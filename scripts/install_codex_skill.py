#!/usr/bin/env python3
"""把本仓库以 Codex 文件系统 Skill 集合一键安装到用户目录。"""
from __future__ import annotations

import argparse
import json
import os
import importlib.util
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

PLUGIN_NAME = "cn-patent-agent-skills"

REQUIRED_SKILLS = (
    "cn-patent-workflow", "cn-patent-application-creator", "cn-patent-claims-analyzer",
    "cn-patent-diagram-generator", "cn-patent-formalities-reviewer", "cn-patent-reviewer",
    "cn-patent-specification-reviewer",
)
RUNTIME_ENTRIES = (
    ".codex-plugin", "assets", "references", "scripts", "skills",
    "AGENTS.md", "CHANGELOG.md", "LICENSE", "README.md", "pyproject.toml",
    "模版.docx",
)
SOURCE_SUFFIXES = frozenset({".py", ".md", ".json", ".toml", ".txt"})
ROOT_TEXT_FILES = frozenset({"LICENSE", ".gitignore", ".gitattributes"})
APPROVED_BINARY_ASSETS = frozenset({"模版.docx"})
CACHE_DIRS = frozenset({".git", ".venv", "venv", ".pytest_cache", "__pycache__"})
LOCAL_DIRS = frozenset({".local-case-archive", "archive", "dist", "build", "tmp", "temp"})
# 依赖取消要给进程一点时间消化 SIGTERM；测试可调低。SIGTERM 被忽略时再 SIGKILL。
DEPENDENCY_CANCEL_GRACE_SECONDS = 2.0
MANUAL_RESTORE_REQUIRED = "必须人工确认后才能恢复"
DEPENDENCY_BLOCK_KEY = "dependency_processes"
LEGAL_INDEX_SCHEMA = "cn-patent-legal-source-index/v1"
LEGAL_SOURCE_FILES = {
    "patent_law": "专利法(2020-10-17).md",
    "implementing_rules": "专利法实施细则(2023-12-21).md",
    "examination_guide_full": "审查指南2026MD/guide-full.md",
}
# 各 Skill 当前真实脚本。不把示例、legacy 对照和稳定性样本写进必需清单；
# 法源分章跟着 source-index.json 走，不在这里逐个写死文件名。
REQUIRED_SKILL_SCRIPTS = {
    "cn-patent-workflow": ("workflow_plan.py",),
    "cn-patent-application-creator": (
        "analyze_template_style.py", "assemble_application_docx.py", "build_feature_ledger.py",
        "check_stage_gate.py", "cn_drafting_io.py", "collect_pending_decisions.py",
        "generate_search_query.py", "merge_template_styles.py", "pending_file.py",
        "rank_template_candidates.py", "read_pending_file.py", "style_applicator.py",
        "template_style_contract.py", "validate_claim_architecture.py",
        "validate_inventive_step_map.py", "validate_red_team_report.py", "verify_docx_assembly.py",
    ),
    "cn-patent-claims-analyzer": ("check_claims_cn.py",),
    "cn-patent-diagram-generator": (
        "analyze_drawing_reference.py", "check_stability_evidence.py", "export_patent_drawio.py",
        "sanitize_drawing_reference.py", "validate_drawing_brief.py",
        "validate_drawing_style_brief.py", "verify_drawing_docx_delivery.py",
        "verify_patent_drawings.py",
    ),
    "cn-patent-formalities-reviewer": ("check_formalities_cn.py",),
    "cn-patent-reviewer": ("build_review_bundle.py", "cn_contract.py", "verify_review_bundle.py"),
    "cn-patent-specification-reviewer": ("build_support_matrix_cn.py",),
}
# 跨 Skill 的必要合同：审查规范是脚本按路径加载的，其余三个是现行流程/附图合同。
REQUIRED_CONTRACTS = (
    ("skills/cn-patent-reviewer/references/cn-review-contract-v2.json",
     "schema_version", "cn-patent-review-contract/v2"),
    ("skills/cn-patent-workflow/references/workflow-plan-schema-v1.json",
     "$id", "cn-patent-workflow-plan/v1"),
    ("skills/cn-patent-diagram-generator/references/patent-drawing-brief-schema-v4.json",
     "$id", "cn-patent-drawing-brief/v4"),
    ("skills/cn-patent-diagram-generator/references/drawing-style-brief-schema.json",
     "$id", "cn-patent-drawing-style-brief/v1"),
)


def is_local_directory(name: str) -> bool:
    return name.lower() in LOCAL_DIRS or name.lower().endswith("-workspace")


def collect_source_files(root: Path, *, distribution_only: bool = True) -> tuple[list[Path], list[str]]:
    """返回可读/可复制文件及阻断错误；不跟随链接，不读取被拒绝目录或文件。"""
    files: list[Path] = []
    errors: list[str] = []

    def visit(path: Path) -> None:
        relative = path.relative_to(root)
        try:
            if path.is_symlink():
                errors.append(f"分发边界不允许符号链接：{relative}")
            elif path.is_dir():
                if path.name in CACHE_DIRS or path.name.endswith(".egg-info"):
                    return
                if is_local_directory(path.name):
                    errors.append(f"分发树内存在本地归档/临时目录：{relative}")
                    return
                for child in sorted(path.iterdir()):
                    visit(child)
            elif path.name == ".git" and path.parent == root:
                # 链接工作树根上的 .git 是 gitdir 指针文件，不是待分发资产。
                return
            elif not path.is_file():
                errors.append(f"不是普通源文件：{relative}")
            elif (
                path.suffix.lower() not in SOURCE_SUFFIXES
                and str(relative) not in ROOT_TEXT_FILES
                and relative.as_posix() not in APPROVED_BINARY_ASSETS
            ):
                errors.append(f"未获准分发的文件类型（临时产物或未经审核的资产）：{relative}")
            else:
                files.append(path)
        except OSError as exc:
            errors.append(f"无法检查源路径：{relative}：{exc}")

    candidates = ([root / name for name in RUNTIME_ENTRIES
                   if (root / name).exists() or (root / name).is_symlink()]
                  if distribution_only else
                  [path for path in root.iterdir()
                   if not is_local_directory(path.name) and path.name not in {".coverage", "htmlcov"}])
    for path in sorted(candidates):
        visit(path)
    return files, errors


