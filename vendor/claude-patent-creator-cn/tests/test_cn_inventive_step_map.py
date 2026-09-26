import hashlib
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/cn-patent-application-creator/scripts/validate_inventive_step_map.py"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def write_json(path: Path, value: object) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

def run_val(tmp_path: Path, contract_path: Path, output_path: Path = None):
    cmd = [
        sys.executable, "-B", str(VALIDATOR),
        "--map", str(contract_path),
        "--case-dir", str(tmp_path),
        "--claims", str(tmp_path / "claims.md"),
        "--specification", str(tmp_path / "spec.md")
    ]
    if output_path:
        cmd.extend(["--output", str(output_path)])
    return subprocess.run(cmd, capture_output=True, text=True)

@pytest.fixture
def software_case(tmp_path):
    claims = tmp_path / "claims.md"
    spec = tmp_path / "spec.md"
    ledger = tmp_path / "ledger.json"
    arch = tmp_path / "arch.json"
    ism = tmp_path / "ism.json"

    write(claims, "1. 一种系统，其特征在于，包括双标识绑定。\n2. 根据权利要求1所述的系统，其特征在于，还包括播完释放。\n")
    write(spec, "绑定标识作为播完释放的唯一验证凭证以防盗链。\n")
    write_json(ledger, {
        "schema_id": "cn-patent-feature-ledger/v2",
        "features": [
            {"feature_id": "F010", "classification": "distinguishing", "prior_art_status": {"verdict": "partially_disclosed"}, "claim_sites": [{"claim_number": 1}]},
            {"feature_id": "F011", "classification": "distinguishing", "prior_art_status": {"verdict": "partially_disclosed"}, "claim_sites": [{"claim_number": 2}]}
        ]
    })
    write_json(arch, {
        "core_protection_point": {
            "claim_number": 2, "parent_claim_number": 1,
            "feature_ids": ["F010", "F011"],
            "statement": "...", "review": {"status": "approved", "statement": "ok", "reviewed_at": "2026"}
        }
    })

    ism_data = {
        "schema_id": "cn-patent-inventive-step-map/v1",
        "case_id": "test",
        "source_artifacts": [
            {"artifact_id": "claims", "path": "claims.md", "sha256": digest(claims)},
            {"artifact_id": "specification", "path": "spec.md", "sha256": digest(spec)},
            {"artifact_id": "feature_ledger", "path": "ledger.json", "sha256": digest(ledger)},
            {"artifact_id": "claim_architecture", "path": "arch.json", "sha256": digest(arch)}
        ],
        "references": [
            {"ref_id": "D1", "role": "closest", "citation": "..." },
            {"ref_id": "D2", "role": "combination", "citation": "..." },
            {"ref_id": "COMMON_KNOWLEDGE", "role": "common_knowledge", "citation": "..." }
        ],
        "cells": [
            {"feature_id": "F010", "ref_id": "D1", "disclosed": "partial", "locator": "段落0012"},
            {"feature_id": "F010", "ref_id": "D2", "disclosed": "yes", "locator": "段落0030", "function_match": "same"},
            {"feature_id": "F010", "ref_id": "COMMON_KNOWLEDGE", "common_knowledge_risk": "low", "evidence_type": "无"},
            {"feature_id": "F011", "ref_id": "D1", "disclosed": "yes", "locator": "段落0015", "function_match": "same"},
            {"feature_id": "F011", "ref_id": "D2", "disclosed": "no", "searched_scope": "D2及播放器缓存逻辑"},
            {"feature_id": "F011", "ref_id": "COMMON_KNOWLEDGE", "common_knowledge_risk": "low", "evidence_type": "无"}
        ],
        "couplings": [
            {"feature_a": "F010", "feature_b": "F011", "dependency": "绑定", "statement_anchor": "绑定标识作为播完释放的唯一验证凭证以防盗链"}
        ],
        "claim_assessments": [
            {"claim_set": [1], "min_refs_to_cover": 1, "coupling_evidence": False, "grade": "novelty_risk", "review": {"status": "pending", "statement": ""}},
            {"claim_set": [1, 2], "min_refs_to_cover": 2, "coupling_evidence": True, "grade": "defensible", "review": {"status": "approved", "statement": ""}}
        ]
    }
    write_json(ism, ism_data)
    return tmp_path, ism

