#!/usr/bin/env python3
"""验证中国专利 Skill 包的独立性、资源完整性和轻量边界。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 安装器与验证器加载同一份分发策略；不复制规则，也不依赖工作区 PYTHONPATH。
import importlib.util
_policy_path = Path(__file__).resolve().with_name("install_codex_skill.py")
_policy_spec = importlib.util.spec_from_file_location("cn_codex_install_policy", _policy_path)
if _policy_spec is None or _policy_spec.loader is None:
    raise RuntimeError(f"无法加载分发策略：{_policy_path}")
_policy = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(_policy)
REQUIRED_SKILLS = _policy.REQUIRED_SKILLS
collect_source_files = _policy.collect_source_files

FORBIDDEN_TOP_LEVEL = {"mcp_server", "commands"}

FORBIDDEN_DEPENDENCIES = {
    "torch",
    "sentence-transformers",
    "faiss-cpu",
    "rank-bm25",
    "google-cloud-bigquery",
    "mcp",
}


def main() -> int:
    files, errors = collect_source_files(ROOT, distribution_only=False)

    for name in sorted(REQUIRED_SKILLS):
        if not (ROOT / "skills" / name / "SKILL.md").is_file():
            errors.append(f"缺少 Skill：{name}")

    for name in sorted(FORBIDDEN_TOP_LEVEL):
        if (ROOT / name).exists():
            errors.append(f"存在禁止的重型目录：{name}")

    legal_root = ROOT / "references" / "cn-legal-sources"
    for relative in (
        "专利法(2020-10-17).md",
        "专利法实施细则(2023-12-21).md",
        "审查指南2026MD/guide-full.md",
        "source-index.json",
    ):
        path = legal_root / relative
        try:
            if path.is_symlink() or not path.is_file() or not path.read_bytes():
                errors.append(f"法源缺失或为空：{relative}")
        except OSError as exc:
            errors.append(f"无法读取法源：{relative}：{exc}")

    try:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"无法读取 pyproject.toml：{exc}")
        pyproject = ""
    for dependency in sorted(FORBIDDEN_DEPENDENCIES):
        if f'"{dependency}' in pyproject:
            errors.append(f"不应引入主项目重型依赖：{dependency}")

    for path in files:
        relative = path.relative_to(ROOT)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(f"源文件不可读取：{relative}：{exc}")
            continue
        if relative.as_posix() in _policy.APPROVED_BINARY_ASSETS:
            if path.suffix.lower() != ".docx" or not raw.startswith(b"PK\x03\x04"):
                errors.append(f"核准模板不是有效 DOCX：{relative}")
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"源文件不是 UTF-8 文本：{relative}：{exc}")
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"文件含 UTF-8 BOM：{relative}")
        if path.suffix == ".json":
            try:
                json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"JSON 无效：{relative}：{exc}")
        if path.suffix in {".py", ".md"} and path.resolve() != Path(__file__).resolve():
            text = raw.decode("utf-8", errors="replace")
            if "from mcp_server" in text or "import mcp_server" in text:
                errors.append(f"存在对主项目 mcp_server 的反向依赖：{relative}")

    report = {
        "schema_id": "cn-patent-skill-package-verification/v1",
        "status": "PASS" if not errors else "FAIL",
        "required_skills": sorted(REQUIRED_SKILLS),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
