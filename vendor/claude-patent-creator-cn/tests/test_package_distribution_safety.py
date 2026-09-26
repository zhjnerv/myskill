"""F09/F10/F11 安装事务与分发边界的合成回归。"""
from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import time
import pytest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_codex_skill.py"


def installer_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_installer", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(tmp_path: Path) -> tuple[Path, Path, object]:
    source = tmp_path / "source"
    home = tmp_path / "codex-home"
    module = installer_module()
    (source / ".codex-plugin").mkdir(parents=True)
    (source / ".codex-plugin/plugin.json").write_bytes((ROOT / ".codex-plugin/plugin.json").read_bytes())
    (source / "pyproject.toml").write_bytes((ROOT / "pyproject.toml").read_bytes())
    for name in module.REQUIRED_SKILLS:
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n# synthetic\n", encoding="utf-8")
        (skill / "generation.txt").write_text("NEW", encoding="utf-8")
    return source, home, module


def run_installer(source: Path, home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(INSTALLER), "--source", str(source),
                           "--codex-home", str(home), "--skip-deps", *extra],
                          text=True, capture_output=True, check=False)


def test_distribution_rejects_nested_local_archive_and_unreviewed_pdf(tmp_path):
    source, _, module = fixture(tmp_path)
    (source / "skills/cn-patent-workflow/.local-case-archive").mkdir()
    (source / "skills/cn-patent-workflow/.local-case-archive/client.pdf").write_bytes(b"synthetic")
    (source / "skills/cn-patent-workflow/synthetic-output.pdf").write_bytes(b"synthetic")
    _, errors = module.collect_source_files(source, distribution_only=True)
    assert any("本地归档/临时目录" in error for error in errors)
    assert any("未获准分发的文件类型" in error for error in errors)
    result = run_installer(source, tmp_path / "home")
    assert result.returncode != 0
    assert not (tmp_path / "home" / "vendor" / module.PLUGIN_NAME).exists()
    assert not (tmp_path / "home" / "vendor" / module.TRANSACTION_NAME).exists()

    # 验证器也消费同一策略；合成法源齐全时仍必须拒绝这两个分发边界违规。
    legal = source / "references/cn-legal-sources"
    legal.mkdir(parents=True)
    for rel in ("专利法(2020-10-17).md", "专利法实施细则(2023-12-21).md", "审查指南2026MD/guide-full.md"):
        target = legal / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic legal source", encoding="utf-8")
    (legal / "source-index.json").write_text("{}", encoding="utf-8")
    import contextlib
    import io
    verifier_spec = __import__("importlib.util").util.spec_from_file_location("test_verifier", ROOT / "scripts/verify_package.py")
    verifier = __import__("importlib.util").util.module_from_spec(verifier_spec)
    verifier_spec.loader.exec_module(verifier)
    verifier.ROOT = source
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert verifier.main() == 2
    report = json.loads(output.getvalue())
    assert report["status"] == "FAIL"
    assert any("未获准分发" in error or "本地归档" in error for error in report["errors"])


@pytest.mark.parametrize("existing_mode", ["symlink", "copy"])
def test_manifest_failure_rolls_back_runtime_and_copy_fallback_entries(tmp_path, existing_mode):
    source, home, module = fixture(tmp_path)
    result = run_installer(source, home)
    assert result.returncode == 0, result.stderr
    runtime = home / "vendor" / module.PLUGIN_NAME
    if existing_mode == "copy":
        for name in module.REQUIRED_SKILLS:
            target = home / "skills" / name
            target.unlink()
            shutil.copytree(runtime / "skills" / name, target)
    old_runtime = {p.relative_to(runtime): p.read_bytes() for p in runtime.rglob("*") if p.is_file()}
    old_entry_state = {}
    for name in module.REQUIRED_SKILLS:
        entry = home / "skills" / name
        if entry.is_symlink():
            old_entry_state[name] = {"kind": "symlink", "target": os.readlink(entry)}
        else:
            old_entry_state[name] = {
                "kind": "copy",
                "files": {p.relative_to(entry).as_posix(): p.read_bytes()
                          for p in entry.rglob("*") if p.is_file()},
            }
    (source / "skills/cn-patent-workflow/generation.txt").write_text("NEWER", encoding="utf-8")
    argv = [str(INSTALLER), "--source", str(source), "--codex-home", str(home), "--skip-deps", "--force"]
    with mock.patch.object(sys, "argv", argv), \
         mock.patch.object(module, "write_manifest", side_effect=OSError("synthetic ENOSPC")), \
         mock.patch.object(module.Path, "symlink_to", side_effect=OSError("synthetic unsupported")):
        try:
            module.main()
        except OSError as exc:
            assert "ENOSPC" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("manifest failure was swallowed")
    assert not (home / "vendor" / module.TRANSACTION_NAME).exists()
    assert all((runtime / rel).read_bytes() == data for rel, data in old_runtime.items())
    assert all((home / "skills" / name / "generation.txt").read_text() == "NEW" for name in module.REQUIRED_SKILLS)
    restored_entry_state = {}
    for name in module.REQUIRED_SKILLS:
        entry = home / "skills" / name
        if entry.is_symlink():
            restored_entry_state[name] = {"kind": "symlink", "target": os.readlink(entry)}
        else:
            restored_entry_state[name] = {
                "kind": "copy",
                "files": {p.relative_to(entry).as_posix(): p.read_bytes()
                          for p in entry.rglob("*") if p.is_file()},
            }
    assert restored_entry_state == old_entry_state


