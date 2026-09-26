#!/usr/bin/env python3
"""把本仓库以 Codex 文件系统 Skill 集合一键安装到用户目录。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLUGIN_NAME = "claude-patent-creator-cn"

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


def install_dependencies(runtime: Path, *, with_dev: bool) -> dict[str, Any]:
    venv = runtime / ".venv"
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("创建虚拟环境失败；Debian/Ubuntu 请先安装 python3-venv，然后重新运行安装器。") from exc
    python = venv_python(venv)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True, stdout=sys.stderr)
    extras = "docx,dev" if with_dev else "docx"
    subprocess.run([str(python), "-m", "pip", "install", f".[{extras}]"], cwd=runtime, check=True, stdout=sys.stderr)
    subprocess.run([str(python), "scripts/verify_package.py"], cwd=runtime, check=True, stdout=sys.stderr)
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


def _restore_transaction(vendor: Path, skills_home: Path) -> None:
    """八个目标使用同一预写日志；恢复可重复执行，绝不删除唯一旧备份。"""
    journal_path, runtime_backup, entries_backup = _tx_paths(vendor, skills_home)
    journal = _read_transaction(vendor, skills_home)
    if journal["phase"] != "prepared":
        _cleanup_transaction(vendor, skills_home, journal)
        return
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
    """先恢复旧版本，再交回操作系统信号语义；SIGKILL 由下次启动恢复。"""
    context = _SIGNAL_CONTEXT
    if context is not None:
        vendor, skills_home = context
        try:
            _restore_transaction(vendor, skills_home)
        except BaseException as exc:
            print(f"SIGTERM 前自动恢复失败，保留事务现场：{exc}", file=sys.stderr)
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
            if _exists(journal_path):
                try:
                    _restore_transaction(vendor, skills_home)
                except BaseException as recovery_error:
                    raise RuntimeError(
                        f"安装失败（{exc!r}），自动恢复未完成；备份/日志已保留，"
                        f"下次启动将重试：{journal_path}；恢复错误：{recovery_error}"
                    ) from exc
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
