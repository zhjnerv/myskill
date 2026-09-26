"""独立中国专利 Skill 包的轻量边界回归。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_boundary_verifier_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_package.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"


def test_no_business_slash_commands_or_mcp_server_are_bundled():
    assert not (ROOT / "commands").exists()
    assert not (ROOT / "mcp_server").exists()


def test_orchestrator_is_lightweight_and_routes_by_stage():
    text = (ROOT / "skills" / "cn-patent-workflow" / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 100
    for skill in (
        "cn-patent-application-creator",
        "cn-patent-reviewer",
        "cn-patent-claims-analyzer",
        "cn-patent-specification-reviewer",
        "cn-patent-formalities-reviewer",
        "cn-patent-diagram-generator",
    ):
        assert skill in text
    assert "不启动 MCP Server" in text
    assert "FAISS" in text


def test_legal_sources_have_topic_router():
    index_path = ROOT / "references" / "cn-legal-sources" / "source-index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["schema_id"] == "cn-patent-legal-source-index/v1"
    assert payload["policy"]["default"] == "load_topic_files_only"
    assert "claims_and_support" in payload["topics"]
    assert "subject_matter_and_computer_programs" in payload["topics"]


def test_package_verifier_uses_shared_distribution_boundary():
    verifier = (ROOT / "scripts/verify_package.py").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/install_codex_skill.py").read_text(encoding="utf-8")
    assert "collect_source_files" in verifier
    assert "collect_source_files" in installer
    assert "install_codex_skill.py" in verifier
    assert ".local-case-archive" in installer
    assert "SOURCE_SUFFIXES" in installer


def test_project_docx_template_is_approved_for_distribution():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cn_codex_install_policy_template", ROOT / "scripts" / "install_codex_skill.py"
    )
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    files, errors = installer.collect_source_files(ROOT, distribution_only=True)
    assert errors == [], errors
    assert ROOT / "模版.docx" in files
    assert "模版.docx" in installer.APPROVED_BINARY_ASSETS