def test_software_case_positive(software_case):
    tmp_path, ism = software_case
    res = run_val(tmp_path, ism)
    assert res.returncode == 0
    report = json.loads(res.stdout)
    assert report["status"] == "PASS"
    assert not report["errors"]
    # Idempotency
    res2 = run_val(tmp_path, ism)
    assert res2.stdout == res.stdout

def test_mechanical_case_uncovered(tmp_path):
    claims = tmp_path / "claims.md"
    spec = tmp_path / "spec.md"
    ledger = tmp_path / "ledger.json"
    arch = tmp_path / "arch.json"
    ism = tmp_path / "ism.json"

    write(claims, "1. 一种阀门，包含特征。\n")
    write(spec, "特征。\n")
    write_json(ledger, {
        "schema_id": "cn-patent-feature-ledger/v2",
        "features": [{"feature_id": "F001", "classification": "distinguishing", "prior_art_status": {"verdict": "not_found_in_searched_outlets"}, "claim_sites": [{"claim_number": 1}]}]
    })
    write_json(arch, {})
    write_json(ism, {
        "schema_id": "cn-patent-inventive-step-map/v1",
        "case_id": "test",
        "source_artifacts": [
            {"artifact_id": "claims", "path": "claims.md", "sha256": digest(claims)},
            {"artifact_id": "specification", "path": "spec.md", "sha256": digest(spec)},
            {"artifact_id": "feature_ledger", "path": "ledger.json", "sha256": digest(ledger)},
            {"artifact_id": "claim_architecture", "path": "arch.json", "sha256": digest(arch)}
        ],
        "references": [
            {"ref_id": "D1", "role": "closest", "citation": "..." },
            {"ref_id": "COMMON_KNOWLEDGE", "role": "common_knowledge", "citation": "..." }
        ],
        "cells": [
            {"feature_id": "F001", "ref_id": "D1", "disclosed": "no", "searched_scope": "D1全文及常规阀控制"},
            {"feature_id": "F001", "ref_id": "COMMON_KNOWLEDGE", "common_knowledge_risk": "low", "evidence_type": "无"}
        ],
        "couplings": [],
        "claim_assessments": [
            {"claim_set": [1], "min_refs_to_cover": None, "coupling_evidence": False, "grade": "defensible", "review": {"status": "pending", "statement": ""}}
        ]
    })
    res = run_val(tmp_path, ism)
    assert res.returncode == 0
    report = json.loads(res.stdout)
    assert report["status"] == "PASS"
    assert report["searched_scope"]["F001"] == ["D1全文及常规阀控制"]

def test_medium_ck_risk(software_case):
    tmp_path, ism = software_case
    data = json.loads(ism.read_text("utf-8"))
    # Make F011 CK medium -> it's covered by CK!
    # Original F011 was covered by D1(yes). We change D1 to 'no', and CK to medium
    for c in data["cells"]:
        if c["feature_id"] == "F011" and c["ref_id"] == "D1":
            c["disclosed"] = "no"
            c["searched_scope"] = "D1"
        if c["feature_id"] == "F011" and c["ref_id"] == "COMMON_KNOWLEDGE":
            c["common_knowledge_risk"] = "medium"
            c["evidence_type"] = "xxx"

    # claim_set=[1] (F010) is covered by D2 (min_refs=1) -> novelty_risk
    # claim_set=[1,2] (F010,F011) covered by D2 and CK (min_refs=2). CE=True -> defensible
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 0
    report = json.loads(res.stdout)
    keys = [pd["key"] for pd in report["pending_decisions"]]
    assert "inventive.common_knowledge_medium" in keys


