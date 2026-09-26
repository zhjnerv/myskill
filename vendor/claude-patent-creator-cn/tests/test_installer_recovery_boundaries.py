"""独立交叉验收：安装事务恢复边界与公开源分发白名单。

本文件只消费现有安装器/验证器接口，不改变生产实现；全部文件写入 pytest 临时目录。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_codex_skill.py"
VERIFY_PACKAGE = ROOT / "scripts/verify_package.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(tmp_path: Path):
    source = tmp_path / "source"
    home = tmp_path / "codex-home"
    module = load_module(INSTALLER, f"installer_{id(tmp_path)}")
    (source / ".codex-plugin").mkdir(parents=True)
    (source / ".codex-plugin/plugin.json").write_bytes((ROOT / ".codex-plugin/plugin.json").read_bytes())
    (source / "pyproject.toml").write_bytes((ROOT / "pyproject.toml").read_bytes())
    for name in module.REQUIRED_SKILLS:
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n# synthetic\n", encoding="utf-8")
        (skill / "generation.txt").write_text("NEW", encoding="utf-8")
    return source, home, module


def run_installer(source: Path, home: Path, *extra: str):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, str(INSTALLER), "--source", str(source), "--codex-home", str(home), "--skip-deps", *extra],
        text=True,
        capture_output=True,
        check=False,
    )


def state(path: Path):
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if path.is_dir():
        return {
            "kind": "copy",
            "files": {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()},
        }
    return {"kind": "missing"}


def test_real_public_source_tree_is_accepted_without_overbroad_rejection():
    installer = load_module(INSTALLER, "installer_public_tree_audit")
    files, errors = installer.collect_source_files(ROOT.resolve(), distribution_only=False)
    assert errors == [], errors
    assert files
    assert any(path.name == "AGENTS.md" for path in files)
    assert any(path.name == "LICENSE" for path in files)
    assert any(path.suffix == ".toml" for path in files)
    assert any(path.suffix == ".json" for path in files)

    verifier = load_module(VERIFY_PACKAGE, "verify_package_public_tree_audit")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert verifier.main() == 0
    report = json.loads(output.getvalue())
    assert report["status"] == "PASS"
    assert report["errors"] == []


def test_rollback_can_resume_after_restore_itself_is_interrupted(tmp_path: Path):
    source, home, module = fixture(tmp_path)
    first = run_installer(source, home)
    assert first.returncode == 0, first.stderr

    vendor = home / "vendor"
    runtime = vendor / module.PLUGIN_NAME
    skills_home = home / "skills"
    staging_parent = vendor / f".{module.PLUGIN_NAME}-recovery-probe"
    staging_parent.mkdir()
    staging = staging_parent / module.PLUGIN_NAME
    staging.mkdir()

    # 预写事务会把旧 runtime 和入口先移入备份；然后模拟新版本已经放入目标。
    journal = module._begin_transaction(vendor, runtime, skills_home, staging)
    runtime.mkdir()
    for name in module.REQUIRED_SKILLS:
        target = skills_home / name
        target.mkdir()
        (target / "generation.txt").write_text("NEW-INCOMPLETE", encoding="utf-8")

    runtime_backup = vendor / module.BACKUP_NAME
    original_replace = module.Path.replace
    interrupted = {"value": False}

    def fail_once(path, target):
        if path == runtime_backup and target == runtime and not interrupted["value"]:
            interrupted["value"] = True
            raise OSError("synthetic interruption during restore")
        return original_replace(path, target)

    with mock.patch.object(module.Path, "replace", fail_once):
        with pytest.raises(OSError, match="synthetic interruption"):
            module._restore_transaction(vendor, skills_home)

    # 失败点发生在 remove_path(target) 之后、backup.replace(target) 之前；
    # 日志和唯一备份都必须仍在，第二次恢复应从该中间态继续。
    journal_path = vendor / module.TRANSACTION_NAME
    assert journal_path.is_file()
    assert runtime_backup.is_dir()
    assert not runtime.exists()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["phase"] == "prepared"

    module._restore_transaction(vendor, skills_home)
    assert state(runtime)["kind"] == "copy"
    assert all((skills_home / name / "generation.txt").read_text() == "NEW" for name in module.REQUIRED_SKILLS)
    assert not journal_path.exists()
    assert not runtime_backup.exists()
    assert not (skills_home / module.ENTRY_BACKUP_NAME).exists()

    # 完成态再次启动恢复是幂等 no-op，而不是误报缺少事务。
    module.recover_pending(vendor, skills_home)
    assert runtime.is_dir()
    assert not journal_path.exists()


def test_rollback_restores_old_runtime_symlink_and_mixed_entry_shapes(tmp_path: Path):
    source, home, module = fixture(tmp_path)
    vendor = home / "vendor"
    skills_home = home / "skills"
    runtime_target = tmp_path / "old-runtime-target"
    runtime_target.mkdir(parents=True)
    for name in module.REQUIRED_SKILLS:
        skill = runtime_target / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"OLD {name}", encoding="utf-8")
        (skill / "generation.txt").write_text("OLD", encoding="utf-8")
    vendor.mkdir(parents=True)
    skills_home.mkdir(parents=True)
    runtime = vendor / module.PLUGIN_NAME
    runtime.symlink_to(runtime_target, target_is_directory=True)

    original_entries = {}
    for index, name in enumerate(module.REQUIRED_SKILLS):
        target = skills_home / name
        if index % 2 == 0:
            target.symlink_to(runtime_target / "skills" / name, target_is_directory=True)
        else:
            shutil.copytree(runtime_target / "skills" / name, target)
        original_entries[name] = state(target)
    original_runtime = state(runtime)

    old_write_manifest = module.write_manifest
    with mock.patch.object(module, "write_manifest", side_effect=OSError("synthetic ENOSPC")):
        with pytest.raises(OSError, match="synthetic ENOSPC"):
            args = module.argparse.Namespace(source=source, codex_home=home, skip_deps=True, with_dev=False, force=True)
            module._install(args, source.resolve(), home.resolve())
    assert state(runtime) == original_runtime
    assert {name: state(skills_home / name) for name in module.REQUIRED_SKILLS} == original_entries
    assert not (vendor / module.TRANSACTION_NAME).exists()
    assert not (vendor / module.BACKUP_NAME).exists()
    assert not (skills_home / module.ENTRY_BACKUP_NAME).exists()
    assert old_write_manifest is not None


def test_source_policy_accepts_existing_public_extensions_but_rejects_artifacts(tmp_path: Path):
    installer = load_module(INSTALLER, "installer_policy_boundary_audit")
    root = tmp_path / "source"
    for name in ("AGENTS.md", "LICENSE", ".gitignore", ".gitattributes"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("public", encoding="utf-8")
    for rel in ("scripts/tool.py", "references/rule.md", "assets/schema.json", "pyproject.toml", "references/notes.txt"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public", encoding="utf-8")
    files, errors = installer.collect_source_files(root, distribution_only=False)
    assert errors == [], errors
    assert {p.relative_to(root).as_posix() for p in files} == {
        "AGENTS.md", "LICENSE", ".gitignore", ".gitattributes", "scripts/tool.py",
        "references/rule.md", "assets/schema.json", "pyproject.toml", "references/notes.txt",
    }

    (root / "assets" / "rendered.png").write_bytes(b"not a source")
    (root / "skills" / ".local-case-archive").mkdir(parents=True)
    (root / "skills" / ".local-case-archive" / "client.pdf").write_bytes(b"private")
    _, errors = installer.collect_source_files(root, distribution_only=False)
    assert any("未获准分发" in item for item in errors)
    assert any("本地归档/临时目录" in item for item in errors)


def test_committed_cleanup_can_resume_without_rolling_back_new_runtime(tmp_path: Path):
    source, home, module = fixture(tmp_path)
    first = run_installer(source, home)
    assert first.returncode == 0, first.stderr

    vendor = home / "vendor"
    runtime = vendor / module.PLUGIN_NAME
    skills_home = home / "skills"
    staging_parent = vendor / f".{module.PLUGIN_NAME}-committed-probe"
    staging_parent.mkdir()
    staging = staging_parent / module.PLUGIN_NAME
    module.copy_runtime(source, staging)
    journal = module._begin_transaction(vendor, runtime, skills_home, staging)

    # 模拟新 runtime/入口已完成、仅提交后的清理尚未完成。
    staging.rename(runtime)
    for name in module.REQUIRED_SKILLS:
        target = skills_home / name
        target.symlink_to(runtime / "skills" / name, target_is_directory=True)
    journal["phase"] = "committed"
    module._atomic_json(vendor / module.TRANSACTION_NAME, journal)

    old_remove = module.remove_path
    interrupted = {"value": False}
    runtime_backup = vendor / module.BACKUP_NAME

    def fail_once(path):
        if path == runtime_backup and not interrupted["value"]:
            interrupted["value"] = True
            raise OSError("synthetic interruption during committed cleanup")
        return old_remove(path)

    with mock.patch.object(module, "remove_path", fail_once):
        with pytest.raises(OSError, match="synthetic interruption"):
            module.recover_pending(vendor, skills_home)

    assert (vendor / module.TRANSACTION_NAME).is_file()
    assert runtime.is_dir()
    assert runtime_backup.is_dir()

    # phase=committed 必须继续清理，而不是把已提交的新 runtime 回滚成旧版本。
    module.recover_pending(vendor, skills_home)
    assert runtime.is_dir()
    assert all((skills_home / name / "SKILL.md").is_file() for name in module.REQUIRED_SKILLS)
    assert not (vendor / module.TRANSACTION_NAME).exists()
    assert not runtime_backup.exists()
    assert not (skills_home / module.ENTRY_BACKUP_NAME).exists()
