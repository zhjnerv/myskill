"""红队报告只接受三种攻击结果，并按案件目录复核四文书字节。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/cn-patent-application-creator/scripts/validate_red_team_report.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_case(tmp_path: Path) -> dict[str, str]:
    names = {
        "claims": "02-申请文件/权利要求书.md",
        "specification": "02-申请文件/说明书.md",
        "abstract": "02-申请文件/说明书摘要.md",
        "drawings": "02-申请文件/说明书附图/图1.png",
    }
    hashes = {}
    for role, relative in names.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{role}-bytes".encode("utf-8"))
        hashes[role] = digest(path)
    return hashes


def report(hashes: dict[str, str], **overrides) -> dict:
    payload = {
        "schema_id": "cn-patent-red-team-report/v1",
        "case_id": "case",
        "team": "package",
        "legal_effect": "ADVISORY_ONLY",
        "bound_artifacts": [
            {"role": role, "path": relative, "sha256": hashes[role]}
            for role, relative in (
                ("claims", "02-申请文件/权利要求书.md"),
                ("specification", "02-申请文件/说明书.md"),
                ("abstract", "02-申请文件/说明书摘要.md"),
                ("drawings", "02-申请文件/说明书附图/图1.png"),
            )
        ],
        "attacks": [{
            "attack_id": "A001",
            "checklist_item": "摘要是否扩大保护范围",
            "result": "攻击未奏效",
            "evidence": "摘要未增加权利要求没有的特征",
        }],
        "disposition": "NO_RETURN",
        "pending_decisions": [{
            "key": "redteam.evidence_gap",
            "source": {"tool_id": "red_team", "rule_id": "RED-EVIDENCE"},
            "target": {"kind": "review", "locator": "新颖性"},
            "question": "是否补做逐项比对？",
            "adopted_default": "新颖性和创造性保持 INCONCLUSIVE",
            "options": ["补做比对", "维持未决"],
            "impact": ["evidence"],
            "decider": "attorney",
        }],
    }
    payload.update(overrides)
    return payload


def run(tmp_path: Path, payload: dict) -> tuple[subprocess.CompletedProcess[str], dict]:
    report_path = tmp_path / "red-team-report.json"
    output = tmp_path / "red-team-validation.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--case-dir", str(tmp_path), "--report", str(report_path), "--output", str(output)],
        capture_output=True, text=True, encoding="utf-8",
    )
    return result, json.loads(output.read_text(encoding="utf-8"))


def test_inconclusive_attack_without_return_passes(tmp_path):
    hashes = write_case(tmp_path)
    payload = report(hashes)
    payload["attacks"].append({
        "attack_id": "A002",
        "checklist_item": "新颖性",
        "result": "证据不足",
        "evidence": "没有 CNIPA 逐项比对",
    })
    result, validation = run(tmp_path, payload)
    assert result.returncode == 0, result.stdout + result.stderr
    assert validation["status"] == "PASS"


def test_only_successful_attack_returns_to_drafting(tmp_path):
    hashes = write_case(tmp_path)
    payload = report(hashes)
    payload["attacks"][0]["result"] = "攻击奏效"
    result, validation = run(tmp_path, payload)
    assert result.returncode == 2
    assert any(item["code"] == "RED-DISPOSITION" for item in validation["errors"])

    payload["disposition"] = "RETURN_TO_DRAFTING"
    result, validation = run(tmp_path, payload)
    assert result.returncode == 0, result.stdout + result.stderr
    assert validation["status"] == "PASS"


def test_unknown_result_hash_mismatch_and_handwritten_pending_fail(tmp_path):
    hashes = write_case(tmp_path)
    payload = report(hashes)
    payload["attacks"][0]["result"] = "可能有问题"
    result, validation = run(tmp_path, payload)
    assert result.returncode == 2
    assert any(item["code"] == "RED-ATTACK" for item in validation["errors"])

    payload = report(hashes)
    payload["bound_artifacts"][0]["sha256"] = "0" * 64
    result, validation = run(tmp_path, payload)
    assert any("SHA-256" in item["message"] for item in validation["errors"])

    payload = report(hashes)
    payload["pending_decisions"][0]["id"] = "D001"
    result, validation = run(tmp_path, payload)
    assert result.returncode == 2
    assert any(item["code"] == "RED-PENDING-SHAPE" for item in validation["errors"])