def test_errors(software_case):
    tmp_path, ism = software_case
    data = json.loads(ism.read_text("utf-8"))

    # ISM-SOURCE-STALE
    data["source_artifacts"][0]["sha256"] = "0" * 64
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-SOURCE-STALE" for e in report["errors"])

    # ISM-REF-001
    data = json.loads(ism.read_text("utf-8"))
    data["references"] = [r for r in data["references"] if r["ref_id"] != "COMMON_KNOWLEDGE"]
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-REF-001" for e in report["errors"])

    # ISM-CELL-001
    data = json.loads(ism.read_text("utf-8"))
    for c in data["cells"]:
        if c["disclosed"] == "yes":
            c.pop("locator", None)
            break
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-CELL-001" for e in report["errors"])

    # ISM-COVER-001
    data = json.loads(ism.read_text("utf-8"))
    data["cells"] = [{"feature_id": f"F{i:03d}", "ref_id": "D1", "disclosed": "yes", "locator": "1"} for i in range(1, 17)]
    for i in range(1, 17):
        data["cells"].append({"feature_id": f"F{i:03d}", "ref_id": "COMMON_KNOWLEDGE", "common_knowledge_risk": "low", "evidence_type": "1"})
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-COVER-001" for e in report["errors"])

    # ISM-COUPLING-001
    data = json.loads(ism.read_text("utf-8"))
    data["couplings"][0]["statement_anchor"] = "不存在的话"
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-COUPLING-001" for e in report["errors"])

    # ISM-CLAIMSET-001
    data = json.loads(ism.read_text("utf-8"))
    data["claim_assessments"] = [{"claim_set": [1], "min_refs_to_cover": 1, "coupling_evidence": False, "grade": "novelty_risk", "review": {"status": "pending", "statement": ""}}]
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-CLAIMSET-001" for e in report["errors"])

    # ISM-GRADE-001
    data = json.loads(ism.read_text("utf-8"))
    for ca in data["claim_assessments"]:
        if ca["claim_set"] == [1]:
            ca["grade"] = "defensible" # manually modify to defensible
    write_json(ism, data)
    res = run_val(tmp_path, ism)
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert any(e["code"] == "ISM-GRADE-001" for e in report["errors"])

def test_pending_core_dependent_missing(tmp_path):
    claims = tmp_path / "claims.md"
    spec = tmp_path / "spec.md"
    ledger = tmp_path / "ledger.json"
    arch = tmp_path / "arch.json"
    ism = tmp_path / "ism.json"

    write(claims, "1. 一种系统，其特征在于，包括双标识绑定。\n")
    write(spec, "绑定。\n")
    write_json(ledger, {
        "schema_id": "cn-patent-feature-ledger/v2",
        "features": [{"feature_id": "F010", "classification": "distinguishing", "prior_art_status": {"verdict": "disclosed"}, "claim_sites": [{"claim_number": 1}]}]
    })
    write_json(arch, {})
    write_json(ism, {
        "schema_id": "cn-patent-inventive-step-map/v1",
        "case_id": "test",
        "source_artifacts": [
            {"artifact_id": "claims", "path": "claims.md", "sha256": digest(claims)},
            {"artifact_id": "specification", "path": "spec.md", "sha256": digest(spec)},
            {"artifact_id": "feature_ledger", "path": "ledger.json", "sha256": digest(ledger)},
            {"artifact_id": "claim_architecture", "path": "arch.json", "sha256": digest(arch)}
        ],
        "references": [
            {"ref_id": "D1", "role": "closest", "citation": "..." },
            {"ref_id": "COMMON_KNOWLEDGE", "role": "common_knowledge", "citation": "..." }
        ],
        "cells": [
            {"feature_id": "F010", "ref_id": "D1", "disclosed": "yes", "locator": "x", "function_match": "same"},
            {"feature_id": "F010", "ref_id": "COMMON_KNOWLEDGE", "common_knowledge_risk": "low", "evidence_type": "无"}
        ],
        "couplings": [],
        "claim_assessments": [
            {"claim_set": [1], "min_refs_to_cover": 1, "coupling_evidence": False, "grade": "novelty_risk", "review": {"status": "pending", "statement": ""}}
        ]
    })
    res = run_val(tmp_path, ism)
    assert res.returncode == 0
    report = json.loads(res.stdout)
    assert "inventive.core_dependent_missing" in [pd["key"] for pd in report["pending_decisions"]]