TRANSACTION_NAME = f".{PLUGIN_NAME}.transaction.json"
BACKUP_NAME = f".{PLUGIN_NAME}.backup"
ENTRY_BACKUP_NAME = f".{PLUGIN_NAME}.entries.backup"
_SIGNAL_CONTEXT: tuple[Path, Path] | None = None


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def copy_runtime(source: Path, staging: Path) -> None:
    files, errors = collect_source_files(source, distribution_only=True)
    if errors:
        raise RuntimeError("源包不满足分发边界：\n" + "\n".join(f"- {e}" for e in errors))
    staging.mkdir(parents=True, exist_ok=False)
    for path in files:
        relative = path.relative_to(source)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")



def _is_safe_relative(value: str) -> bool:
    """包内相对路径。POSIX 上也按 Windows 规则拒绝盘符、驱动器相对路径、UNC 和反斜杠。"""
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    if value.startswith(("/", "\\")):
        return False
    windows = PureWindowsPath(value)
    if windows.drive or windows.root or windows.anchor or windows.is_absolute():
        return False
    parts = windows.parts
    if not parts or any(part in {"", ".", ".."} or ":" in part or "\\" in part for part in parts):
        return False
    posix = PurePosixPath(value)
    if posix.is_absolute() or not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        return False
    return True


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _is_regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file()
    except OSError:
        return False


def _read_required_text(path: Path, label: str, errors: list[str]) -> str | None:
    if not _is_regular_file(path):
        errors.append(f"必需文件缺失或不是普通文件：{label}")
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"无法读取必需文件：{label}：{exc}")
        return None
    if not raw:
        errors.append(f"必需文件为空：{label}")
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append(f"必需文件含 UTF-8 BOM：{label}")
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"必需文件不是 UTF-8：{label}：{exc}")
        return None


def required_package_files(root: Path) -> list[str]:
    """完整性所需相对路径。法源分章来自该包的 source-index，不逐个写死。"""
    files = [
        ".codex-plugin/plugin.json", "pyproject.toml", "scripts/run_python.py",
        "scripts/verify_package.py", "scripts/install_codex_skill.py", "模版.docx",
        "references/cn-legal-sources/source-index.json",
    ]
    for relative in LEGAL_SOURCE_FILES.values():
        files.append(f"references/cn-legal-sources/{relative}")
    for skill in REQUIRED_SKILLS:
        files.append(f"skills/{skill}/SKILL.md")
        for name in REQUIRED_SKILL_SCRIPTS.get(skill, ()):
            files.append(f"skills/{skill}/scripts/{name}")
    for relative, _key, _expected in REQUIRED_CONTRACTS:
        files.append(relative)
    index = root / "references" / "cn-legal-sources" / "source-index.json"
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    topics = payload.get("topics") if isinstance(payload, dict) else None
    if isinstance(topics, dict):
        for rels in topics.values():
            if not isinstance(rels, list):
                continue
            for relative in rels:
                if isinstance(relative, str) and _is_safe_relative(relative):
                    files.append(f"references/cn-legal-sources/{relative}")
    return _dedupe(files)


def _contained_legal_path(legal_root: Path, relative: str) -> Path | None:
    """逐段拼接。拒绝盘符片段，避免 Windows 上把 C:foo 当成新的路径根。不访问候选路径。"""
    if not _is_safe_relative(relative):
        return None
    candidate = legal_root
    for part in PurePosixPath(relative).parts:
        if part in {"", ".", ".."} or ":" in part or "\\" in part or "/" in part:
            return None
        candidate = candidate / part
    try:
        candidate.relative_to(legal_root)
    except ValueError:
        return None
    root_text = os.path.normpath(os.fspath(legal_root))
    cand_text = os.path.normpath(os.fspath(candidate))
    try:
        if os.path.commonpath([root_text, cand_text]) != root_text:
            return None
    except ValueError:
        return None
    return candidate


def _require_legal_file(legal_root: Path, relative: str, errors: list[str], seen: set[str]) -> None:
    if relative in seen:
        return
    seen.add(relative)
    path = _contained_legal_path(legal_root, relative)
    if path is None:
        errors.append(f"法源索引含非法路径：{relative!r}")
        return
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"法源缺失或为空：{relative}")
    except OSError as exc:
        errors.append(f"无法读取法源：{relative}：{exc}")