def test_real_sigterm_at_rename_gap_restores_runtime_and_entries(tmp_path):
    source, home, module = fixture(tmp_path)
    first = run_installer(source, home)
    assert first.returncode == 0, first.stderr
    runtime = home / "vendor" / module.PLUGIN_NAME
    marker = tmp_path / "ready.json"
    helper = tmp_path / "signal_worker.py"
    helper.write_text(
        "import importlib.util, json, os, signal, sys, time\n"
        "from pathlib import Path\n"
        "script, source, home, ready = map(Path, sys.argv[1:])\n"
        "spec = importlib.util.spec_from_file_location('worker_installer', script)\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "original = Path.replace\n"
        "def pause(path, target):\n"
        "    if Path(target) == Path(home) / 'vendor' / m.PLUGIN_NAME and path.name == m.PLUGIN_NAME and path.parent != Path(target).parent:\n"
        "        ready.write_text(json.dumps({'runtime': Path(target).exists(), 'backup': (Path(target).parent / m.BACKUP_NAME).exists()}))\n"
        "        signal.pause()\n"
        "    return original(path, target)\n"
        "Path.replace = pause\n"
        "sys.argv = [str(script), '--source', str(source), '--codex-home', str(home), '--skip-deps', '--force']\n"
        "m.main()\n", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.Popen([sys.executable, str(helper), str(INSTALLER), str(source), str(home), str(marker)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        deadline = time.monotonic() + 8
        while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), proc.stderr.read() if proc.poll() is not None else "未到达 SIGTERM 注入点"
        proc.terminate()
        proc.communicate(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert proc.returncode == -signal.SIGTERM
    assert runtime.is_dir()
    assert all((home / "skills" / name / "SKILL.md").is_file() for name in module.REQUIRED_SKILLS)
    assert not (home / "vendor" / module.BACKUP_NAME).exists()
    assert not (home / "vendor" / module.TRANSACTION_NAME).exists()


def test_sigkill_leaves_recoverable_journal_and_next_startup_recovers(tmp_path):
    source, home, module = fixture(tmp_path)
    first = run_installer(source, home)
    assert first.returncode == 0, first.stderr
    marker = tmp_path / "ready.json"
    helper = tmp_path / "sigkill_worker.py"
    helper.write_text(
        "import importlib.util, json, signal, sys\n"
        "from pathlib import Path\n"
        "script, source, home, ready = map(Path, sys.argv[1:])\n"
        "spec = importlib.util.spec_from_file_location('worker_installer', script)\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "original = Path.replace\n"
        "def pause(path, target):\n"
        "    if Path(target) == Path(home) / 'vendor' / m.PLUGIN_NAME and path.name == m.PLUGIN_NAME and path.parent != Path(target).parent:\n"
        "        ready.write_text('ready')\n"
        "        signal.pause()\n"
        "    return original(path, target)\n"
        "Path.replace = pause\n"
        "sys.argv = [str(script), '--source', str(source), '--codex-home', str(home), '--skip-deps', '--force']\n"
        "m.main()\n", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(helper), str(INSTALLER), str(source), str(home), str(marker)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        deadline = time.monotonic() + 8
        while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        proc.kill()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=5)
    vendor = home / "vendor"
    assert (vendor / module.TRANSACTION_NAME).is_file()
    assert (vendor / module.BACKUP_NAME).is_dir()
    recovered = run_installer(source, home, "--force")
    assert recovered.returncode == 0, recovered.stderr
    assert (vendor / module.PLUGIN_NAME).is_dir()
    assert not (vendor / module.TRANSACTION_NAME).exists()
    assert not (vendor / module.BACKUP_NAME).exists()
    assert all((home / "skills" / name / "SKILL.md").is_file() for name in module.REQUIRED_SKILLS)