def _report(tmp_path, ism):
    res = run_val(tmp_path, ism)
    return res.returncode, json.loads(res.stdout)


def test_coupling_covered_by_single_reference_does_not_count(software_case):
    tmp_path, ism = software_case
    data = json.loads(ism.read_text("utf-8"))
    for c in data["cells"]:
        if c["feature_id"] == "F011" and c["ref_id"] == "D2":
            c.update({"disclosed": "yes", "locator": "段落0031", "function_match": "same"})
    for ca in data["claim_assessments"]:
        if ca["claim_set"] == [1, 2]:
            ca["grade"] = "novelty_risk"
    write_json(ism, data)
    code, report = _report(tmp_path, ism)
    assert code == 0
    pair = next(a for a in report["claim_assessments"] if a["claim_set"] == [1, 2])
    assert pair["min_refs_to_cover"] == 1 and pair["coupling_evidence"] is False and pair["grade"] == "novelty_risk"
    assert any(r["code"] == "ISM-COUPLING-002" for r in report["review_required"])


def test_common_knowledge_cover_never_counts_as_different_function(software_case):
    tmp_path, ism = software_case
    data = json.loads(ism.read_text("utf-8"))
    data["couplings"] = []
    for c in data["cells"]:
        if c["feature_id"] == "F010" and c["ref_id"] == "D2":
            c["function_match"] = "different"
        if c["feature_id"] == "F011" and c["ref_id"] == "D1":
            c.update({"disclosed": "no", "searched_scope": "D1 全文"})
        if c["feature_id"] == "F011" and c["ref_id"] == "COMMON_KNOWLEDGE":
            c["common_knowledge_risk"] = "high"
    for ca in data["claim_assessments"]:
        if ca["claim_set"] == [1, 2]:
            ca["grade"] = "weak"
    write_json(ism, data)
    code, report = _report(tmp_path, ism)
    assert code == 0
    pair = next(a for a in report["claim_assessments"] if a["claim_set"] == [1, 2])
    assert pair["min_refs_to_cover"] == 2 and pair["grade"] == "weak"
    assert any(p["key"] == "inventive.core_set_not_defensible" for p in report["pending_decisions"])


def test_feature_not_in_ledger_or_not_distinguishing_is_blocked(software_case):
    tmp_path, ism = software_case
    ledger_path = tmp_path / "ledger.json"
    ledger = json.loads(ledger_path.read_text("utf-8"))
    ledger["features"][1]["classification"] = "preamble"
    write_json(ledger_path, ledger)
    data = json.loads(ism.read_text("utf-8"))
    data["source_artifacts"][2]["sha256"] = digest(ledger_path)
    write_json(ism, data)
    code, report = _report(tmp_path, ism)
    assert code == 2 and any(e["code"] == "ISM-CELL-002" for e in report["errors"])


def test_not_searched_feature_is_treated_as_common_knowledge_and_pending(software_case):
    tmp_path, ism = software_case
    ledger_path = tmp_path / "ledger.json"
    ledger = json.loads(ledger_path.read_text("utf-8"))
    ledger["features"][1]["prior_art_status"] = {"verdict": "not_searched"}
    write_json(ledger_path, ledger)
    data = json.loads(ism.read_text("utf-8"))
    data["source_artifacts"][2]["sha256"] = digest(ledger_path)
    for c in data["cells"]:
        if c["feature_id"] == "F011" and c["ref_id"] == "D1":
            c.update({"disclosed": "no", "searched_scope": "D1 全文"})
    write_json(ism, data)
    code, report = _report(tmp_path, ism)
    assert code == 0
    assert any(p["key"] == "inventive.feature_not_searched" for p in report["pending_decisions"])
    pair = next(a for a in report["claim_assessments"] if a["claim_set"] == [1, 2])
    assert pair["min_refs_to_cover"] == 2  # D2 + COMMON_KNOWLEDGE（未检索视同覆盖）


def test_validation_is_idempotent(software_case):
    tmp_path, ism = software_case
    first = run_val(tmp_path, ism).stdout
    second = run_val(tmp_path, ism).stdout
    assert first == second
