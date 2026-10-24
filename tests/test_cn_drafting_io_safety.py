"""F01 起草报告 I/O 隔离：输入原文、别名和输出互冲回归。"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER_TEST = ROOT / "tests/test_cn_feature_ledger_v2.py"
ARCH_TEST = ROOT / "tests/test_cn_claim_architecture.py"
IO_SCRIPT = ROOT / "skills/cn-patent-application-creator/scripts/cn_drafting_io.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ledger_tests = load(LEDGER_TEST, "f01_ledger_test_fixture")
arch_tests = load(ARCH_TEST, "f01_arch_test_fixture")
io = load(IO_SCRIPT, "f01_drafting_io")


def run_ledger(paths: tuple[Path, Path, Path, Path], output: Path, table: Path | None = None):
    ledger, claims, specification, _ = paths
    return ledger_tests.run(ledger, claims, specification, output) if table is None else __import__("subprocess").run(
        [sys.executable, str(ROOT / "skills/cn-patent-application-creator/scripts/build_feature_ledger.py"), "--ledger", str(ledger), "--claims", str(claims), "--specification", str(specification), "--output", str(output), "--table", str(table)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )


def test_ledger_rejects_same_path_resolve_hardlink_symlink_and_output_conflict(tmp_path: Path):
    for mode in ("same", "resolve", "hardlink", "symlink"):
        case = tmp_path / mode
        case.mkdir()
        paths = ledger_tests.fixture(case)
        _, claims, _, report = paths
        original = claims.read_bytes()
        if mode == "same":
            output = claims
        elif mode == "resolve":
            # 不同拼写但 resolve 后与输入文件相同。
            output = case / "nested" / ".." / claims.name
        else:
            output = case / "alias.json"
            if mode == "hardlink":
                os.link(claims, output)
            else:
                output.symlink_to(claims)
        result = run_ledger(paths, output)
        assert result.returncode == 3, (mode, result.stdout, result.stderr)
        assert claims.read_bytes() == original

    case = tmp_path / "outputs"
    case.mkdir()
    paths = ledger_tests.fixture(case)
    _, claims, _, _ = paths
    original = claims.read_bytes()
    output = case / "report.md"
    result = run_ledger(paths, output, output)
    assert result.returncode == 3
    assert claims.read_bytes() == original
    assert not output.exists()

    # --output 与 --table 的同路径、硬链接、符号链接别名都必须在任何写入前拒绝。
    for mode in ("same", "hardlink", "symlink"):
        conflict_case = case / f"output-conflict-{mode}"
        conflict_case.mkdir()
        conflict_paths = ledger_tests.fixture(conflict_case)
        conflict_output = conflict_case / "report.json"
        conflict_output.write_text("sentinel", encoding="utf-8")
        if mode == "same":
            table = conflict_output
        else:
            table = conflict_case / f"{mode}.md"
            if mode == "hardlink":
                os.link(conflict_output, table)
            else:
                table.symlink_to(conflict_output)
        result = run_ledger(conflict_paths, conflict_output, table)
        assert result.returncode == 3, (mode, result.stdout, result.stderr)
        assert conflict_output.read_text(encoding="utf-8") == "sentinel"

    # --table 对输入文件的路径别名也必须拒绝。
    for mode in ("same", "resolve", "hardlink", "symlink"):
        table_case = case / f"table-input-{mode}"
        table_case.mkdir()
        table_paths = ledger_tests.fixture(table_case)
        _, table_claims, _, _ = table_paths
        table_output = table_case / "report.json"
        if mode == "same":
            table = table_claims
        elif mode == "resolve":
            table = table_case / "nested" / ".." / table_claims.name
        else:
            table = table_case / "claims-alias"
            if mode == "hardlink":
                os.link(table_claims, table)
            else:
                table.symlink_to(table_claims)
        result = run_ledger(table_paths, table_output, table)
        assert result.returncode == 3, (mode, result.stdout, result.stderr)
        assert table_claims.read_text(encoding="utf-8").startswith("# 权利要求书")
        assert not table_output.exists()


def test_architecture_rejects_output_alias_and_preserves_claims(tmp_path: Path):
    case = tmp_path / "architecture"
    contract, claims, specification, report = arch_tests.fixture(case)
    original = claims.read_bytes()
    alias = case / "claims-link.json"
    alias.symlink_to(claims)
    result = arch_tests.run(contract, claims, specification, alias)
    assert result.returncode == 3
    assert claims.read_bytes() == original
    assert report is not alias


def test_atomic_write_rechecks_source_hash_before_replace(tmp_path: Path):
    source = tmp_path / "claims.md"
    output = tmp_path / "report.json"
    source.write_text("原始权利要求", encoding="utf-8")
    guard = io.DraftingOutputGuard([source], [output])
    original_check = guard.check
    calls = 0

    def mutate_before_final_check():
        nonlocal calls
        calls += 1
        if calls == 3:
            source.write_text("被外部修改", encoding="utf-8")
        return original_check()

    with mock.patch.object(guard, "check", side_effect=mutate_before_final_check):
        with pytest.raises(io.DraftingOutputError, match="输入文件在校验期间发生变化"):
            guard.write_texts(["报告"])
    assert not output.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() != hashlib.sha256("原始权利要求".encode()).hexdigest()