def check_package_integrity(root: Path) -> list[str]:
    """与 pip/venv 无关的运行资源检查。缺失或空壳插件清单不能算完整包。"""
    errors: list[str] = []
    plugin = _read_required_text(root / ".codex-plugin" / "plugin.json", ".codex-plugin/plugin.json", errors)
    if plugin is not None:
        try:
            payload = json.loads(plugin)
        except json.JSONDecodeError as exc:
            errors.append(f"插件清单不是 JSON：.codex-plugin/plugin.json：{exc}")
        else:
            if not isinstance(payload, dict):
                errors.append("插件清单顶层必须是 JSON 对象：.codex-plugin/plugin.json")
            else:
                if payload.get("name") != PLUGIN_NAME:
                    errors.append(f"插件清单 name 必须是 {PLUGIN_NAME}")
                skills = payload.get("skills")
                if not isinstance(skills, str) or not skills.strip():
                    errors.append("插件清单缺少有效 skills 路径")
                version = payload.get("version")
                if not isinstance(version, str) or not version.strip():
                    errors.append("插件清单缺少有效 version")
    project = _read_required_text(root / "pyproject.toml", "pyproject.toml", errors)
    if project is not None and 'name = "cn-patent-agent-skills"' not in project:
        errors.append("pyproject.toml 不是本包项目文件")
    runner = _read_required_text(root / "scripts" / "run_python.py", "scripts/run_python.py", errors)
    if runner is not None and "def main" not in runner:
        errors.append("运行入口 scripts/run_python.py 不是有效 runner")
    verifier = _read_required_text(root / "scripts" / "verify_package.py", "scripts/verify_package.py", errors)
    if verifier is not None and "def verify_tree" not in verifier:
        errors.append("scripts/verify_package.py 不是包完整性验证器")
    installer = _read_required_text(
        root / "scripts" / "install_codex_skill.py", "scripts/install_codex_skill.py", errors)
    if installer is not None and "def check_package_integrity" not in installer:
        errors.append("scripts/install_codex_skill.py 缺少共享完整性检查")
    template = root / "模版.docx"
    if template.is_symlink() or not template.is_file():
        errors.append("默认模板缺失：模版.docx")
    else:
        try:
            with template.open("rb") as handle:
                magic = handle.read(4)
            if template.stat().st_size <= 0 or magic != b"PK\x03\x04":
                errors.append("默认模板不是有效 DOCX：模版.docx")
        except OSError as exc:
            errors.append(f"无法读取默认模板：模版.docx：{exc}")
    for skill in REQUIRED_SKILLS:
        label = f"skills/{skill}/SKILL.md"
        text = _read_required_text(root / "skills" / skill / "SKILL.md", label, errors)
        if text is not None and not text.strip():
            errors.append(f"必需文件为空：{label}")
        scripts = REQUIRED_SKILL_SCRIPTS.get(skill)
        if not scripts:
            errors.append(f"安装器未声明 Skill 的真实脚本：{skill}")
            continue
        for name in scripts:
            script_label = f"skills/{skill}/scripts/{name}"
            script_text = _read_required_text(root / script_label, script_label, errors)
            if script_text is not None and not script_text.strip():
                errors.append(f"必需文件为空：{script_label}")
    for relative, key, expected in REQUIRED_CONTRACTS:
        text = _read_required_text(root / relative, relative, errors)
        if text is None:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"必要合同不是 JSON：{relative}：{exc}")
            continue
        ident = payload.get(key) if isinstance(payload, dict) else None
        if ident != expected:
            errors.append(f"必要合同标识不符：{relative} 需要 {key}={expected}")
    legal = root / "references" / "cn-legal-sources"
    index_label = "references/cn-legal-sources/source-index.json"
    index_text = _read_required_text(legal / "source-index.json", index_label, errors)
    seen: set[str] = set()
    if index_text is not None:
        try:
            payload = json.loads(index_text)
        except json.JSONDecodeError as exc:
            errors.append(f"法源索引无法读取或不是 JSON：source-index.json：{exc}")
            payload = None
        if not isinstance(payload, dict) or payload.get("schema_id") != LEGAL_INDEX_SCHEMA:
            errors.append(f"法源索引无效：schema_id 不是 {LEGAL_INDEX_SCHEMA}")
        else:
            policy = payload.get("policy")
            if not isinstance(policy, dict) or policy.get("default") != "load_topic_files_only":
                errors.append("法源索引无效：policy.default 不是 load_topic_files_only")
            sources = payload.get("sources")
            if not isinstance(sources, dict):
                errors.append("法源索引无效：缺少 sources")
                sources = {}
            for key, relative in LEGAL_SOURCE_FILES.items():
                if sources.get(key) != relative:
                    errors.append(f"法源索引未声明必要文件：{key} -> {relative}")
                if _is_safe_relative(relative):
                    _require_legal_file(legal, relative, errors, seen)
            topics = payload.get("topics")
            if not isinstance(topics, dict) or not topics:
                errors.append("法源索引无效：缺少 topics")
            else:
                for topic, rels in topics.items():
                    if not isinstance(rels, list) or not rels:
                        errors.append(f"法源主题无效：{topic}")
                        continue
                    for relative in rels:
                        if not isinstance(relative, str) or not _is_safe_relative(relative):
                            rendered = repr(relative) if isinstance(relative, str) else type(relative).__name__
                            errors.append(f"法源索引含非法路径：{topic}：{rendered}")
                            continue
                        _require_legal_file(legal, relative, errors, seen)
    return errors


_VERIFY_MODULE: Any = None
_TRACKED_DEPENDENCY_PROCESSES: list[dict[str, Any]] = []


