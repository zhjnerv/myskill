import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import domain_fixture_materialize as domain_fixtures

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills/cn-patent-diagram-generator"
CONTRACT_PATH = SKILL_DIR / "config" / "instruction-stability-contract.json"
CHECKER_SCRIPT = SKILL_DIR / "scripts" / "check_stability_evidence.py"
POSITIVE_REPORT = SKILL_DIR / "assets/stability/positive-final-verification-v4.json"


def _run_checker(args):
    result = subprocess.run(
        [sys.executable, str(CHECKER_SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result


def _expand_case(case, checkers, materialized):
    checker = checkers[case["checker_ids"][0]]
    artifact_paths = {
        item["artifact_id"]: domain_fixtures.remap_domain_path(SKILL_DIR / item["path"], materialized)
        for item in case["artifacts"]
    }
    args = []
    for arg in checker["args"]:
        if arg.startswith("{artifact:") and arg.endswith("}"):
            args.append(str(artifact_paths[arg[10:-1]]))
        else:
            args.append(arg)
    return args


def _domain_args(report, constraint, domain, *, manifest=None, brief=None, visual=None, include_brief=True):
    args = [
        "--report", str(report),
        "--manifest", str(manifest or (domain / "legal-manifest.json")),
        "--constraint", constraint,
        "--observable", "domain-observable",
        "--measurement", "domain-pass",
    ]
    if include_brief:
        args.extend(["--brief", str(brief or (domain / "legal-brief.json"))])
    if visual is not None:
        args.extend(["--visual-review", str(visual)])
    return args


def _install_policy():
    """读取安装器现有后缀清单，不修改白名单。"""
    path = ROOT / "scripts/install_codex_skill.py"
    spec = importlib.util.spec_from_file_location("cn_codex_install_policy_for_domain_suffix", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载分发策略：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_domain_inputs_are_tracked_text():
    """合同和领域夹具不得依赖被忽略的 PNG、Draw.io，或无法分发的 .xml。"""
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert re.search(r"\.png\"", text) is None
    assert re.search(r"\.drawio\"", text) is None
    assert ".drawio.xml" not in text
    assert "domain-manifest" in text
    domain = domain_fixtures.DOMAIN_DIR
    assert not list(domain.glob("*.png"))
    assert not list(domain.glob("*.drawio"))
    assert not list(domain.glob("*.xml"))
    templates = ("figure-1.drawio.txt", "figure-2.drawio.txt")
    policy = _install_policy()
    assert ".txt" in policy.SOURCE_SUFFIXES
    assert ".xml" not in policy.SOURCE_SUFFIXES
    for name in templates:
        path = domain / name
        assert path.is_file()
        assert path.suffix.lower() in policy.SOURCE_SUFFIXES
        assert path.read_text(encoding="utf-8").startswith("<mxfile")
    domain_text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(domain.glob("*.json")))
    assert "figure-1.drawio.txt" in domain_text
    assert "figure-2.drawio.txt" in domain_text
    assert ".drawio.xml" not in domain_text
    assert '.drawio"' not in domain_text
    files, errors = policy.collect_source_files(ROOT, distribution_only=True)
    accepted = {item.relative_to(ROOT).as_posix() for item in files}
    for name in templates:
        relative = f"skills/cn-patent-diagram-generator/assets/stability/domain/{name}"
        assert relative in accepted
        assert not any(relative in item for item in errors)


def test_synthesis_hashes_match_distinct_figure_reports(tmp_path):
    domain = domain_fixtures.materialize_domain(tmp_path / "domain")
    report = json.loads(POSITIVE_REPORT.read_text(encoding="utf-8"))
    by_number = {figure["figure_number"]: figure for figure in report["figures"]}

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert by_number[1]["drawio"]["sha256"] != by_number[2]["drawio"]["sha256"]
    assert by_number[1]["png"]["sha256"] != by_number[2]["png"]["sha256"]
    assert by_number[1]["drawio"]["sha256"] == digest(domain / "figure-1.drawio.txt")
    assert by_number[2]["drawio"]["sha256"] == digest(domain / "figure-2.drawio.txt")
    assert by_number[1]["png"]["sha256"] == digest(domain / "figure-1-margin-10.png")
    assert by_number[2]["png"]["sha256"] == digest(domain / "figure-2-margin-10.png")
    assert not (domain_fixtures.DOMAIN_DIR / "figure-1-margin-10.png").exists()


def test_stability_fixtures(tmp_path):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    cases = contract.get("cases", [])
    checkers = {item["id"]: item for item in contract.get("checkers", [])}
    materialized = domain_fixtures.materialize_domain(tmp_path / "domain")

    for case in cases:
        for checker_id in case.get("checker_ids", []):
            case_for_checker = dict(case)
            case_for_checker["checker_ids"] = [checker_id]
            result = _run_checker(_expand_case(case_for_checker, checkers, materialized))
            assert result.returncode == case.get("expected_exit_code", 0), (
                f"Case {case['id']} with checker {checker_id} failed. Output: {result.stdout} {result.stderr}"
            )


def test_v4_positive_fixture_content():
    content = POSITIVE_REPORT.read_text(encoding="utf-8")
    data = json.loads(content)

    assert data.get("schema_id") == "cn-patent-drawing-verification/v4", "Schema ID must be v4"
    assert "DDS" not in content, "Must not contain real customer terms like DDS"
    assert "啁啾" not in content, "Must not contain real customer terms like 啁啾"


def test_geometry_checker_rejects_shell_report_and_file_drift(tmp_path):
    """空壳报告、改图不改报告、只改报告数值、缺文件都必须失败；合法边界仍通过。"""
    shell = tmp_path / "shell.json"
    shell.write_text('{"figures":[{"drawio":{}}]}\n', encoding="utf-8")
    domain = domain_fixtures.materialize_domain(tmp_path / "domain")
    for constraint in (
        "PATENT-DRAWING-NODE-TEXT-FIT",
        "PATENT-DRAWING-VERTICAL-SPACING",
        "PATENT-DRAWING-COLOR",
        "PATENT-DRAWING-NODE-SHAPE",
        "PATENT-DRAWING-EDGE-LABEL-READABILITY",
    ):
        shell_result = _run_checker([
            "--report", str(shell),
            "--constraint", constraint,
            "--observable", "domain-observable",
            "--measurement", "domain-pass",
        ])
        assert shell_result.returncode == 3, constraint + shell_result.stdout
        # 上下文齐全时也必须拒绝空壳报告，不能仅靠缺 manifest 让反例通过。
        bound_shell = _run_checker(_domain_args(shell, constraint, domain))
        assert bound_shell.returncode == 3, constraint + bound_shell.stdout
        assert "missing-domain-artifact" not in bound_shell.stdout

        legal = _run_checker(_domain_args(POSITIVE_REPORT, constraint, domain))
        assert legal.returncode == 0, constraint + legal.stdout + legal.stderr

    report = json.loads(POSITIVE_REPORT.read_text(encoding="utf-8"))
    for figure in report["figures"]:
        figure["drawio"]["sha256"] = "0" * 64
    changed_report = tmp_path / "numbers.json"
    changed_report.write_text(json.dumps(report), encoding="utf-8")
    numbers = _run_checker(_domain_args(changed_report, "PATENT-DRAWING-NODE-TEXT-FIT", domain))
    assert numbers.returncode == 3, numbers.stdout
    assert "report-drawio-sha-mismatch" in numbers.stdout

    boundary = _run_checker(_domain_args(
        SKILL_DIR / "assets/stability/near-miss-legal-PATENT-DRAWING-PNG-MARGIN.json",
        "PATENT-DRAWING-PNG-MARGIN",
        domain,
        manifest=domain / "boundary-manifest.json",
        brief=domain / "boundary-png-brief.json",
    ))
    assert boundary.returncode == 0, boundary.stdout + boundary.stderr


def test_distinct_figures_and_full_source_set(tmp_path):
    """两张不同附图可以通过；只动第二张或非首个来源必须失败，且不会补造缺文件。"""
    domain = domain_fixtures.materialize_domain(tmp_path / "domain")
    manifest = domain / "legal-manifest.json"
    visual = domain / "legal-visual.json"
    figure1 = (domain / "figure-1.drawio.txt").read_bytes()
    figure2 = (domain / "figure-2.drawio.txt").read_bytes()
    png1 = (domain / "figure-1-margin-10.png").read_bytes()
    png2 = (domain / "figure-2-margin-10.png").read_bytes()
    assert figure1 != figure2
    assert png1 != png2

    for constraint in (
        "PATENT-DRAWING-COLOR",
        "PATENT-DRAWING-PNG-MARGIN",
        "PATENT-DRAWING-OFFICIAL-EXPORT",
    ):
        result = _run_checker(_domain_args(POSITIVE_REPORT, constraint, domain))
        assert result.returncode == 0, constraint + result.stdout + result.stderr
    visual_result = _run_checker(_domain_args(
        POSITIVE_REPORT,
        "PATENT-DRAWING-VISUAL-BINDING",
        domain,
        visual=visual,
        include_brief=False,
    ))
    assert visual_result.returncode == 0, visual_result.stdout + visual_result.stderr

    drawio2 = domain / "figure-2.drawio.txt"
    drawio2.write_text(drawio2.read_text(encoding="utf-8").replace("#EAF2F8", "#FF0000"), encoding="utf-8")
    assert (domain / "figure-1.drawio.txt").read_bytes() == figure1
    changed = _run_checker(_domain_args(POSITIVE_REPORT, "PATENT-DRAWING-COLOR", domain))
    assert changed.returncode == 3, changed.stdout
    assert "figure-2" in changed.stdout
    drawio2.write_bytes(figure2)

    drawio2.unlink()
    missing_drawio = _run_checker(_domain_args(POSITIVE_REPORT, "PATENT-DRAWING-NODE-SHAPE", domain))
    assert missing_drawio.returncode == 3, missing_drawio.stdout
    assert "missing-domain-artifact" in missing_drawio.stdout
    assert not drawio2.exists()
    drawio2.write_bytes(figure2)

    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["figures"] = [item for item in manifest_data["figures"] if item["figure_number"] != 2]
    omitted = domain / "omitted-manifest.json"
    omitted.write_text(json.dumps(manifest_data), encoding="utf-8")
    omitted_result = _run_checker(_domain_args(
        POSITIVE_REPORT, "PATENT-DRAWING-COLOR", domain, manifest=omitted,
    ))
    assert omitted_result.returncode == 3, omitted_result.stdout
    assert "figure-coverage" in omitted_result.stdout

    png_path = domain / "figure-2-margin-10.png"
    png_path.write_bytes(domain_fixtures.synthesize_png(36, 34, 10, [48, 48, 48]))
    assert (domain / "figure-1-margin-10.png").read_bytes() == png1
    changed_png = _run_checker(_domain_args(POSITIVE_REPORT, "PATENT-DRAWING-PNG-MARGIN", domain))
    assert changed_png.returncode == 3, changed_png.stdout
    assert "figure-2" in changed_png.stdout
    png_path.unlink()
    missing_png = _run_checker(_domain_args(POSITIVE_REPORT, "PATENT-DRAWING-PNG-MARGIN", domain))
    assert missing_png.returncode == 3, missing_png.stdout
    assert "missing-domain-artifact" in missing_png.stdout
    assert not png_path.exists()
    png_path.write_bytes(png2)

    claims = domain / "claims-source.txt"
    original_claims = claims.read_text(encoding="utf-8")
    specification = (domain / "technical-source.txt").read_bytes()
    claims.write_text(original_claims + "补充一句。\n", encoding="utf-8")
    changed_source = _run_checker(_domain_args(POSITIVE_REPORT, "PATENT-DRAWING-COLOR", domain))
    assert changed_source.returncode == 3, changed_source.stdout
    assert "source-hash-mismatch:claims" in changed_source.stdout
    assert "source-hash-mismatch:specification" not in changed_source.stdout
    assert (domain / "technical-source.txt").read_bytes() == specification
    claims.write_text(original_claims, encoding="utf-8")

    empty = tmp_path / "empty.json"
    empty.write_text('{"figures":[]}\n', encoding="utf-8")
    empty_result = _run_checker(_domain_args(empty, "PATENT-DRAWING-COLOR", domain))
    assert empty_result.returncode == 3, empty_result.stdout

    export = json.loads((domain / "figure-2-export.json").read_text(encoding="utf-8"))
    export["outputs"]["png"]["sha256"] = "0" * 64
    (domain / "figure-2-export.json").write_text(json.dumps(export), encoding="utf-8")
    changed_export = _run_checker(_domain_args(POSITIVE_REPORT, "PATENT-DRAWING-OFFICIAL-EXPORT", domain))
    assert changed_export.returncode == 3, changed_export.stdout
    assert "figure-2" in changed_export.stdout

    visual_data = json.loads(visual.read_text(encoding="utf-8"))
    visual_data["figures"] = [item for item in visual_data["figures"] if item["figure_number"] != 2]
    partial_visual = tmp_path / "partial-visual.json"
    partial_visual.write_text(json.dumps(visual_data), encoding="utf-8")
    missing_visual = _run_checker(_domain_args(
        POSITIVE_REPORT,
        "PATENT-DRAWING-VISUAL-BINDING",
        domain,
        visual=partial_visual,
        include_brief=False,
    ))
    assert missing_visual.returncode == 3, missing_visual.stdout
    assert "figure-coverage" in missing_visual.stdout
