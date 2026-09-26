"""Codex 文件系统 Skill 一键安装器回归测试。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_codex_skill.py"


def test_codex_skill_installer_installs_router_and_stage_skills(tmp_path):
    codex_home = tmp_path / ".codex"
    completed = subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--source",
            str(ROOT),
            "--codex-home",
            str(codex_home),
            "--skip-deps",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["entry_skill"] == "cn-patent-workflow"
    runtime = codex_home / "vendor" / "claude-patent-creator-cn"
    manifest = json.loads((runtime / "codex-install.json").read_text(encoding="utf-8"))
    assert manifest["invocation"] == "$cn-patent-workflow"
    assert len(manifest["skills"]) == 7
    for item in manifest["skills"]:
        skill = codex_home / "skills" / item["name"]
        assert (skill / "SKILL.md").is_file()
    router = (codex_home / "skills" / "cn-patent-workflow" / "SKILL.md").read_text(encoding="utf-8")
    assert "cn-patent-application-creator" in router


def test_codex_skill_installer_force_updates_existing_runtime(tmp_path):
    codex_home = tmp_path / ".codex"
    base = [
        sys.executable, str(INSTALLER), "--source", str(ROOT),
        "--codex-home", str(codex_home), "--skip-deps",
    ]
    subprocess.run(base, check=True, capture_output=True, text=True)
    marker = codex_home / "vendor" / "claude-patent-creator-cn" / "stale.txt"
    marker.write_text("stale", encoding="utf-8")
    completed = subprocess.run(
        [*base, "--force"], check=True, capture_output=True, text=True
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert not marker.exists()
    for item in result["skills"]:
        assert (Path(item["path"]) / "SKILL.md").is_file()
