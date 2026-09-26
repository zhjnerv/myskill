#!/usr/bin/env python3
"""中国发明专利综合审查的 CN v2 生产编排器。

两个子命令构成一条可独立复算的闭环：

    prepare   读取真实申请文件 -> 冻结输入/规则/工具身份 -> 调用三个真实检查器
              -> 输出三份原始报告和独立语义审查输入模板
    finalize  校验语义输入与冻结证据的新鲜度 -> 守恒转换全部原始 finding/gap
              -> 构造专项报告、41 维原子评估和 bundle

编排器本身不作任何法律判断，也不产生总体结论。处置状态只能由独立 verifier 派生。

守恒的实现要点：finalize 机械地把原始 finding/gap 并入其所属维度的评估，语义审查者
无法通过省略来"清掉"一个仍有确定性失败的维度——规范状态不变量会直接拒绝该组合。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_ROOT = SCRIPT_DIR.parents[1]

PREPARE_INPUT_SCHEMA = "cn-patent-review-prepare-input/v2"
PREPARE_MANIFEST_SCHEMA = "cn-patent-review-prepare-manifest/v2"
SEMANTIC_INPUT_SCHEMA = "cn-patent-review-semantic-input/v2"

TOOL_ID = "cn-patent-reviewer-orchestrator"
TOOL_VERSION = "2.0.0"

REVIEW_TYPES = ("claims", "specification", "formalities")
CHECKER_SCRIPTS = {
    "claims": SKILLS_ROOT / "cn-patent-claims-analyzer" / "scripts" / "check_claims_cn.py",
    "specification": SKILLS_ROOT / "cn-patent-specification-reviewer" / "scripts" / "build_support_matrix_cn.py",
    "formalities": SKILLS_ROOT / "cn-patent-formalities-reviewer" / "scripts" / "check_formalities_cn.py",
}

ALLOWED_PREPARE_FIELDS = {
    "schema_version", "application_id", "claims", "specification", "features", "formalities_manifest",
    "provenance_artifacts",
}

# 每个维度默认的失败关闭状态：未评估即覆盖度 NONE、结论 INCONCLUSIVE、证据 NONE/MISSING。
UNASSESSED_STATE = {
    "coverage": "NONE",
    "result": "INCONCLUSIVE",
    "evidence": {"mode": "NONE", "sufficiency": "MISSING", "artifact_ids": [], "source_locations": []},
    "severity": "NONE",
}

EXIT_OK = 0
EXIT_DETERMINISTIC_FAIL = 2
EXIT_INPUT_ERROR = 3
EXIT_RESOURCE_ERROR = 4


class OrchestrationError(ValueError):
    """输入、路径、新鲜度或规范错误；属于工具错误，不产生法律结论。"""


class ResourceLimitError(Exception):
    """资源越限；统一退出码 4，不得转换为法律 finding。"""


def load_module(name: str, path: Path):
    """按路径加载同仓库内的检查器与规范模块，避免跨 Skill 包依赖。"""

    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OrchestrationError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cn_contract = load_module("cn_contract", SCRIPT_DIR / "cn_contract.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def collection_digest(items: list[dict[str, Any]]) -> str:
    material = sorted((item["artifact_id"], item["sha256"]) for item in items)
    return sha256_bytes(canonical_json(material))


def evidence_digest(report: dict[str, Any]) -> str:
    """对原始报告的证据内容取摘要，排除耗时遥测。

    resource_usage 含 elapsed_milliseconds 及随之变动的 output_bytes，属运行遥测而非证据。
    把它算进证据绑定会让相同输入产生不同的 prepare_id，绑定就不再是证据的纯函数。
    逐文件的字节级新鲜度仍由各自的 sha256 单独校验，篡改依然会被发现。
    """

    return sha256_bytes(canonical_json({
        key: value for key, value in report.items() if key != "resource_usage"
    }))


def read_json(path: Path, limit: int, label: str) -> tuple[bytes, Any]:
    """读取 UTF-8 无 BOM JSON；超限属资源错误，格式错误属输入错误。"""

    if not path.is_file():
        raise OrchestrationError(f"{label} 不存在：{path}")
    if path.stat().st_size > limit:
        raise ResourceLimitError(f"{label} 超过 {limit} 字节上限")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ResourceLimitError(f"{label} 超过 {limit} 字节上限")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise OrchestrationError(f"{label} 必须是 UTF-8 无 BOM")
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OrchestrationError(f"{label} 不是合法 UTF-8 JSON：{exc}") from exc


def resolve_under(base: Path, raw_path: str, label: str) -> Path:
    """把声明路径解析到 base 之下，拒绝越界引用。"""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise OrchestrationError(f"{label} 必须是非空路径字符串")
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise OrchestrationError(f"{label} 越出输入目录：{raw_path}") from exc
    return resolved


def make_artifact(artifact_id: str, path: Path | str, raw: bytes, media_type: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": sha256_bytes(raw),
        "byte_length": len(raw),
        "media_type": media_type,
        "encoding": "utf-8",
    }


def _same_file(left: Path, right: Path) -> bool:
    """判断两个已解析路径是否指向同一文件，兼顾硬链接和普通重复路径。"""

    if left == right:
        return True
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError):
        return False


def _provenance_declarations(declaration: Any, contract) -> list[dict[str, str]]:
    """将输入声明的 provenance_artifacts 规范化为唯一的 id/path 列表。

    为便于人工维护，同时接受 ``[{artifact_id, path}, ...]`` 和
    ``{artifact_id: path}`` 两种写法；写入 manifest 时统一为带哈希的 artifact 数组。
    """

    if declaration is None:
        return []
    if isinstance(declaration, dict):
        entries = [{"artifact_id": key, "path": value} for key, value in declaration.items()]
    elif isinstance(declaration, list):
        entries = declaration
    else:
        raise OrchestrationError("prepare 输入的 provenance_artifacts 必须是数组或对象")

    config = contract.data.get("provenance", {})
    declared_fields = set(config.get("declaration_fields", ("artifact_id", "path")))
    pattern = config.get("artifact_id_pattern", r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
    max_count = contract.limits.get("provenance_max_artifacts")
    if isinstance(max_count, int) and len(entries) > max_count:
        raise ResourceLimitError(f"provenance_artifacts 数量超过规范上限 {max_count}")

    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != declared_fields:
            raise OrchestrationError(
                f"provenance_artifacts[{index}] 必须恰好包含字段 {sorted(declared_fields)}"
            )
        artifact_id = item.get("artifact_id")
        raw_path = item.get("path")
        if not isinstance(artifact_id, str) or not re.fullmatch(pattern, artifact_id):
            raise OrchestrationError(
                f"provenance_artifacts[{index}].artifact_id 不符合规范标识格式"
            )
        if artifact_id in seen:
            raise OrchestrationError(f"provenance_artifacts 出现重复 artifact_id：{artifact_id}")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise OrchestrationError(f"provenance_artifacts[{index}].path 必须是非空字符串")
        seen.add(artifact_id)
        normalized.append({"artifact_id": artifact_id, "path": raw_path})
    return normalized


def build_provenance_artifacts(
    declaration: Any, base: Path, core_paths: list[Path], contract
) -> list[dict[str, Any]]:
    """读取并冻结前置流程证据，所有路径必须位于 prepare 输入目录之下。"""

    artifacts: list[dict[str, Any]] = []
    seen_paths: list[Path] = list(core_paths)
    for item in _provenance_declarations(declaration, contract):
        path = resolve_under(base, item["path"], f"provenance_artifacts[{item['artifact_id']}]")
        if not path.is_file():
            raise OrchestrationError(f"provenance_artifacts[{item['artifact_id']}] 不存在：{path}")
        if any(_same_file(path, existing) for existing in seen_paths):
            raise OrchestrationError(
                f"provenance_artifacts[{item['artifact_id']}] 与其他证据工件指向同一文件：{path}"
            )
        raw = path.read_bytes()
        if len(raw) > contract.limits["verifier_max_single_artifact_bytes"]:
            raise ResourceLimitError(
                f"provenance_artifacts[{item['artifact_id']}] 超过单工件字节上限"
            )
        if raw.startswith(b"\xef\xbb\xbf"):
            raise OrchestrationError(
                f"provenance_artifacts[{item['artifact_id']}] 必须是 UTF-8 无 BOM"
            )
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OrchestrationError(
                f"provenance_artifacts[{item['artifact_id']}] 不是合法 UTF-8 文本：{exc}"
            ) from exc
        media_type = "application/json" if path.suffix.lower() == ".json" else "text/plain"
        artifacts.append(make_artifact(item["artifact_id"], path, raw, media_type))
        seen_paths.append(path)
    return artifacts


def write_json_atomic(path: Path, payload: bytes, protected: list[Path]) -> None:
    """临时文件加原子替换；拒绝覆盖任何证据输入。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    for candidate in protected:
        if resolved == candidate.resolve() or (
            resolved.exists() and candidate.exists() and os.path.samefile(resolved, candidate)
        ):
            raise OrchestrationError(f"输出路径与证据输入冲突：{candidate}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def run_checkers(paths: dict[str, Path], contract) -> dict[str, dict[str, Any]]:
    """在进程内调用三个真实检查器；任何一份不合规都立即失败。"""

    claims_module = load_module("cn_claims_checker", CHECKER_SCRIPTS["claims"])
    specification_module = load_module("cn_specification_checker", CHECKER_SCRIPTS["specification"])
    formalities_module = load_module("cn_formalities_checker", CHECKER_SCRIPTS["formalities"])

    reports: dict[str, dict[str, Any]] = {}
    try:
        claims_raw, claims_text = claims_module.read_input(paths["claims"])
        reports["claims"] = claims_module.analyze_claims(claims_text, str(paths["claims"]), claims_raw)

        specification_raw, specification_text = specification_module.read_specification(paths["specification"])
        features_raw, features = specification_module.read_features(paths["features"])
        reports["specification"] = specification_module.build_raw_report(
            specification_text,
            features,
            specification_bytes=specification_raw,
            features_bytes=features_raw,
            specification_name=str(paths["specification"]),
            features_name=str(paths["features"]),
        )

        manifest_raw = formalities_module.read_limited(
            paths["formalities_manifest"], formalities_module.MAX_MANIFEST_BYTES, "manifest"
        )
        manifest = json.loads(manifest_raw.decode("utf-8"))
        formalities_module.ensure_json_depth(manifest)
        reports["formalities"], _ = formalities_module.analyse(
            manifest, paths["formalities_manifest"], manifest_raw
        )
    except (claims_module.ResourceLimitError, specification_module.ResourceLimitError,
            formalities_module.ResourceLimitError) as exc:
        raise ResourceLimitError(f"检查器资源失败：{exc}") from exc
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise OrchestrationError(f"检查器输入失败：{exc}") from exc

    for review_type, report in reports.items():
        problems = contract.validate_raw_report(report, f"raw:{review_type}")
        if problems:
            raise OrchestrationError(
                f"{review_type} 原始报告不符合 CN v2 规范：" + "；".join(problems[:5])
            )
    return reports


def build_semantic_template(
    contract,
    prepare_id: str,
    binding: dict[str, str],
    provenance_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成 41 维语义审查输入模板，默认全部失败关闭为未评估。"""

    assessments: list[dict[str, Any]] = []
    semantic_gaps: list[dict[str, Any]] = []
    for dimension in contract.data["dimensions"]:
        dimension_id = dimension["id"]
        gap_id = stable_id("SG", prepare_id, dimension_id, "SEMANTIC_REVIEW_NOT_PERFORMED")
        semantic_gaps.append({
            "gap_id": gap_id,
            "dimension_id": dimension_id,
            "category": "SEMANTIC_REVIEW_NOT_PERFORMED",
            "reason": f"独立语义审查尚未对{dimension['citation']}作出评估。",
            "evidence": [{
                "artifact_id": "review-contract",
                "location": f"dimensions.{dimension_id}",
                "excerpt": dimension["required_evidence"][:240],
            }],
            "blocks_assessment": True,
        })
        assessments.append({
            "rule_id": dimension_id,
            "target_id": "application",
            **json.loads(json.dumps(UNASSESSED_STATE)),
            "finding_ids": [],
            "gap_ids": [gap_id],
            "_citation": dimension["citation"],
            "_required_evidence": dimension["required_evidence"],
            "_non_inference_boundary": dimension["non_inference_boundary"],
        })
    template = {
        "schema_version": SEMANTIC_INPUT_SCHEMA,
        "prepare_id": prepare_id,
        "evidence_binding": binding,
        "assessments": assessments,
        "semantic_gaps": semantic_gaps,
    }
    # provenance 数组与哈希同时传给独立语义审查者，避免其只能看到不可解释的摘要值。
    # 旧版无 provenance 的 prepare 仍保持 v2 兼容，不强行增加空字段。
    if provenance_artifacts is not None:
        template["provenance_artifacts"] = provenance_artifacts
    return template


def command_prepare(args: argparse.Namespace) -> int:
    contract = cn_contract.load_contract()
    limits = contract.limits
    started = time.monotonic()

    input_path = args.application.resolve()
    base = input_path.parent
    input_raw, declaration = read_json(input_path, limits["formalities_manifest_bytes"], "prepare 输入")
    if not isinstance(declaration, dict):
        raise OrchestrationError("prepare 输入顶层必须是对象")
    unknown = set(declaration) - ALLOWED_PREPARE_FIELDS
    if unknown:
        raise OrchestrationError("prepare 输入含未知字段：" + ", ".join(sorted(unknown)))
    if declaration.get("schema_version") != PREPARE_INPUT_SCHEMA:
        raise OrchestrationError(f"prepare 输入 schema_version 必须为 {PREPARE_INPUT_SCHEMA}")
    application_id = declaration.get("application_id")
    if not isinstance(application_id, str) or not application_id.strip():
        raise OrchestrationError("prepare 输入必须声明非空 application_id")

    paths = {
        key: resolve_under(base, declaration.get(key), f"prepare 输入的 {key}")
        for key in ("claims", "specification", "features", "formalities_manifest")
    }
    provenance_artifacts = build_provenance_artifacts(
        declaration.get("provenance_artifacts"), base, list(paths.values()) + [input_path], contract
    )
    reports = run_checkers(paths, contract)

    workspace = args.workspace.resolve()
    raw_directory = workspace / "raw"
    protected = [input_path, *paths.values(), *(Path(item["path"]) for item in provenance_artifacts)]

    input_artifacts = [
        make_artifact("prepare-input", input_path, input_raw, "application/json"),
        *(
            make_artifact(key, path, path.read_bytes(), "application/json" if path.suffix == ".json" else "text/plain")
            for key, path in sorted(paths.items())
        ),
    ]
    rule_sources: list[dict[str, Any]] = []
    seen_rules: set[str] = set()
    for report in reports.values():
        for item in report["rule_sources"]:
            if item["artifact_id"] not in seen_rules:
                seen_rules.add(item["artifact_id"])
                rule_sources.append(item)
    if len(input_artifacts) + len(provenance_artifacts) > limits["verifier_max_artifacts"]:
        raise ResourceLimitError("输入与 provenance artifact 总数超过上限")
    if len(rule_sources) > limits["verifier_max_rule_sources"]:
        raise ResourceLimitError("规则来源数超过上限")

    tool_identities = [report["tool_identity"] for report in reports.values()]
    orchestrator_sha = sha256_bytes(Path(__file__).resolve().read_bytes())
    tool_set = sorted(
        [(item["tool_id"], item["tool_sha256"]) for item in tool_identities] + [(TOOL_ID, orchestrator_sha)]
    )
    tool_set_sha256 = sha256_bytes(canonical_json(tool_set))

    raw_payloads = {
        review_type: json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        for review_type, report in reports.items()
    }
    raw_artifacts = [
        {"artifact_id": f"raw-{review_type}", "sha256": evidence_digest(report)}
        for review_type, report in sorted(reports.items())
    ]
    binding = {
        "input_set_sha256": collection_digest(input_artifacts),
        "provenance_set_sha256": collection_digest(provenance_artifacts),
        "rule_set_sha256": collection_digest(rule_sources),
        "tool_set_sha256": tool_set_sha256,
        "raw_report_set_sha256": collection_digest(raw_artifacts),
    }
    prepare_id = stable_id("P", application_id, *(binding[key] for key in sorted(binding)))

    manifest = {
        "schema_version": PREPARE_MANIFEST_SCHEMA,
        "jurisdiction": "CN",
        "legal_effect": contract.data["legal_effect"],
        "prepare_id": prepare_id,
        "application_id": application_id,
        "input_artifacts": input_artifacts,
        "provenance_artifacts": provenance_artifacts,
        "rule_sources": rule_sources,
        "tool_identity": {
            "tool_id": TOOL_ID,
            "tool_version": TOOL_VERSION,
            "tool_sha256": orchestrator_sha,
            "contract_schema_version": contract.schema_ids["contract"],
        },
        "checker_identities": sorted(tool_identities, key=lambda item: item["tool_id"]),
        "evidence_binding": binding,
        "raw_reports": {
            review_type: {
                "path": f"raw/{review_type}.json",
                "report_id": reports[review_type]["report_id"],
                "sha256": sha256_bytes(raw_payloads[review_type]),
            }
            for review_type in sorted(reports)
        },
        "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
    }

    template = build_semantic_template(contract, prepare_id, binding, provenance_artifacts)
    # 时限检查必须早于任何写盘：资源失败是工具错误，不得留下半成品工件。
    if time.monotonic() - started > limits["orchestration_deadline_seconds"]:
        raise ResourceLimitError("prepare 超过编排时限")

    for review_type, payload in raw_payloads.items():
        write_json_atomic(raw_directory / f"{review_type}.json", payload, protected)
    write_json_atomic(
        workspace / "prepare-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        protected,
    )
    write_json_atomic(
        workspace / "review-input-template.json",
        json.dumps(template, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        protected,
    )

    deterministic = any(
        item["status"] == "DETERMINISTIC_FAIL"
        for report in reports.values()
        for item in report["findings"]
    )
    print(f"prepare 完成：{prepare_id}", file=sys.stderr)
    return EXIT_DETERMINISTIC_FAIL if deterministic else EXIT_OK


# --------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------

def _validate_frozen_artifacts(
    artifacts: Any,
    label: str,
    expected_digest: str,
    contract,
    scope_base: Path | None = None,
) -> None:
    """复核 manifest 中工件的字段、字节、路径边界和集合哈希。"""

    if not isinstance(artifacts, list):
        raise OrchestrationError(f"{label}必须是工件数组")
    limits = contract.limits
    if len(artifacts) > limits["verifier_max_artifacts"]:
        raise ResourceLimitError(f"{label}工件数超过上限")
    seen_ids: set[str] = set()
    seen_paths: list[Path] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise OrchestrationError(f"{label}[{index}] 必须是对象")
        required = {"artifact_id", "path", "sha256", "byte_length", "media_type", "encoding"}
        if set(artifact) != required:
            raise OrchestrationError(f"{label}[{index}] 字段集合不符合 artifact 合同")
        artifact_id = artifact["artifact_id"]
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen_ids:
            raise OrchestrationError(f"{label}[{index}] artifact_id 无效或重复：{artifact_id!r}")
        seen_ids.add(artifact_id)
        path = Path(artifact["path"]).resolve()
        if scope_base is not None:
            try:
                path.relative_to(scope_base.resolve())
            except ValueError as exc:
                raise OrchestrationError(f"{label}[{index}] 越出输入目录：{path}") from exc
        if not path.is_file():
            raise OrchestrationError(f"{label}工件 {artifact_id} 已不可读取：{path}")
        if any(_same_file(path, existing) for existing in seen_paths):
            raise OrchestrationError(f"{label}工件 {artifact_id} 与其他工件指向同一文件：{path}")
        raw = path.read_bytes()
        if len(raw) != artifact["byte_length"]:
            raise OrchestrationError(
                f"{label}工件 {artifact_id} 的字节长度与声明不一致，冻结证据失效；必须重新运行 prepare"
            )
        if len(raw) > limits["verifier_max_single_artifact_bytes"]:
            raise ResourceLimitError(f"{label}工件 {artifact_id} 超过单工件字节上限")
        if raw.startswith(b"\xef\xbb\xbf"):
            raise OrchestrationError(f"{label}工件 {artifact_id} 必须是 UTF-8 无 BOM")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OrchestrationError(f"{label}工件 {artifact_id} 不是合法 UTF-8 文本：{exc}") from exc
        if sha256_bytes(raw) != artifact["sha256"]:
            raise OrchestrationError(f"{label}工件 {artifact_id} 字节已变化，冻结证据失效；必须重新运行 prepare")
        seen_paths.append(path)
    if collection_digest(artifacts) != expected_digest:
        raise OrchestrationError(f"{label}证据集合哈希与冻结清单不一致")


def load_frozen_state(workspace: Path, contract) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """重新读取 prepare 冻结的清单与原始报告，并逐字节核对新鲜度。"""

    limits = contract.limits
    _, manifest = read_json(workspace / "prepare-manifest.json", limits["max_report_output_bytes"], "prepare 清单")
    if manifest.get("schema_version") != PREPARE_MANIFEST_SCHEMA:
        raise OrchestrationError(f"prepare 清单 schema_version 必须为 {PREPARE_MANIFEST_SCHEMA}")

    declared = manifest.get("raw_reports", {})
    if sorted(declared) != sorted(REVIEW_TYPES):
        raise OrchestrationError(f"prepare 清单必须声明 {sorted(REVIEW_TYPES)} 三份原始报告")
    if len(declared) > limits["verifier_max_raw_reports"]:
        raise ResourceLimitError("原始报告数超过上限")

    reports: dict[str, dict[str, Any]] = {}
    for review_type, entry in sorted(declared.items()):
        path = resolve_under(workspace, entry["path"], f"{review_type} 原始报告路径")
        raw, report = read_json(path, limits["max_report_output_bytes"], f"{review_type} 原始报告")
        if sha256_bytes(raw) != entry["sha256"]:
            raise OrchestrationError(
                f"{review_type} 原始报告字节已变化，冻结证据失效；必须重新运行 prepare"
            )
        if report.get("report_id") != entry["report_id"]:
            raise OrchestrationError(f"{review_type} 原始报告 report_id 与冻结清单不一致")
        problems = contract.validate_raw_report(report, f"raw:{review_type}")
        if problems:
            raise OrchestrationError(f"{review_type} 原始报告不符合规范：" + "；".join(problems[:5]))
        reports[review_type] = report

    # 输入、provenance 和规则字节必须与冻结时一致，否则下游证据已经陈旧。
    binding = manifest.get("evidence_binding", {})
    _validate_frozen_artifacts(
        manifest.get("input_artifacts"), "输入", binding.get("input_set_sha256"), contract
    )
    _validate_frozen_artifacts(
        manifest.get("rule_sources"), "规则", binding.get("rule_set_sha256"), contract
    )

    has_provenance = "provenance_artifacts" in manifest
    has_provenance_hash = "provenance_set_sha256" in binding
    if has_provenance != has_provenance_hash:
        raise OrchestrationError(
            "prepare 清单的 provenance_artifacts 与 provenance_set_sha256 必须同时出现或同时省略"
        )
    if has_provenance:
        prepare_input = next(
            (item for item in manifest["input_artifacts"] if item.get("artifact_id") == "prepare-input"),
            None,
        )
        if not isinstance(prepare_input, dict):
            raise OrchestrationError("prepare 清单缺少 prepare-input 工件，无法确定 provenance 路径边界")
        _validate_frozen_artifacts(
            manifest.get("provenance_artifacts"),
            "provenance",
            binding.get("provenance_set_sha256"),
            contract,
            Path(prepare_input["path"]).resolve().parent,
        )
    return manifest, reports


def conserve(report: dict[str, Any], raw_report_sha256: str, contract) -> dict[str, Any]:
    """把一份原始报告守恒转换为专项报告：逐条保留，不合并、不降级、不丢弃。"""

    review_type = report["review_type"]
    findings = [
        {
            "finding_id": item["finding_id"],
            "origin": {"origin_raw_finding_id": item["finding_id"], "origin_raw_gap_id": None},
            "review_type": review_type,
            "rule_id": item["rule_id"],
            "dimension_id": contract.dimension_for_rule(item["rule_id"]),
            "target_id": item["target_id"],
            "location": item["location"],
            "status": item["status"],
            "evidence": item["evidence"],
            "problem": item["problem"],
            "remedy": item["remedy"],
            "manual_review_required": item["manual_review_required"],
        }
        for item in report["findings"]
    ]
    gaps = [
        {
            "gap_id": item["gap_id"],
            "origin": {"origin_raw_finding_id": None, "origin_raw_gap_id": item["gap_id"]},
            "review_type": review_type,
            "rule_id": item["rule_id"],
            "dimension_id": contract.dimension_for_rule(item["rule_id"]),
            "target_id": item["target_id"],
            "category": item["category"],
            "reason": item["reason"],
            "evidence": item["evidence"],
            "blocks_assessment": item["blocks_assessment"],
        }
        for item in report["gaps"]
    ]
    return {
        "schema_version": contract.schema_ids["subreport"],
        "jurisdiction": contract.data["jurisdiction"],
        "legal_effect": contract.data["legal_effect"],
        "review_type": review_type,
        "subreport_id": stable_id("S", review_type, report["report_id"]),
        "raw_report_id": report["report_id"],
        "raw_report_sha256": raw_report_sha256,
        "findings": findings,
        "gaps": gaps,
    }


def read_semantic_input(path: Path, manifest: dict[str, Any], contract) -> dict[str, Any]:
    """读取独立语义审查输入并核对其与冻结证据的新鲜度。"""

    _, payload = read_json(path, contract.limits["max_report_output_bytes"], "语义审查输入")
    if not isinstance(payload, dict):
        raise OrchestrationError("语义审查输入顶层必须是对象")

    expected_keys = set(contract.data["exact_fields"]["review_input"])
    actual_keys = set(payload)
    if expected_keys != actual_keys:
        extra = sorted(actual_keys - expected_keys)
        missing = sorted(expected_keys - actual_keys)
        raise OrchestrationError(f"review-input 顶层字段与规范不一致：多出 {extra} / 缺少 {missing}")

    if payload.get("schema_version") != SEMANTIC_INPUT_SCHEMA:
        raise OrchestrationError(f"语义审查输入 schema_version 必须为 {SEMANTIC_INPUT_SCHEMA}")
    if payload.get("prepare_id") != manifest["prepare_id"]:
        raise OrchestrationError("语义审查输入绑定的 prepare_id 与当前冻结证据不一致")
    if payload.get("evidence_binding") != manifest["evidence_binding"]:
        raise OrchestrationError("语义审查输入绑定的证据哈希已陈旧；必须基于当前 prepare 重新审查")
    manifest_has_provenance = "provenance_artifacts" in manifest
    payload_has_provenance = "provenance_artifacts" in payload
    if manifest_has_provenance != payload_has_provenance:
        raise OrchestrationError(
            "语义审查输入与 prepare 清单的 provenance_artifacts 出现状态不一致"
        )
    if manifest_has_provenance and payload.get("provenance_artifacts") != manifest.get("provenance_artifacts"):
        raise OrchestrationError(
            "语义审查输入的 provenance_artifacts 与 prepare 清单不一致"
        )
    for key in ("assessments", "semantic_gaps"):
        if not isinstance(payload.get(key), list):
            raise OrchestrationError(f"语义审查输入的 {key} 必须是数组")
    return payload


def build_assessments(
    semantic_input: dict[str, Any], subreports: list[dict[str, Any]], contract
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """构造 41 维原子评估：语义状态来自审查者，ID 归属由工具机械并入。"""

    by_dimension_findings: dict[str, list[str]] = {}
    by_dimension_gaps: dict[str, list[str]] = {}
    for subreport in subreports:
        for item in subreport["findings"]:
            by_dimension_findings.setdefault(item["dimension_id"], []).append(item["finding_id"])
        for item in subreport["gaps"]:
            by_dimension_gaps.setdefault(item["dimension_id"], []).append(item["gap_id"])

    semantic_gaps = semantic_input["semantic_gaps"]
    semantic_gap_ids = [item["gap_id"] for item in semantic_gaps]
    if len(semantic_gap_ids) != len(set(semantic_gap_ids)):
        raise OrchestrationError("语义审查输入的 gap_id 必须唯一")
    for item in semantic_gaps:
        by_dimension_gaps.setdefault(item["dimension_id"], []).append(item["gap_id"])

    declared = {}
    for item in semantic_input["assessments"]:
        rule_id = item.get("rule_id")
        if rule_id in declared:
            raise OrchestrationError(f"语义审查输入对维度 {rule_id} 重复评估")
        declared[rule_id] = item
    unknown = sorted(set(declared) - set(contract.dimension_ids))
    if unknown:
        raise OrchestrationError(f"语义审查输入出现规范未定义的维度：{unknown}")

    assessments: list[dict[str, Any]] = []
    for dimension_id in contract.dimension_ids:
        provided = declared.get(dimension_id)
        state = provided if provided is not None else {**json.loads(json.dumps(UNASSESSED_STATE)), "target_id": "application"}
        for key in ("coverage", "result", "severity", "evidence"):
            if key not in state:
                raise OrchestrationError(f"维度 {dimension_id} 的语义评估缺少字段 {key}")
        assessment = {
            "assessment_id": f"A-{dimension_id}",
            "rule_id": dimension_id,
            "target_id": state.get("target_id", "application"),
            "coverage": state["coverage"],
            "result": state["result"],
            "evidence": state["evidence"],
            "severity": state["severity"],
            # 原始 finding/gap 由工具机械并入，审查者无法通过省略把它们清掉。
            "finding_ids": sorted(set(by_dimension_findings.get(dimension_id, [])) | set(state.get("finding_ids", []))),
            "gap_ids": sorted(set(by_dimension_gaps.get(dimension_id, [])) | set(state.get("gap_ids", []))),
        }
        problems = contract.validate_atomic_assessment(assessment, f"assessments.{dimension_id}")
        if problems:
            raise OrchestrationError(
                f"维度 {dimension_id} 的评估违反规范状态不变量：" + "；".join(problems[:3])
            )
        assessments.append(assessment)
    return assessments, semantic_gaps


def command_finalize(args: argparse.Namespace) -> int:
    contract = cn_contract.load_contract()
    started = time.monotonic()
    workspace = args.workspace.resolve()
    manifest, reports = load_frozen_state(workspace, contract)
    semantic_input = read_semantic_input(args.review_input.resolve(), manifest, contract)

    # 与证据绑定同源：专项报告绑定原始报告的证据摘要，字节级新鲜度已在 load_frozen_state 校验。
    subreports = [
        conserve(reports[review_type], evidence_digest(reports[review_type]), contract)
        for review_type in sorted(reports)
    ]
    assessments, semantic_gaps = build_assessments(semantic_input, subreports, contract)

    bundle = {
        "schema_version": contract.schema_ids["bundle"],
        "jurisdiction": contract.data["jurisdiction"],
        "legal_effect": contract.data["legal_effect"],
        "bundle_id": stable_id("B", manifest["prepare_id"], canonical_json(assessments).hex()[:32]),
        "prepare_id": manifest["prepare_id"],
        "input_artifacts": manifest["input_artifacts"],
        "rule_sources": manifest["rule_sources"],
        "tool_identity": manifest["tool_identity"],
        "evidence_binding": manifest["evidence_binding"],
        "resource_usage": {
            "input_bytes_total": sum(item["byte_length"] for item in manifest["input_artifacts"]),
            "output_bytes": 0,
            "finding_count": sum(len(item["findings"]) for item in subreports),
            "gap_count": sum(len(item["gaps"]) for item in subreports) + len(semantic_gaps),
            "check_count": sum(len(report["checks_performed"]) for report in reports.values()),
            "elapsed_milliseconds": 0,
        },
        "subreports": subreports,
        "assessments": assessments,
        "semantic_gaps": semantic_gaps,
    }
    if "provenance_artifacts" in manifest:
        bundle["provenance_artifacts"] = manifest["provenance_artifacts"]
        # 新 manifest 已由 prepare 生成该绑定；旧 manifest 无此字段时保持 v2 兼容。
        bundle["evidence_binding"]["provenance_set_sha256"] = manifest["evidence_binding"]["provenance_set_sha256"]

    problems = contract.validate_bundle(bundle)
    problems += contract.check_finding_conservation(reports, bundle)
    if problems:
        raise OrchestrationError("bundle 不符合 CN v2 规范或未通过守恒检查：" + "；".join(problems[:5]))

    bundle["resource_usage"]["elapsed_milliseconds"] = int((time.monotonic() - started) * 1000)
    payload = b""
    for _ in range(4):
        payload = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        if len(payload) > contract.limits["max_report_output_bytes"]:
            raise ResourceLimitError("bundle 输出超过上限")
        if bundle["resource_usage"]["output_bytes"] == len(payload):
            break
        bundle["resource_usage"]["output_bytes"] = len(payload)

    # 时限检查必须早于写盘：资源失败是工具错误，不得留下 bundle。
    if time.monotonic() - started > contract.limits["orchestration_deadline_seconds"]:
        raise ResourceLimitError("finalize 超过编排时限")
    protected = [Path(item["path"]) for item in manifest["input_artifacts"]]
    protected += [Path(item["path"]) for item in manifest.get("provenance_artifacts", [])]
    protected.append(args.review_input.resolve())
    write_json_atomic(args.output.resolve(), payload, protected)

    deterministic = any(
        item["status"] == "DETERMINISTIC_FAIL"
        for subreport in subreports
        for item in subreport["findings"]
    )
    print(f"finalize 完成：{bundle['bundle_id']}", file=sys.stderr)
    return EXIT_DETERMINISTIC_FAIL if deterministic else EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中国发明专利综合审查 CN v2 编排器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="冻结证据并运行三个真实检查器")
    prepare.add_argument("--application", required=True, type=Path, help="prepare 输入 JSON")
    prepare.add_argument("--workspace", required=True, type=Path, help="工作目录，写入原始报告与语义模板")
    prepare.set_defaults(handler=command_prepare)

    finalize = subparsers.add_parser("finalize", help="守恒转换原始结果并构造 bundle")
    finalize.add_argument("--workspace", required=True, type=Path, help="prepare 使用过的工作目录")
    finalize.add_argument("--review-input", required=True, type=Path, help="已完成的独立语义审查输入")
    finalize.add_argument("--output", required=True, type=Path, help="bundle 输出路径")
    finalize.set_defaults(handler=command_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ResourceLimitError as exc:
        print(f"编排资源失败：{exc}", file=sys.stderr)
        return EXIT_RESOURCE_ERROR
    except cn_contract.ContractError as exc:
        print(f"规范错误：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except (OrchestrationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"编排失败：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
