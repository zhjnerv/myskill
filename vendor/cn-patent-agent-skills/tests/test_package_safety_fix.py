"""F13/F14：依赖进程必须在回滚前停止，完整性检查不能被 --skip-deps 跳过。"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_codex_skill.py"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_complete_source(source: Path, module, generation: str = "NEW") -> None:
    for relative in module.required_package_files(ROOT):
        origin = ROOT / relative
        if not origin.is_file():
            raise AssertionError(f"合法 fixture 缺少源文件：{relative}")
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        origin_bytes = origin.read_bytes()
        target.write_bytes(origin_bytes)
    for name in module.REQUIRED_SKILLS:
        (source / "skills" / name / "generation.txt").write_text(generation, encoding="utf-8")


def snapshot(path: Path) -> dict[str, bytes]:
    data: dict[str, bytes] = {}
    for item in path.rglob("*"):
        if item.is_symlink():
            raise AssertionError(f"意外符号链接：{item}")
        if item.is_file():
            data[item.relative_to(path).as_posix()] = item.read_bytes()
    return data


def run_installer(source: Path, home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--source", str(source), "--codex-home", str(home), *extra],
        text=True, capture_output=True, check=False,
    )


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "pidfd_open"), reason="需要 Linux 进程身份支持")
def test_escaped_child_is_captured_before_parent_kill(tmp_path):
    """子进程脱组且忽略 TERM，也必须先记录身份再杀父进程，并等待它退出。"""
    module = load_module("installer_escaped_before_kill")
    ready = tmp_path / "escaped.pid"
    child_code = (
        "import os,signal,time; from pathlib import Path; "
        "os.setsid(); signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(120)"
    )
    parent_code = (
        "import subprocess,sys,signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]).wait()"
    )
    parent = subprocess.Popen([sys.executable, "-c", parent_code], start_new_session=True)
    child_fd = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "合成子进程未启动"
        child_pid = int(ready.read_text())
        child_fd = os.pidfd_open(child_pid)
        assert os.getpgid(child_pid) != os.getpgid(parent.pid)
        record = {"process": parent}
        module._capture_group_proof(record)
        assert module._signal_dependency_tree(record, signal.SIGKILL) == "process-group"
        assert child_pid in record["descendant_identities"]
        assert module._reap_direct(parent, 3)
        clear, remaining = module._wait_groups_clear([record], 3)
        assert clear and not remaining
        state = module._proc_stat(child_pid)
        assert state is None or state[0] == "Z"
    finally:
        if child_fd is not None:
            try:
                signal.pidfd_send_signal(child_fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(child_fd)
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="只验证 POSIX 身份跟踪")
def test_clear_group_does_not_hide_a_live_escaped_descendant(monkeypatch):
    module = load_module("installer_wait_escaped_identity")
    record = {"group_proven": True, "descendant_identities": {45678: 99}}
    monkeypatch.setattr(module, "_proven_group_members", lambda _: ("empty", []))
    monkeypatch.setattr(module, "_proc_stat", lambda _: ("S", 45678, 99))
    assert module._groups_are_clear([record]) == (False, [45678])
    # PID 已复用不是原任务还活着，更不能向新进程发送旧任务的信号。
    monkeypatch.setattr(module, "_proc_stat", lambda _: ("S", 45678, 100))
    assert module._groups_are_clear([record]) == (True, [])
    monkeypatch.setattr(module.os, "pidfd_open", lambda _: pytest.fail("不得钉住复用后的PID"))
    module._signal_known_descendants(record, signal.SIGKILL)


def test_real_package_integrity_passes():
    module = load_module("installer_real_integrity")
    assert module.check_package_integrity(ROOT) == []


def test_skill_md_only_package_is_rejected_without_touching_runtime(tmp_path: Path):
    module = load_module("installer_minimal_reject")
    source = tmp_path / "minimal"
    (source / ".codex-plugin").mkdir(parents=True)
    (source / ".codex-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    for name in module.REQUIRED_SKILLS:
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    errors = module.check_package_integrity(source)
    assert any("插件清单" in item for item in errors)
    assert any("run_python.py" in item for item in errors)
    assert any("模版" in item for item in errors)

    home = tmp_path / "home"
    skipped = run_installer(source, home, "--skip-deps")
    assert skipped.returncode != 0
    assert "完整性检查失败" in skipped.stderr
    assert not (home / "vendor" / module.PLUGIN_NAME).exists()
    assert not (home / "vendor" / module.TRANSACTION_NAME).exists()

    calls = {"n": 0}

    def forbidden(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("完整性失败后不应安装依赖")

    module.install_dependencies = forbidden
    args = module.argparse.Namespace(
        source=source, codex_home=home, skip_deps=False, with_dev=False, force=True,
    )
    with pytest.raises(RuntimeError, match="完整性检查失败"):
        module._install(args, source.resolve(), home.resolve())
    assert calls["n"] == 0
    assert not (home / "vendor" / module.PLUGIN_NAME).exists()


def test_missing_template_fails_verifier_and_keeps_old_install(tmp_path: Path):
    module = load_module("installer_missing_template")
    source = tmp_path / "source"
    home = tmp_path / "home"
    write_complete_source(source, module)
    installed = run_installer(source, home, "--skip-deps")
    assert installed.returncode == 0, installed.stderr
    runtime = home / "vendor" / module.PLUGIN_NAME
    before = snapshot(runtime)

    public = tmp_path / "public"
    write_complete_source(public, module)
    checked = subprocess.run(
        [sys.executable, str(public / "scripts" / "verify_package.py")],
        text=True, capture_output=True, check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    (public / "模版.docx").unlink()
    (source / "模版.docx").unlink()
    rejected = subprocess.run(
        [sys.executable, str(public / "scripts" / "verify_package.py")],
        text=True, capture_output=True, check=False,
    )
    assert rejected.returncode == 2
    report = json.loads(rejected.stdout)
    assert report["status"] == "FAIL"
    assert any("模版" in item for item in report["errors"])

    calls = {"n": 0}

    def forbidden(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("替换旧 runtime 前就应拒绝")

    module.install_dependencies = forbidden
    for skip in (True, False):
        args = module.argparse.Namespace(
            source=source, codex_home=home, skip_deps=skip, with_dev=False, force=True,
        )
        with pytest.raises(RuntimeError, match="完整性检查失败"):
            module._install(args, source.resolve(), home.resolve())
    assert calls["n"] == 0
    assert snapshot(runtime) == before
    assert not (home / "vendor" / module.TRANSACTION_NAME).exists()
    assert not (home / "vendor" / module.BACKUP_NAME).exists()


def test_failed_dependency_command_restores_old_bytes(tmp_path: Path):
    module = load_module("installer_failed_dependency_names")
    source = tmp_path / "source"
    home = tmp_path / "home"
    write_complete_source(source, module)
    first = run_installer(source, home, "--skip-deps")
    assert first.returncode == 0, first.stderr
    runtime = home / "vendor" / module.PLUGIN_NAME
    marker = runtime / "old-generation.txt"
    marker.write_text("OLD", encoding="utf-8")
    before = snapshot(runtime)
    worker = tmp_path / "fail_worker.py"
    worker.write_text(
        "import importlib.util, sys\n"
        "script, source, home, marker = sys.argv[1:]\n"
        "spec = importlib.util.spec_from_file_location('fail_install', script)\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "real = m._run_tracked_command\n"
        "def wrapped(command, **kwargs):\n"
        "    return real([sys.executable, '-c', 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\"DIRTY\", encoding=\"utf-8\"); raise SystemExit(3)', marker], **kwargs)\n"
        "m._run_tracked_command = wrapped\n"
        "sys.argv = [script, '--source', source, '--codex-home', home, '--force']\n"
        "m.main()\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(worker), str(INSTALLER), str(source), str(home), str(marker)],
        text=True, capture_output=True, check=False,
    )
    assert completed.returncode != 0, completed.stdout
    assert marker.read_text(encoding="utf-8") == "OLD"
    assert snapshot(runtime) == before
    assert not (home / "vendor" / module.TRANSACTION_NAME).exists()
    assert not (home / "vendor" / module.BACKUP_NAME).exists()


def test_sigterm_cancels_dependency_child_before_restore(tmp_path: Path):
    module = load_module("installer_sigterm_names")
    source = tmp_path / "source"
    home = tmp_path / "home"
    write_complete_source(source, module)
    first = run_installer(source, home, "--skip-deps")
    assert first.returncode == 0, first.stderr
    runtime = home / "vendor" / module.PLUGIN_NAME
    marker = runtime / "old-generation.txt"
    marker.write_text("OLD", encoding="utf-8")
    before = snapshot(runtime)
    fifo = tmp_path / "release-child"
    os.mkfifo(fifo)
    child = (
        "import os, signal, sys\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print(f'DEPENDENCY_CHILD_READY {os.getpid()} {os.getpgrp()}', flush=True)\n"
        "Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "Path(sys.argv[2]).write_text('LATE_NEW_PROCESS_WRITE', encoding='utf-8')\n"
        "print('DEPENDENCY_CHILD_DONE', flush=True)\n"
    )
    worker = tmp_path / "signal_dependency_worker.py"
    worker.write_text(
        "import importlib.util, signal, sys\n"
        "signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})\n"
        "script, source, home, fifo, marker = sys.argv[1:]\n"
        "spec = importlib.util.spec_from_file_location('signal_install', script)\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "m.DEPENDENCY_CANCEL_GRACE_SECONDS = 0.2\n"
        "real = m._run_tracked_command\n"
        f"child = {child!r}\n"
        "def wrapped(command, **kwargs):\n"
        "    return real([sys.executable, '-c', child, fifo, marker], **kwargs)\n"
        "m._run_tracked_command = wrapped\n"
        "sys.argv = [script, '--source', source, '--codex-home', home, '--force']\n"
        "m.main()\n",
        encoding="utf-8",
    )
    stderr_path = tmp_path / "stderr.txt"
    with stderr_path.open("w", encoding="utf-8") as stderr_handle:
        proc = subprocess.Popen(
            [sys.executable, str(worker), str(INSTALLER), str(source), str(home), str(fifo), str(marker)],
            stdout=subprocess.PIPE, stderr=stderr_handle, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            assert proc.stdout is not None
            line = ""
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and proc.poll() is None:
                import select
                ready, _, _ = select.select([proc.stdout], [], [], 0.2)
                if ready:
                    line = proc.stdout.readline().strip()
                    break
            assert line.startswith("DEPENDENCY_CHILD_READY"), stderr_path.read_text(encoding="utf-8") or line
            _tag, pid_text, pgid_text = line.split()
            child_pid = int(pid_text)
            assert int(pgid_text) != os.getpgid(proc.pid)
            proc.terminate()
            proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
    assert proc.returncode == -signal.SIGTERM
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"依赖子进程仍存活：{child_pid}")
    released = False
    probe_until = time.monotonic() + 0.5
    while time.monotonic() < probe_until:
        try:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno != errno.ENXIO:
                raise
            time.sleep(0.05)
            continue
        os.close(fd)
        released = True
        break
    assert not released
    rest = proc.stdout.read() if proc.stdout is not None else ""
    assert "DEPENDENCY_CHILD_DONE" not in rest
    assert marker.read_text(encoding="utf-8") == "OLD"
    assert snapshot(runtime) == before
    assert not (home / "vendor" / module.TRANSACTION_NAME).exists()
    assert not (home / "vendor" / module.BACKUP_NAME).exists()


def test_non_posix_cancel_does_not_claim_process_tree(monkeypatch: pytest.MonkeyPatch):
    module = load_module("installer_non_posix_cancel")
    monkeypatch.setattr(os, "name", "nt", raising=False)

    def forbid_killpg(*args, **_kwargs):
        raise AssertionError(f"非 POSIX 路径不应 killpg：{args}")

    monkeypatch.setattr(os, "killpg", forbid_killpg, raising=False)

    class Dummy:
        def __init__(self) -> None:
            self.pid = 424242
            self.returncode = None
            self.signals: list[str] = []

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.signals.append("term")
            self.returncode = -15

        def kill(self) -> None:
            self.signals.append("kill")
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("dummy", timeout or 0)
            return self.returncode

    dummy = Dummy()
    module._TRACKED_DEPENDENCY_PROCESSES.append({"process": dummy, "group": True, "pgid": dummy.pid})
    try:
        report = module._cancel_tracked_dependency_processes()
    finally:
        module._TRACKED_DEPENDENCY_PROCESSES.clear()
    assert report["mechanism"] == "direct-only"
    assert report["claims_full_process_tree"] is False
    assert report["direct_stopped"] is True
    assert report["descendants_proven"] is False
    assert report["remaining_descendants"] == -1
    assert report["safe_to_restore"] is False
    assert "非 POSIX" in report["limitation"]
    assert "不宣称" in report["limitation"]
    assert "人工确认" in report["limitation"]
    assert dummy.signals == ["term"]


def test_venv_failure_keeps_actionable_message(tmp_path: Path):
    module = load_module("installer_venv_message")

    def fail(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command)

    module._run_tracked_command = fail
    with pytest.raises(RuntimeError, match="python3-venv"):
        module.install_dependencies(tmp_path / "runtime", with_dev=False)


def test_reaped_parent_group_survives_sigterm_until_group_kill(tmp_path: Path):
    """父进程先退出并被回收后，忽略 SIGTERM 的同组子孙仍必须被取消。不调用 pip。"""
    module = load_module("installer_reaped_parent_group")
    module.DEPENDENCY_CANCEL_GRACE_SECONDS = 1.0
    ready = tmp_path / "ready"
    pid_path = tmp_path / "child-pid"
    script = (
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "ready = Path(sys.argv[1]); pid_path = Path(sys.argv[2])\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    fd = os.open(os.devnull, os.O_RDWR)\n"
        "    os.dup2(fd, 0); os.dup2(fd, 1); os.dup2(fd, 2)\n"
        "    if fd > 2: os.close(fd)\n"
        "    pid_path.write_text(str(os.getpid()), encoding='utf-8')\n"
        "    ready.write_text('ready', encoding='utf-8')\n"
        "    while True:\n"
        "        time.sleep(0.1)\n"
        "deadline = time.time() + 10\n"
        "while not ready.exists():\n"
        "    if time.time() > deadline:\n"
        "        os._exit(2)\n"
        "    time.sleep(0.01)\n"
        "os._exit(0)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(ready), str(pid_path)],
        start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    bystander = None
    child_pid = None
    try:
        record = module._register_dependency_process(proc, group=True)
        assert record["group_proven"] is True
        assert record["pgid"] == proc.pid > 1
        assert record["pgid"] != os.getpgrp()
        assert isinstance(record["leader_starttime"], int)
        assert proc.wait(timeout=15) == 0
        assert not Path(f"/proc/{proc.pid}").exists()
        child_pid = int(pid_path.read_text(encoding="utf-8"))
        os.kill(child_pid, 0)
        assert os.getpgid(child_pid) == record["pgid"]
        assert module._posix_descendants(proc.pid) == []
        bystander = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        bystander_pgid = os.getpgid(bystander.pid)
        assert bystander_pgid != record["pgid"]
        status, members = module._proven_group_members(record)
        assert status == "live"
        assert child_pid in members
        assert bystander.pid not in members
        report = module._cancel_tracked_dependency_processes()
        assert report["safe_to_restore"] is True
        assert report["claims_full_process_tree"] is True
        assert report["mechanism"] == "process-group"
        assert report["remaining_descendants"] == 0
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        os.kill(bystander.pid, 0)
        assert os.getpgid(bystander.pid) == bystander_pgid
        assert module._TRACKED_DEPENDENCY_PROCESSES == []
    finally:
        module._TRACKED_DEPENDENCY_PROCESSES.clear()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for pid in (child_pid, None if bystander is None else bystander.pid):
            if not pid:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if bystander is not None and bystander.poll() is None:
            bystander.wait(timeout=5)


def test_reused_leader_identity_does_not_kill_other_group(monkeypatch: pytest.MonkeyPatch):
    module = load_module("installer_reused_pgid")
    module.DEPENDENCY_CANCEL_GRACE_SECONDS = 0.0
    killed: list[tuple[int, int]] = []
    groups: list[tuple[int, int]] = []

    def forbid_kill(pid, sig):
        killed.append((pid, sig))

    def forbid_killpg(pgid, sig):
        groups.append((pgid, sig))

    monkeypatch.setattr(os, "kill", forbid_kill)
    monkeypatch.setattr(os, "killpg", forbid_killpg, raising=False)

    class Dead:
        def __init__(self) -> None:
            self.pid = 55555
            self.returncode = 0

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            raise AssertionError("进程组身份已被复用，不应再向直接进程发信号")

        def kill(self) -> None:
            raise AssertionError("进程组身份已被复用，不应再向直接进程发信号")

    record = {
        "process": Dead(),
        "group": True,
        "group_proven": True,
        "pgid": 55555,
        "leader_pid": 55555,
        "leader_starttime": 100,
    }
    module._TRACKED_DEPENDENCY_PROCESSES.append(record)

    def fake_stat(pid: int):
        if pid == 55555:
            return ("S", 55555, 999)
        if pid == 424242:
            return ("S", 424242, 50)
        return None

    monkeypatch.setattr(module, "_proc_stat", fake_stat)
    monkeypatch.setattr(module, "_iter_proc_pids", lambda: [55555, 424242])
    try:
        report = module._cancel_tracked_dependency_processes()
    finally:
        module._TRACKED_DEPENDENCY_PROCESSES.clear()
    assert groups == []
    assert killed == []
    assert record.get("group_unproven") is True
    assert report["safe_to_restore"] is False
    assert report["claims_full_process_tree"] is False
    assert "PID" in report["limitation"]
    assert "人工确认" in report["limitation"]


def test_non_posix_failure_keeps_scene_until_manual_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_module("installer_non_posix_scene")
    source = tmp_path / "source"
    home = tmp_path / "home"
    write_complete_source(source, module, "OLD")
    first = run_installer(source, home, "--skip-deps")
    assert first.returncode == 0, first.stderr
    vendor = home / "vendor"
    runtime = vendor / module.PLUGIN_NAME
    skills = home / "skills"
    (runtime / "old-generation.txt").write_text("OLD", encoding="utf-8")
    before = snapshot(runtime)
    entry = skills / "cn-patent-workflow"
    assert (entry / "SKILL.md").is_file()

    staging_parent = vendor / f".{module.PLUGIN_NAME}-nt-probe"
    staging_parent.mkdir()
    staging = staging_parent / module.PLUGIN_NAME
    staging.mkdir()
    module._begin_transaction(vendor, runtime, skills, staging)
    runtime.mkdir()
    (runtime / "old-generation.txt").write_text("NEW-DIRTY", encoding="utf-8")
    backup = vendor / module.BACKUP_NAME
    assert (backup / "old-generation.txt").read_text(encoding="utf-8") == "OLD"
    assert not entry.exists()

    def forbid_killpg(*args, **_kwargs):
        raise AssertionError(f"非 POSIX 路径不应 killpg：{args}")

    monkeypatch.setattr(os, "killpg", forbid_killpg, raising=False)

    class Dummy:
        def __init__(self) -> None:
            self.pid = 424242
            self.returncode = None
            self.signals: list[str] = []

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.signals.append("term")
            self.returncode = -15

        def kill(self) -> None:
            self.signals.append("kill")
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("dummy", timeout or 0)
            return self.returncode

    dummy = Dummy()
    module._TRACKED_DEPENDENCY_PROCESSES.append(
        {"process": dummy, "group": False, "pgid": None, "group_proven": False}
    )
    real_cancel = module._cancel_tracked_dependency_processes

    def cancel_as_nt():
        # 只在取消判断里伪装平台。全程改 os.name 会让 Linux 上的 tempfile 写出反斜杠路径。
        monkeypatch.setattr(os, "name", "nt")
        try:
            return real_cancel()
        finally:
            monkeypatch.setattr(os, "name", "posix")

    module._cancel_tracked_dependency_processes = cancel_as_nt
    try:
        with pytest.raises(RuntimeError, match="必须人工确认后才能恢复"):
            module._abort_installation(vendor, skills, RuntimeError("deps failed"))
    finally:
        module._TRACKED_DEPENDENCY_PROCESSES.clear()
    assert dummy.signals == ["term"]

    assert (runtime / "old-generation.txt").read_text(encoding="utf-8") == "NEW-DIRTY"
    assert (backup / "old-generation.txt").read_text(encoding="utf-8") == "OLD"
    assert not entry.exists()
    journal_path = vendor / module.TRANSACTION_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == "prepared"
    assert journal["dependency_processes"]["state"] == "unconfirmed"
    assert journal["dependency_processes"]["manual_confirmation_required"] is True

    with pytest.raises(RuntimeError, match="必须人工确认后才能恢复"):
        module.recover_pending(vendor, skills)
    with pytest.raises(RuntimeError, match="必须人工确认后才能恢复"):
        module.recover_pending(vendor, skills)
    assert (runtime / "old-generation.txt").read_text(encoding="utf-8") == "NEW-DIRTY"
    assert (backup / "old-generation.txt").read_text(encoding="utf-8") == "OLD"

    journal["dependency_processes"] = {
        "state": "operator-confirmed",
        "manual_confirmation_required": True,
    }
    module._atomic_json(journal_path, journal)
    with pytest.raises(RuntimeError, match="必须人工确认后才能恢复"):
        module.recover_pending(vendor, skills)
    assert (runtime / "old-generation.txt").read_text(encoding="utf-8") == "NEW-DIRTY"

    journal["dependency_processes"] = {
        "state": "operator-confirmed",
        "manual_confirmation_required": False,
    }
    module._atomic_json(journal_path, journal)
    module.recover_pending(vendor, skills)
    assert snapshot(runtime) == before
    assert (entry / "SKILL.md").is_file()
    assert not journal_path.exists()
    assert not backup.exists()
    assert not (skills / module.ENTRY_BACKUP_NAME).exists()


def test_committed_journal_cleans_forward_despite_dependency_note(tmp_path: Path):
    module = load_module("installer_committed_note")
    vendor = tmp_path / "vendor"
    skills = tmp_path / "skills"
    vendor.mkdir()
    skills.mkdir()
    runtime = vendor / module.PLUGIN_NAME
    runtime.mkdir()
    (runtime / "marker.txt").write_text("NEW", encoding="utf-8")
    backup = vendor / module.BACKUP_NAME
    backup.mkdir()
    (backup / "marker.txt").write_text("OLD", encoding="utf-8")
    (skills / module.ENTRY_BACKUP_NAME).mkdir()
    journal = {
        "schema_id": "cn-patent-codex-skill-install-transaction/v1",
        "phase": "committed",
        "staging_name": f".{module.PLUGIN_NAME}-done",
        "runtime_existed": True,
        "entries_existed": {name: False for name in module.REQUIRED_SKILLS},
        "dependency_processes": {
            "state": "unconfirmed",
            "manual_confirmation_required": True,
            "reason": "non-posix",
        },
    }
    module._atomic_json(vendor / module.TRANSACTION_NAME, journal)
    module.recover_pending(vendor, skills)
    assert (runtime / "marker.txt").read_text(encoding="utf-8") == "NEW"
    assert not backup.exists()
    assert not (vendor / module.TRANSACTION_NAME).exists()
    assert not (skills / module.ENTRY_BACKUP_NAME).exists()


def test_legal_index_rejects_windows_escapes_without_reading_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_module("installer_legal_path_guard")
    index = json.loads((ROOT / "references" / "cn-legal-sources" / "source-index.json").read_text(encoding="utf-8"))
    for relative in index["sources"].values():
        assert module._is_safe_relative(relative), relative
    for rels in index["topics"].values():
        for relative in rels:
            assert module._is_safe_relative(relative), relative
    positives = [
        "专利法(2020-10-17).md",
        "审查指南2026MD/guide-full.md",
        "审查指南2026MD/chapters/第二部分-第一章 不授予专利权的申请.md",
    ]
    negatives = [
        "C:/foo",
        "C:foo",
        "C:foo/bar",
        "c:/Windows",
        "//server/share/foo",
        r"\\server\share\foo",
        r"C:\foo",
        "/etc/passwd",
        "../secret.txt",
        "chapters/../../secret.txt",
        r"foo\..\secret.txt",
        r"\\?\C:\foo",
    ]
    for item in positives:
        assert module._is_safe_relative(item), item
    for item in negatives:
        assert not module._is_safe_relative(item), item

    source = tmp_path / "source"
    write_complete_source(source, module)
    assert module.check_package_integrity(source) == []
    legal = source / "references" / "cn-legal-sources"
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SECRET-OUTSIDE", encoding="utf-8")
    outside_text = str(outside.resolve())
    escape = Path(os.path.relpath(outside, legal)).as_posix()
    assert escape.startswith("../")
    payload = json.loads((legal / "source-index.json").read_text(encoding="utf-8"))
    payload["topics"]["subject_matter_and_computer_programs"].extend([
        "C:/foo", "C:foo", r"\\server\share\foo", "/etc/passwd", escape,
    ])
    (legal / "source-index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert module._contained_legal_path(legal, "C:/foo") is None
    assert module._contained_legal_path(legal, "C:foo") is None
    assert module._contained_legal_path(legal, escape) is None
    contained = module._contained_legal_path(legal, "专利法(2020-10-17).md")
    assert contained == legal / "专利法(2020-10-17).md"

    seen: list[str] = []
    real_stat = os.stat
    real_lstat = os.lstat

    def spy_stat(path, *args, **kwargs):
        seen.append(os.fspath(path))
        return real_stat(path, *args, **kwargs)

    def spy_lstat(path, *args, **kwargs):
        seen.append(os.fspath(path))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", spy_stat)
    monkeypatch.setattr(os, "lstat", spy_lstat)
    errors = module.check_package_integrity(source)
    listed = module.required_package_files(source)
    joined_errors = "\n".join(errors)
    joined_seen = "\n".join(seen)
    assert "C:/foo" in joined_errors
    assert "C:foo" in joined_errors
    assert "非法路径" in joined_errors
    assert "SECRET-OUTSIDE" not in joined_errors
    assert outside_text not in joined_seen
    assert "C:/foo" not in joined_seen
    assert "C:foo" not in joined_seen
    for item in listed:
        assert "C:/foo" not in item
        assert "C:foo" not in item
        assert not item.startswith(("/", "\\"))
        assert ".." not in Path(item).parts