def _load_verify_module() -> Any:
    """加载与本安装器同目录的验证器。

    完整性规则以正在执行的安装器为准。不执行候选包里的 verify_package.py，
    避免候选删除必需 Skill 后仍给自己签发 PASS。
    """
    global _VERIFY_MODULE
    if _VERIFY_MODULE is not None:
        return _VERIFY_MODULE
    path = Path(__file__).resolve().with_name("verify_package.py")
    spec = importlib.util.spec_from_file_location("cn_codex_verify_package_for_install", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载完整性验证器：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _VERIFY_MODULE = module
    return module


def _verify_staged_tree(root: Path) -> list[str]:
    errors = _load_verify_module().verify_tree(root)
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise RuntimeError("完整性验证器返回了无法理解的结果")
    return errors


def _register_dependency_process(process: subprocess.Popen[Any], *, group: bool) -> dict[str, Any]:
    record: dict[str, Any] = {
        "process": process,
        "group": bool(group) and os.name == "posix",
        "pgid": None,
        "leader_pid": process.pid,
        "leader_starttime": None,
        "group_proven": False,
    }
    if record["group"]:
        _capture_group_proof(record)
    _TRACKED_DEPENDENCY_PROCESSES.append(record)
    return record


def _discard_dependency_process(record: dict[str, Any]) -> None:
    try:
        _TRACKED_DEPENDENCY_PROCESSES.remove(record)
    except ValueError:
        pass


def _pid_exists(pid: int) -> bool:
    if pid <= 1 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _proc_stat(pid: int) -> tuple[str, int, int] | None:
    """返回 (state, pgrp, starttime)。comm 可能含空格和括号，所以从最后一个 ')' 后面拆。"""
    if pid <= 0:
        return None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    marker = raw.rfind(")")
    if marker < 0 or marker + 2 >= len(raw):
        return None
    fields = raw[marker + 2:].split()
    # 去掉 pid 和 comm 后，state/pgrp/starttime 分别是第 3、5、22 字段。
    if len(fields) < 20:
        return None
    try:
        return fields[0], int(fields[2]), int(fields[19])
    except ValueError:
        return None


def _iter_proc_pids() -> list[int]:
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    pids: list[int] = []
    for name in names:
        if name.isdigit():
            pids.append(int(name))
    return pids


def _capture_group_proof(record: dict[str, Any]) -> None:
    """在回收父进程之前记下进程组身份。之后父进程退出也不能再向 getpgid 要这个身份。"""
    pid = record["process"].pid
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        record["group_refused"] = True
        return
    stat = _proc_stat(pid)
    start = None if stat is None else stat[2]
    own = os.getpgrp()
    proven = (
        isinstance(pgid, int) and pgid > 1 and pgid == pid and pgid != own
        and isinstance(start, int) and Path("/proc").is_dir()
    )
    record["pgid"] = pgid if isinstance(pgid, int) else None
    record["leader_pid"] = pid
    record["leader_starttime"] = start
    record["group_proven"] = proven
    if not proven:
        record["group_refused"] = True


def _group_id_reused(record: dict[str, Any]) -> bool:
    """leader pid 已换成另一段生命，并且它正占着我们保存的进程组号时，killpg 会打到别人。"""
    stat = _proc_stat(record.get("leader_pid"))
    if stat is None:
        return False
    _state, pgrp, starttime = stat
    saved = record.get("leader_starttime")
    if not isinstance(saved, int) or starttime == saved:
        return False
    return pgrp == record.get("pgid")


def _proven_group_members(record: dict[str, Any]) -> tuple[str, list[int]]:
    """返回 ('empty'|'live'|'unproven', 非僵尸成员)。

    父进程退出后 /proc 父树会消失，同组子孙仍可能活着。只认启动时证明过的进程组号。
    """
    if record.get("group_unproven") or not record.get("group_proven"):
        return "unproven", []
    if os.name != "posix" or not Path("/proc").is_dir():
        return "unproven", []
    if _group_id_reused(record):
        record["group_unproven"] = True
        return "unproven", []
    pgid = record.get("pgid")
    if not isinstance(pgid, int) or pgid <= 1 or pgid == os.getpgrp():
        record["group_refused"] = True
        record["group_unproven"] = True
        return "unproven", []
    live: list[int] = []
    for pid in _iter_proc_pids():
        if pid <= 1 or pid == os.getpid():
            continue
        stat = _proc_stat(pid)
        if stat is None:
            continue
        state, pgrp, starttime = stat
        if pgrp != pgid or state == "Z":
            continue
        if pgrp == os.getpgrp():
            record["group_refused"] = True
            record["group_unproven"] = True
            return "unproven", []
        if pid == record.get("leader_pid") and starttime != record.get("leader_starttime"):
            record["group_unproven"] = True
            return "unproven", []
        live.append(pid)
    return ("live", live) if live else ("empty", [])


def _posix_descendants(pid: int) -> list[int]:
    if os.name != "posix" or not Path("/proc").is_dir():
        return []
    seen = {pid, os.getpid()}
    found: list[int] = []
    stack = [pid]
    while stack:
        current = stack.pop()
        try:
            text = Path(f"/proc/{current}/task/{current}/children").read_text(encoding="utf-8")
        except OSError:
            continue
        for part in text.split():
            try:
                child = int(part)
            except ValueError:
                continue
            if child in seen or child <= 1:
                continue
            seen.add(child)
            found.append(child)
            stack.append(child)
    return found


def _pinned_in_group(pid: int, pgid: int) -> bool:
    stat = _proc_stat(pid)
    if stat is None:
        return False
    state, pgrp, _start = stat
    return state != "Z" and pgrp == pgid


def _signal_proven_group(record: dict[str, Any], sig: int) -> str:
    status, members = _proven_group_members(record)
    if status != "live":
        return status
    opener = getattr(os, "pidfd_open", None)
    sender = getattr(signal, "pidfd_send_signal", None)
    pins: list[tuple[int, int]] = []
    try:
        if opener is not None:
            for pid in members:
                try:
                    pins.append((pid, opener(pid)))
                except OSError:
                    continue
        if _group_id_reused(record):
            record["group_unproven"] = True
            return "unproven"
        pgid = record.get("pgid")
        if not isinstance(pgid, int) or pgid <= 1 or pgid == os.getpgrp():
            record["group_refused"] = True
            record["group_unproven"] = True
            return "unproven"
        pinned_live = [(pid, fd) for pid, fd in pins if _pinned_in_group(pid, pgid)]
        observed, _members = _proven_group_members(record)
        if observed == "unproven":
            return "unproven"
        # 钉住的活进程还在本组里时，组号不能被复用。没有 pidfd 时，两次扫描都看到活进程才发组信号。
        if not pinned_live and observed != "live":
            return observed
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            record["group_unproven"] = True
            return "unproven"
        if sender is not None:
            for _pid, fd in pinned_live:
                try:
                    sender(fd, sig)
                except OSError:
                    pass
        return "live"
    finally:
        for _pid, fd in pins:
            try:
                os.close(fd)
            except OSError:
                pass


def _signal_direct(record: dict[str, Any], sig: int) -> None:
    process: subprocess.Popen[Any] = record["process"]
    if process.poll() is not None:
        return
    try:
        if sig == signal.SIGKILL:
            process.kill()
        else:
            process.terminate()
    except OSError:
        pass


def _capture_descendant_identities(record: dict[str, Any]) -> None:
    """在任何终止信号前记录子孙身份，父进程退出后仍可核对已脱组的成员。"""
    process = record["process"]
    if process.poll() is not None:
        return
    identities = record.setdefault("descendant_identities", {})
    for pid in _posix_descendants(process.pid):
        stat = _proc_stat(pid)
        if stat is not None and stat[0] != "Z":
            identities[pid] = stat[2]


def _signal_known_descendants(record: dict[str, Any], sig: int) -> None:
    opener = getattr(os, "pidfd_open", None)
    sender = getattr(signal, "pidfd_send_signal", None)
    for pid, starttime in record.get("descendant_identities", {}).items():
        stat = _proc_stat(pid)
        if stat is None or stat[0] == "Z" or stat[2] != starttime:
            continue
        if opener is None or sender is None:
            record["descendants_unproven"] = True
            continue
        fd = None
        try:
            fd = opener(pid)
            pinned = _proc_stat(pid)
            if pinned is not None and pinned[2] == starttime:
                sender(fd, sig)
        except ProcessLookupError:
            pass
        except OSError:
            record["descendants_unproven"] = True
        finally:
            if fd is not None:
                os.close(fd)


def _signal_dependency_tree(record: dict[str, Any], sig: int) -> str:
    """向本次任务证明过的进程组和已观察子孙发信号，不先销毁父树。"""
    if os.name != "posix" or not record.get("group_proven") or record.get("group_unproven"):
        _signal_direct(record, sig)
        return "direct-only"
    _capture_descendant_identities(record)
    _signal_known_descendants(record, sig)
    outcome = _signal_proven_group(record, sig)
    if outcome == "unproven":
        _signal_direct(record, sig)
        return "direct-only"
    _signal_direct(record, sig)
    return "process-group"


def _reap_direct(process: subprocess.Popen[Any], timeout: float) -> bool:
    if process.poll() is not None:
        return True
    if os.name != "posix":
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True
    deadline = time.monotonic() + timeout
    while True:
        try:
            got, status = os.waitpid(process.pid, os.WNOHANG)
        except ChildProcessError:
            if process.poll() is None:
                process.returncode = -1
            return True
        if got == process.pid:
            if os.WIFSIGNALED(status):
                process.returncode = -os.WTERMSIG(status)
            elif os.WIFEXITED(status):
                process.returncode = os.WEXITSTATUS(status)
            else:
                process.returncode = status
            return True
        if time.monotonic() >= deadline:
            return process.poll() is not None
        time.sleep(0.02)


def _groups_are_clear(records: list[dict[str, Any]]) -> tuple[bool, list[int]]:
    """身份都证明了且没有活进程时返回 (True, [])。无法证明时第一个值是 False。"""
    live: list[int] = []
    clear = True
    for record in records:
        for pid, starttime in record.get("descendant_identities", {}).items():
            stat = _proc_stat(pid)
            if stat is not None and stat[0] != "Z" and stat[2] == starttime:
                clear = False
                live.append(pid)
        if record.get("descendants_unproven"):
            clear = False
        if (
            os.name != "posix"
            or not record.get("group_proven")
            or record.get("group_unproven")
            or record.get("group_refused")
        ):
            clear = False
            continue
        status, members = _proven_group_members(record)
        if status != "empty":
            clear = False
            live.extend(members)
    return clear, live


def _wait_groups_clear(records: list[dict[str, Any]], timeout: float) -> tuple[bool, list[int]]:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        clear, live = _groups_are_clear(records)
        if clear or not live or time.monotonic() >= deadline:
            return clear, live
        time.sleep(0.02)


def _cancel_report(
    tracked: int, direct_stopped: bool, remaining: int, safe: bool, mechanism: str,
    claims: bool, proven: bool, limitation: str,
) -> dict[str, Any]:
    return {
        "tracked": tracked,
        "direct_stopped": direct_stopped,
        "remaining_descendants": remaining,
        "safe_to_restore": safe,
        "mechanism": mechanism,
        "claims_full_process_tree": claims,
        "descendants_proven": proven,
        "limitation": limitation,
    }


def _cancel_tracked_dependency_processes() -> dict[str, Any]:
    """取消已跟踪的依赖进程。只有证明进程组里没有活进程时才允许恢复旧目录。"""
    records = list(_TRACKED_DEPENDENCY_PROCESSES)
    grace = max(0.0, float(DEPENDENCY_CANCEL_GRACE_SECONDS))
    if not records:
        return _cancel_report(0, True, 0, True, "none", False, True, "")
    if os.name != "posix":
        # 不在这里实现未经本环境验证的 Windows Job Object。直接子进程结束不能证明子孙已退出。
        for record in records:
            _signal_direct(record, signal.SIGTERM)
        direct_stopped = all(_reap_direct(record["process"], grace) for record in records)
        if not direct_stopped:
            for record in records:
                _signal_direct(record, signal.SIGKILL)
            direct_stopped = all(_reap_direct(record["process"], grace) for record in records)
        limitation = (
            "非 POSIX 平台只能结束安装器直接持有的依赖进程，不宣称其子进程树已终止；"
            f"不能安全恢复旧目录，{MANUAL_RESTORE_REQUIRED}"
        )
        return _cancel_report(
            len(records), direct_stopped, -1, False, "direct-only", False, False, limitation,
        )
    mechanism = "process-group"
    for record in records:
        if _signal_dependency_tree(record, signal.SIGTERM) != "process-group":
            mechanism = "direct-only"
    direct_stopped = all(_reap_direct(record["process"], grace) for record in records)
    clear, live = _groups_are_clear(records)
    if (not direct_stopped) or (not clear):
        for record in records:
            if _signal_dependency_tree(record, signal.SIGKILL) != "process-group":
                mechanism = "direct-only"
        direct_stopped = all(_reap_direct(record["process"], grace) for record in records)
        clear, live = _wait_groups_clear(records, grace)
    group_refused = any(record.get("group_refused") for record in records)
    group_unproven = any(record.get("group_unproven") for record in records)
    enumerated = Path("/proc").is_dir()
    proven = bool(clear and not live and not group_refused and not group_unproven)
    claims = bool(
        mechanism == "process-group" and enumerated and direct_stopped and proven
    )
    safe = bool(direct_stopped and proven)
    if safe:
        for record in records:
            _discard_dependency_process(record)
    if group_unproven:
        limitation = (
            "未能证明依赖进程组仍属于本次安装任务，已拒绝 killpg，避免 PID 复用后误杀其他进程；"
            f"已保留事务现场，{MANUAL_RESTORE_REQUIRED}"
        )
    elif not enumerated:
        limitation = f"当前系统不能枚举依赖进程组，不宣称整个进程树已终止；{MANUAL_RESTORE_REQUIRED}"
    elif group_refused or mechanism == "direct-only" or not clear:
        limitation = (
            "依赖进程组身份未证明或仍有成员存活，已拒绝把未知进程当成已结束；"
            f"{MANUAL_RESTORE_REQUIRED}"
        )
    elif not direct_stopped or live:
        limitation = f"仍有依赖进程未能确认退出，已保留事务现场，{MANUAL_RESTORE_REQUIRED}"
    elif claims:
        limitation = ""
    else:
        limitation = f"未能确认依赖进程树已终止，已保留事务现场，{MANUAL_RESTORE_REQUIRED}"
    return _cancel_report(
        len(records), direct_stopped, -1 if not proven else len(live), safe, mechanism,
        claims, proven, limitation,
    )


def _record_confirmed_clear(record: dict[str, Any]) -> bool:
    if not any(item is record for item in _TRACKED_DEPENDENCY_PROCESSES):
        return True
    clear, live = _groups_are_clear([record])
    return clear and not live


def _run_tracked_command(
    command: list[str], *, cwd: Path | None = None, stdout: Any = None,
) -> subprocess.CompletedProcess[Any]:
    """启动依赖命令并登记进程。POSIX 使用新会话，便于按进程组取消。"""
    popen_kwargs: dict[str, Any] = {"cwd": None if cwd is None else str(cwd), "stdout": stdout}
    group = os.name == "posix"
    if group:
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if creationflags:
            popen_kwargs["creationflags"] = creationflags
    process = subprocess.Popen(command, **popen_kwargs)
    record = _register_dependency_process(process, group=group)
    try:
        if not record.get("group_proven"):
            if os.name == "posix":
                reason = f"依赖进程组身份未能证明，不能确认子孙进程已终止；{MANUAL_RESTORE_REQUIRED}"
            else:
                reason = (
                    "非 POSIX 平台只能结束安装器直接持有的依赖进程，不宣称其子进程树已终止；"
                    f"{MANUAL_RESTORE_REQUIRED}"
                )
            _block_open_transaction_for_unprovable_dependency(reason)
        process.communicate()
    except BaseException:
        _cancel_tracked_dependency_processes()
        raise
    if record.get("group_proven") and not _record_confirmed_clear(record):
        report = _cancel_tracked_dependency_processes()
        if not report.get("safe_to_restore"):
            raise RuntimeError(
                str(report.get("limitation") or f"依赖进程组在直接进程退出后仍无法确认已终止；{MANUAL_RESTORE_REQUIRED}")
            )
    if process.poll() is not None and record.get("group_proven") and _record_confirmed_clear(record):
        _discard_dependency_process(record)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    return subprocess.CompletedProcess(command, process.returncode)


def install_dependencies(runtime: Path, *, with_dev: bool) -> dict[str, Any]:
    venv = runtime / ".venv"
    try:
        _run_tracked_command([sys.executable, "-m", "venv", str(venv)])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("创建虚拟环境失败；Debian/Ubuntu 请先安装 python3-venv，然后重新运行安装器。") from exc
    python = venv_python(venv)
    _run_tracked_command([str(python), "-m", "pip", "install", "--upgrade", "pip"], stdout=sys.stderr)
    extras = "docx,dev" if with_dev else "docx"
    _run_tracked_command(
        [str(python), "-m", "pip", "install", f".[{extras}]"], cwd=runtime, stdout=sys.stderr)
    _run_tracked_command([str(python), "scripts/verify_package.py"], cwd=runtime, stdout=sys.stderr)
    return {"python": str(python), "extras": extras}


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


@contextmanager
def _installation_lock(vendor: Path):
    """OS 文件锁随进程死亡自动释放，避免两个安装器互相恢复尚在运行的事务。"""
    path = vendor / f".{PLUGIN_NAME}.lock"
    if path.is_symlink():
        raise RuntimeError(f"安装锁不能是符号链接：{path}")
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("另一个安装器正在运行，拒绝并发修改") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("另一个安装器正在运行，拒绝并发修改") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            # POSIX close 也会释放 flock，无需维护容易过期的 PID 文件。


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _tx_paths(vendor: Path, skills_home: Path) -> tuple[Path, Path, Path]:
    # 入口备份与入口同盘；不要求 skills 和 vendor 位于同一个挂载点。
    return vendor / TRANSACTION_NAME, vendor / BACKUP_NAME, skills_home / ENTRY_BACKUP_NAME


def _read_transaction(vendor: Path, skills_home: Path) -> dict[str, Any]:
    journal_path, _, entries_backup = _tx_paths(vendor, skills_home)
    if journal_path.is_symlink() or entries_backup.is_symlink():
        raise RuntimeError("事务日志/入口备份目录不能是符号链接；已保留现场")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if (journal.get("schema_id") != "cn-patent-codex-skill-install-transaction/v1"
            or journal.get("phase") not in {"prepared", "committed", "rolled_back"}
            or type(journal.get("runtime_existed")) is not bool
            or set(journal.get("entries_existed", {})) != set(REQUIRED_SKILLS)
            or any(type(value) is not bool for value in journal["entries_existed"].values())):
        raise RuntimeError(f"事务日志损坏或格式不受支持，已保留备份：{journal_path}")
    # 日志不携带可执行的目标绝对路径，恢复目标只由当前 codex_home 推导。
    staging_name = journal.get("staging_name", "")
    if (not isinstance(staging_name, str) or not staging_name.startswith(f".{PLUGIN_NAME}-")
            or Path(staging_name).name != staging_name or "/" in staging_name or "\\" in staging_name):
        raise RuntimeError("非法暂存目录，拒绝恢复并保留现场")
    return journal


def _cleanup_transaction(vendor: Path, skills_home: Path, journal: dict[str, Any]) -> None:
    journal_path, runtime_backup, entries_backup = _tx_paths(vendor, skills_home)
    remove_path(runtime_backup)
    remove_path(entries_backup)
    remove_path(vendor / journal["staging_name"])
    # 日志最后删除：清理失败/被强制终止后，启动时依 phase 继续，不回滚已提交状态。
    journal_path.unlink()


def _mutate_prepared_journal(vendor: Path, skills_home: Path, mutate: Any) -> None:
    journal_path = vendor / TRANSACTION_NAME
    if not _exists(journal_path):
        return
    journal = _read_transaction(vendor, skills_home)
    if journal.get("phase") != "prepared":
        return
    if mutate(journal):
        _atomic_json(journal_path, journal)


def _mark_cancelling(vendor: Path, skills_home: Path, reason: str) -> None:
    def mutate(journal: dict[str, Any]) -> bool:
        current = journal.get(DEPENDENCY_BLOCK_KEY)
        # 非 POSIX 或身份无法证明时写下的硬阻塞，不能被一次“正在取消”覆盖掉。
        if isinstance(current, dict) and current.get("state") == "unconfirmed":
            return False
        journal[DEPENDENCY_BLOCK_KEY] = {
            "state": "cancelling",
            "manual_confirmation_required": True,
            "reason": reason,
        }
        return True

    _mutate_prepared_journal(vendor, skills_home, mutate)


def _mark_unconfirmed(vendor: Path, skills_home: Path, reason: str) -> None:
    def mutate(journal: dict[str, Any]) -> bool:
        journal[DEPENDENCY_BLOCK_KEY] = {
            "state": "unconfirmed",
            "manual_confirmation_required": True,
            "reason": reason,
        }
        return True

    _mutate_prepared_journal(vendor, skills_home, mutate)


def _clear_provisional_dependency_block(vendor: Path, skills_home: Path) -> None:
    def mutate(journal: dict[str, Any]) -> bool:
        current = journal.get(DEPENDENCY_BLOCK_KEY)
        if not isinstance(current, dict) or current.get("state") != "cancelling":
            return False
        journal.pop(DEPENDENCY_BLOCK_KEY, None)
        return True

    _mutate_prepared_journal(vendor, skills_home, mutate)


def _dependency_restore_block_reason(journal: dict[str, Any]) -> str | None:
    if DEPENDENCY_BLOCK_KEY not in journal:
        return None
    block = journal[DEPENDENCY_BLOCK_KEY]
    if not isinstance(block, dict):
        return "dependency_processes 字段损坏"
    state = block.get("state")
    manual = block.get("manual_confirmation_required")
    if state == "operator-confirmed" and manual is False:
        return None
    if state == "cancelling":
        return "依赖进程取消未完成"
    if state == "unconfirmed" and manual is True:
        reason = block.get("reason")
        if isinstance(reason, str) and reason:
            return reason
        return "依赖进程树未确认终止"
    return "dependency_processes 状态无法识别，拒绝自动恢复"


def _block_open_transaction_for_unprovable_dependency(reason: str) -> None:
    context = _SIGNAL_CONTEXT
    if context is None:
        return
    vendor, skills_home = context
    _mark_unconfirmed(vendor, skills_home, reason)


def _finish_cancelled_transaction(vendor: Path, skills_home: Path) -> dict[str, Any]:
    journal_path = vendor / TRANSACTION_NAME
    if _exists(journal_path) and _TRACKED_DEPENDENCY_PROCESSES:
        _mark_cancelling(vendor, skills_home, "依赖进程取消尚未完成")
    report = _cancel_tracked_dependency_processes()
    if not _exists(journal_path):
        return report
    if report.get("safe_to_restore") and report.get("descendants_proven"):
        _clear_provisional_dependency_block(vendor, skills_home)
    elif report.get("tracked"):
        _mark_unconfirmed(
            vendor, skills_home, str(report.get("limitation") or "未能确认依赖进程树已终止"),
        )
    try:
        journal = _read_transaction(vendor, skills_home)
    except RuntimeError as exc:
        blocked = dict(report)
        blocked["safe_to_restore"] = False
        blocked["limitation"] = str(exc)
        return blocked
    if journal.get("phase") == "prepared":
        reason = _dependency_restore_block_reason(journal)
        if reason:
            blocked = dict(report)
            blocked["safe_to_restore"] = False
            if not blocked.get("limitation"):
                blocked["limitation"] = reason
            return blocked
    return report


def _abort_installation(vendor: Path, skills_home: Path, exc: BaseException) -> None:
    """依赖树未确认结束时保留事务现场。调用方在成功恢复后仍抛出原来的安装错误。"""
    journal_path = vendor / TRANSACTION_NAME
    report = _finish_cancelled_transaction(vendor, skills_home)
    if not _exists(journal_path):
        return
    if report.get("safe_to_restore"):
        try:
            _restore_transaction(vendor, skills_home)
        except BaseException as recovery_error:
            raise RuntimeError(
                f"安装失败（{exc!r}），自动恢复未完成；备份/日志已保留，"
                f"下次启动将重试：{journal_path}；恢复错误：{recovery_error}"
            ) from exc
        return
    detail = str(report.get("limitation") or "依赖进程树未能确认已终止")
    raise RuntimeError(
        f"安装失败（{exc!r}），{detail}；已保留事务现场，{MANUAL_RESTORE_REQUIRED}：{journal_path}"
    ) from exc



def _restore_transaction(vendor: Path, skills_home: Path) -> None:
    """八个目标使用同一预写日志；恢复可重复执行，绝不删除唯一旧备份。"""
    journal_path, runtime_backup, entries_backup = _tx_paths(vendor, skills_home)
    journal = _read_transaction(vendor, skills_home)
    if journal["phase"] != "prepared":
        _cleanup_transaction(vendor, skills_home, journal)
        return
    blocked = _dependency_restore_block_reason(journal)
    if blocked is not None:
        raise RuntimeError(
            f"依赖进程树未能确认已终止，已保留事务现场和备份，{MANUAL_RESTORE_REQUIRED}。"
            f"确认没有本安装任务启动的进程仍在写入后，将事务日志 {DEPENDENCY_BLOCK_KEY}.state "
            "改为 operator-confirmed，且 manual_confirmation_required 设为 false，再重新运行安装器。"
            f"原因：{blocked}。日志：{journal_path}"
        )
    targets = [(vendor / PLUGIN_NAME, runtime_backup, journal["runtime_existed"])]
    targets += [(skills_home / name, entries_backup / name, journal["entries_existed"][name])
                for name in REQUIRED_SKILLS]
    for target, backup, existed in targets:
        if _exists(backup):
            remove_path(target)
            backup.replace(target)
        elif not existed:
            remove_path(target)
        elif not _exists(target):
            raise RuntimeError(f"旧目标及其备份均缺失，停止恢复并保留剩余备份：{target}")
        # 原有目标存在且备份不存在：它尚未移动，或上次恢复已归位。不能再删除。
    journal["phase"] = "rolled_back"
    _atomic_json(journal_path, journal)
    _cleanup_transaction(vendor, skills_home, journal)


def recover_pending(vendor: Path, skills_home: Path) -> None:
    """启动时恢复 SIGKILL 等留下的未提交事务；失败保留现场并阻止新安装。"""
    journal_path, runtime_backup, entries_backup = _tx_paths(vendor, skills_home)
    if _exists(journal_path):
        print(f"恢复/收尾上次安装事务：{journal_path}", file=sys.stderr)
        _restore_transaction(vendor, skills_home)
        return
    if _exists(entries_backup):
        raise RuntimeError(f"发现无日志的入口备份，拒绝覆盖：{entries_backup}")
    if _exists(runtime_backup):
        runtime = vendor / PLUGIN_NAME
        if _exists(runtime):
            raise RuntimeError(f"运行时与无日志旧备份同时存在，拒绝猜测或删除：{runtime_backup}")
        # 兼容旧安装器留下的重命名间隙备份，原子归位而不是删掉它。
        runtime_backup.replace(runtime)
        print(f"已恢复旧安装器的运行时备份：{runtime}", file=sys.stderr)


def _sigterm_handler(signum: int, frame: Any) -> None:
    """先取消依赖进程并等待已证明的进程组结束，再恢复旧版本；SIGKILL 由下次启动处理。"""
    signal.signal(signum, signal.SIG_IGN)
    context = _SIGNAL_CONTEXT
    if context is not None:
        vendor, skills_home = context
        try:
            report = _finish_cancelled_transaction(vendor, skills_home)
            journal_path = vendor / TRANSACTION_NAME
            if _exists(journal_path) and report.get("safe_to_restore"):
                _restore_transaction(vendor, skills_home)
            elif _exists(journal_path):
                print(
                    f"依赖进程树未能确认已终止，已保留事务现场，{MANUAL_RESTORE_REQUIRED}",
                    file=sys.stderr,
                )
            limitation = str(report.get("limitation") or "")
            if report.get("tracked") and limitation:
                print(limitation, file=sys.stderr)
        except BaseException as exc:
            print(f"取消依赖进程或自动恢复失败，保留事务现场：{exc}", file=sys.stderr)
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def install_skill_links(runtime: Path, skills_home: Path, *, force: bool) -> list[dict[str, str]]:
    skills_home.mkdir(parents=True, exist_ok=True)
    installed: list[dict[str, str]] = []
    for name in REQUIRED_SKILLS:
        source = runtime / "skills" / name
        if not (source / "SKILL.md").is_file():
            raise RuntimeError(f"运行时缺少 Skill：{name}")
        target = skills_home / name
        if target.exists() or target.is_symlink():
            if not force:
                raise RuntimeError(f"Codex Skill 已存在，使用 --force 才能替换：{target}")
            remove_path(target)
        mode = "symlink"
        try:
            target.symlink_to(source, target_is_directory=True)
        except OSError:
            shutil.copytree(source, target)
            mode = "copy"
        installed.append({"name": name, "path": str(target), "mode": mode})
    return installed


def write_manifest(runtime: Path, codex_home: Path, installed: list[dict[str, str]], deps: dict[str, Any] | None) -> Path:
    manifest = {
        "schema_id": "cn-patent-codex-skill-install/v1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(runtime), "codex_home": str(codex_home),
        "entry_skill": "cn-patent-workflow", "skills": installed,
        "dependencies": deps, "invocation": "$cn-patent-workflow",
    }
    path = runtime / "codex-install.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1], help="仓库根目录")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home(), help="Codex 用户目录")
    parser.add_argument("--skip-deps", action="store_true", help="不创建运行时虚拟环境")
    parser.add_argument("--with-dev", action="store_true", help="同时安装 pytest 等开发依赖")
    parser.add_argument("--force", action="store_true", help="替换已有同名 Skill 和运行时")
    return parser.parse_args()


def _begin_transaction(vendor: Path, runtime: Path, skills_home: Path, staging: Path) -> dict[str, Any]:
    journal_path, runtime_backup, entries_backup = _tx_paths(vendor, skills_home)
    if any(_exists(path) for path in (journal_path, runtime_backup, entries_backup)):
        raise RuntimeError("发现已有事务/备份，拒绝覆盖")
    journal = {
        "schema_id": "cn-patent-codex-skill-install-transaction/v1",
        "phase": "prepared", "staging_name": staging.parent.name,
        "runtime_existed": _exists(runtime),
        "entries_existed": {name: _exists(skills_home / name) for name in REQUIRED_SKILLS},
    }
    # 所有原始存在状态先落盘，再执行任何 rename。不要用 rename 后更新的列表
    # 推断已移动目标，否则 SIGKILL 恰好落在两者之间仍会遗漏旧入口。
    _atomic_json(journal_path, journal)
    entries_backup.mkdir()
    for name in REQUIRED_SKILLS:
        if journal["entries_existed"][name]:
            (skills_home / name).replace(entries_backup / name)
    if journal["runtime_existed"]:
        runtime.replace(runtime_backup)
    return journal


def _install(args: argparse.Namespace, source: Path, codex_home: Path) -> dict[str, Any]:
    vendor = codex_home / "vendor"
    runtime = vendor / PLUGIN_NAME
    skills_home = codex_home / "skills"
    skills_home.mkdir(parents=True, exist_ok=True)
    # 即使本轮源目录已失效，也先恢复上次安装，不让源检查阻塞旧版本归位。
    recover_pending(vendor, skills_home)
    if not (source / ".codex-plugin" / "plugin.json").is_file():
        raise RuntimeError(f"不是有效项目根目录：{source}")
    for name in REQUIRED_SKILLS:
        if not (source / "skills" / name / "SKILL.md").is_file():
            raise RuntimeError(f"源仓库缺少 Skill：{name}")
    if not args.force:
        for target in [runtime, *(skills_home / name for name in REQUIRED_SKILLS)]:
            if _exists(target):
                raise RuntimeError(f"安装目标已存在，使用 --force 更新：{target}")

    with tempfile.TemporaryDirectory(prefix=f".{PLUGIN_NAME}-", dir=vendor) as temporary:
        staging = Path(temporary) / PLUGIN_NAME
        copy_runtime(source, staging)
        problems = _verify_staged_tree(staging)
        if problems:
            raise RuntimeError(
                "安装前完整性检查失败，旧安装未替换：\n"
                + "\n".join(f"- {item}" for item in problems)
            )
        journal_path = vendor / TRANSACTION_NAME
        try:
            journal = _begin_transaction(vendor, runtime, skills_home, staging)
            staging.replace(runtime)
            deps = None if args.skip_deps else install_dependencies(runtime, with_dev=args.with_dev)
            installed = install_skill_links(runtime, skills_home, force=args.force)
            manifest_path = write_manifest(runtime, codex_home, installed, deps)
            journal["phase"] = "committed"
            _atomic_json(journal_path, journal)
        except BaseException as exc:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            _abort_installation(vendor, skills_home, exc)
            raise
        _cleanup_transaction(vendor, skills_home, journal)
    return {"status": "PASS", "runtime_root": str(runtime), "entry_skill": "cn-patent-workflow",
            "invocation": "$cn-patent-workflow", "manifest": str(manifest_path),
            "skills": installed, "restart_required": True}


def main() -> int:
    global _SIGNAL_CONTEXT
    args = parse_args()
    source = args.source.expanduser().resolve()
    codex_home = args.codex_home.expanduser().resolve()
    vendor = codex_home / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    with _installation_lock(vendor):
        previous_sigterm = signal.signal(signal.SIGTERM, _sigterm_handler)
        _SIGNAL_CONTEXT = (vendor, codex_home / "skills")
        try:
            result = _install(args, source, codex_home)
        finally:
            _SIGNAL_CONTEXT = None
            signal.signal(signal.SIGTERM, previous_sigterm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
