#!/usr/bin/env python3
"""CN v2 审查规范的机读加载与一致性校验。

设计前提：`cn-review-contract-v2.json` 是唯一事实来源。字段集合、枚举绑定、
ID 完整性、状态不变量、聚合与处置全部由规范数据驱动，代码里不再另写一份
规则副本。规范新增了不变量或处置分支而本模块没有对应实现时，加载即失败，
避免"规范写了但没人校验"这类静默漏检。

本模块只依赖标准库，不发起网络请求、不加载模型、不读取索引。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "references" / "cn-review-contract-v2.json"

# 递归校验的安全深度上限，防止畸形规范造成无界递归。
_MAX_VALIDATION_DEPTH = 32


class ContractError(Exception):
    """规范本身不可用或与实现不一致；属于工具错误，不得转为法律 finding。"""


# --------------------------------------------------------------------------
# 五轴状态不变量：逐条对应规范 state_invariants 的 id
# --------------------------------------------------------------------------

def _inv_not_applicable_pair(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if (coverage == "NOT_APPLICABLE") != (result == "NOT_APPLICABLE"):
        return "coverage=NOT_APPLICABLE 与 result=NOT_APPLICABLE 必须同时成立"
    return None


def _inv_none_requires_missing(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if coverage == "NONE" and (result, mode, sufficiency) != ("INCONCLUSIVE", "NONE", "MISSING"):
        return "coverage=NONE 要求 result=INCONCLUSIVE 且 evidence 为 NONE/MISSING"
    return None


def _inv_partial_cannot_clear(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if coverage == "PARTIAL" and result not in {"ISSUE_FOUND", "INCONCLUSIVE"}:
        return "coverage=PARTIAL 只允许 ISSUE_FOUND 或 INCONCLUSIVE"
    return None


def _inv_none_mode_iff_missing(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if (mode == "NONE") != (sufficiency == "MISSING"):
        return "evidence.mode=NONE 与 evidence.sufficiency=MISSING 必须同时成立"
    return None


def _inv_heuristic_is_inconclusive(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if mode == "HEURISTIC" and (sufficiency, result) != ("LIMITED", "INCONCLUSIVE"):
        return "evidence.mode=HEURISTIC 要求 sufficiency=LIMITED 且 result=INCONCLUSIVE"
    return None


def _inv_limited_or_missing_is_inconclusive(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if sufficiency in {"LIMITED", "MISSING"} and result != "INCONCLUSIVE":
        return "evidence.sufficiency=LIMITED/MISSING 要求 result=INCONCLUSIVE"
    return None


def _inv_no_issue_requires_full(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if result == "NO_ISSUE_FOUND" and not (
        coverage == "FULL"
        and sufficiency == "ADEQUATE_FOR_SCOPED_ASSESSMENT"
        and mode not in {"HEURISTIC", "NONE"}
        and severity == "NONE"
    ):
        return "NO_ISSUE_FOUND 要求 FULL 覆盖、充分证据、非启发式模式且 severity=NONE"
    return None


def _inv_issue_requires_evidence_and_severity(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if result == "ISSUE_FOUND" and not (
        coverage in {"FULL", "PARTIAL"}
        and sufficiency == "ADEQUATE_FOR_SCOPED_ASSESSMENT"
        and mode not in {"HEURISTIC", "NONE"}
        and severity != "NONE"
    ):
        return "ISSUE_FOUND 要求 FULL/PARTIAL 覆盖、充分证据、非启发式模式且 severity 非 NONE"
    return None


def _inv_inconclusive_requires_gap(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if result == "INCONCLUSIVE" and severity != "NONE":
        return "INCONCLUSIVE 要求 severity=NONE"
    return None


def _inv_not_applicable_nonpunitive(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if result == "NOT_APPLICABLE" and severity != "NONE":
        return "NOT_APPLICABLE 要求 severity=NONE"
    return None


def _inv_atomic_mixed_forbidden(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> str | None:
    if result == "MIXED":
        return "MIXED 不允许出现在原子评估"
    return None


# 键必须与规范 state_invariants[].id 完全一致，缺一即加载失败。
_AXIS_INVARIANTS: dict[str, Callable[[str, str, str, str, str], str | None]] = {
    "coverage_not_applicable_iff_result_not_applicable": _inv_not_applicable_pair,
    "none_requires_missing_evidence": _inv_none_requires_missing,
    "partial_cannot_clear": _inv_partial_cannot_clear,
    "none_mode_iff_missing": _inv_none_mode_iff_missing,
    "heuristic_is_inconclusive": _inv_heuristic_is_inconclusive,
    "limited_or_missing_is_inconclusive": _inv_limited_or_missing_is_inconclusive,
    "no_issue_requires_full_adequate_nonheuristic": _inv_no_issue_requires_full,
    "issue_requires_evidence_and_severity": _inv_issue_requires_evidence_and_severity,
    "inconclusive_requires_gap": _inv_inconclusive_requires_gap,
    "not_applicable_nonpunitive": _inv_not_applicable_nonpunitive,
    "atomic_mixed_forbidden": _inv_atomic_mixed_forbidden,
}

# 五轴之外、依赖 finding_ids/gap_ids 的补充条件，按同一 invariant id 归属。
_ID_INVARIANTS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "no_issue_requires_full_adequate_nonheuristic": lambda item: (
        "NO_ISSUE_FOUND 不得携带 finding_ids 或 gap_ids"
        if item["result"] == "NO_ISSUE_FOUND" and (item["finding_ids"] or item["gap_ids"])
        else None
    ),
    "issue_requires_evidence_and_severity": lambda item: (
        "ISSUE_FOUND 至少需要一个 finding_id"
        if item["result"] == "ISSUE_FOUND" and not item["finding_ids"]
        else None
    ),
    "inconclusive_requires_gap": lambda item: (
        "INCONCLUSIVE 至少需要一个 gap_id"
        if item["result"] == "INCONCLUSIVE" and not item["gap_ids"]
        else None
    ),
    "not_applicable_nonpunitive": lambda item: (
        "NOT_APPLICABLE 不得携带 finding_ids"
        if item["result"] == "NOT_APPLICABLE" and item["finding_ids"]
        else None
    ),
}


# --------------------------------------------------------------------------
# 处置派生：键为规范 disposition[].when
# --------------------------------------------------------------------------

_DISPOSITION_RULES: dict[str, Callable[[list[dict[str, Any]]], bool]] = {
    "all_required_assessments_have_coverage_NONE": lambda items: bool(items) and all(
        item["coverage"] == "NONE" for item in items
    ),
    "any_ISSUE_FOUND_with_severity_BLOCKER": lambda items: any(
        item["result"] == "ISSUE_FOUND" and item["severity"] == "BLOCKER" for item in items
    ),
    "any_INCONCLUSIVE_or_gap_or_LIMITED_or_MISSING_evidence": lambda items: any(
        item["result"] == "INCONCLUSIVE"
        or item["gap_ids"]
        or item["evidence"]["sufficiency"] in {"LIMITED", "MISSING"}
        for item in items
    ),
    "any_nonblocking_ISSUE_FOUND": lambda items: any(item["result"] == "ISSUE_FOUND" for item in items),
    "otherwise": lambda items: True,
}


class Contract:
    """机读 CN v2 规范；所有校验都以规范数据为准。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self._assert_implementation_covers_contract()

    # -- 加载 ---------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Contract":
        contract_path = Path(path) if path is not None else DEFAULT_CONTRACT_PATH
        try:
            raw = contract_path.read_bytes()
        except OSError as exc:
            raise ContractError(f"无法读取规范文件 {contract_path}：{exc}") from exc
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ContractError("规范文件必须是 UTF-8 无 BOM")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"规范文件不是合法 UTF-8 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ContractError("规范顶层必须是 JSON 对象")
        return cls(data)

    def _assert_implementation_covers_contract(self) -> None:
        """规范声明的每条不变量和处置分支都必须有实现，否则拒绝加载。"""

        declared = [item["id"] for item in self.data.get("state_invariants", [])]
        if set(declared) != set(_AXIS_INVARIANTS):
            missing = sorted(set(declared) - set(_AXIS_INVARIANTS))
            extra = sorted(set(_AXIS_INVARIANTS) - set(declared))
            raise ContractError(f"状态不变量实现与规范不一致；未实现={missing}，多余实现={extra}")
        if set(_ID_INVARIANTS) - set(_AXIS_INVARIANTS):
            raise ContractError("ID 级不变量必须归属于已声明的不变量 id")
        declared_when = [item["when"] for item in self.data.get("disposition", [])]
        if set(declared_when) != set(_DISPOSITION_RULES):
            missing = sorted(set(declared_when) - set(_DISPOSITION_RULES))
            extra = sorted(set(_DISPOSITION_RULES) - set(declared_when))
            raise ContractError(f"处置规则实现与规范不一致；未实现={missing}，多余实现={extra}")
        priorities = [item["priority"] for item in self.data["disposition"]]
        if priorities != sorted(priorities) or len(set(priorities)) != len(priorities):
            raise ContractError("处置优先级必须唯一且按升序声明")
        dimension_ids = {item["id"] for item in self.data.get("dimensions", [])}
        unknown = sorted(set(self.data.get("rule_dimension_map", {}).values()) - dimension_ids)
        if unknown:
            raise ContractError(f"rule_dimension_map 指向不存在的维度：{unknown}")
        tool_only = self.data.get("tool_only_rules", [])
        if not isinstance(tool_only, list) or any(not isinstance(item, str) or not item for item in tool_only):
            raise ContractError("tool_only_rules 必须是非空字符串数组")
        overlap = sorted(set(tool_only) & set(self.data.get("rule_dimension_map", {})))
        if overlap:
            raise ContractError(f"tool_only_rules 与 rule_dimension_map 不得重叠：{overlap}")
        optional_fields = self.data.get("optional_fields", {})
        if not isinstance(optional_fields, dict):
            raise ContractError("optional_fields 必须是对象")
        for kind, fields in optional_fields.items():
            if kind not in self.data.get("exact_fields", {}):
                raise ContractError(f"optional_fields 指向未定义的字段集合：{kind}")
            if not isinstance(fields, list) or any(not isinstance(item, str) or not item for item in fields):
                raise ContractError(f"optional_fields.{kind} 必须是非空字符串数组")
            unknown_optional = sorted(set(fields) - set(self.data["exact_fields"][kind]))
            if unknown_optional:
                raise ContractError(
                    f"optional_fields.{kind} 含未列入 exact_fields 的字段：{unknown_optional}"
                )

    # -- 便捷访问 -----------------------------------------------------------

    @property
    def schema_ids(self) -> dict[str, str]:
        return self.data["schema_ids"]

    @property
    def exact_fields(self) -> dict[str, list[str]]:
        return self.data["exact_fields"]

    @property
    def limits(self) -> dict[str, Any]:
        return self.data["resource_limits"]

    @property
    def dimension_ids(self) -> list[str]:
        return [item["id"] for item in self.data["dimensions"]]

    @property
    def rule_dimension_map(self) -> dict[str, str]:
        return self.data["rule_dimension_map"]

    @property
    def tool_only_rules(self) -> set[str]:
        return set(self.data.get("tool_only_rules", []))

    def dimension_for_rule(self, rule_id: str) -> str:
        """把检查器 rule_id 映射到唯一法律维度；缺映射是规范错误，不允许猜测归属。

        工具规则（输出保护、资源上限、verifier 自身规则）列在 tool_only_rules，
        不得伪装成法律维度。
        """

        if rule_id in self.tool_only_rules:
            raise ContractError(f"rule_id 属于 tool_only_rules，不得映射到法律维度：{rule_id}")
        try:
            return self.rule_dimension_map[rule_id]
        except KeyError as exc:
            raise ContractError(f"规范 rule_dimension_map 缺少 rule_id 的维度归属：{rule_id}") from exc

    def dimensions_in_group(self, group: str) -> list[str]:
        return [item["id"] for item in self.data["dimensions"] if item["group"] == group]

    # -- 通用结构校验 -------------------------------------------------------

    def _resolve_target(self, target: str) -> Any:
        """把 field_relationships 的目标字符串解析为规范中的实际值。"""

        node: Any = self.data
        for part in target.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ContractError(f"规范缺少 field_relationships 目标：{target}")
            node = node[part]
        return node

    def _check_exact_fields(self, obj: dict[str, Any], kind: str, path: str) -> list[str]:
        allowed = self.exact_fields.get(kind)
        if allowed is None:
            return []
        policy = self.data["exact_field_policy"]
        optional = set(self.data.get("optional_fields", {}).get(kind, []))
        problems: list[str] = []
        actual = set(obj)
        expected = set(allowed)
        if policy.get("reject_missing_fields", True):
            for name in sorted((expected - actual) - optional):
                problems.append(f"{path}: 缺少规范要求的字段 {name}")
        if policy.get("reject_unknown_fields", True):
            for name in sorted(actual - expected):
                problems.append(f"{path}: 出现规范未定义的字段 {name}")
        return problems

    def _check_enums(self, obj: dict[str, Any], kind: str, path: str) -> list[str]:
        problems: list[str] = []
        for binding, enum_name in self.data.get("enum_bindings", {}).items():
            owner, field = binding.split(".", 1)
            if owner != kind or field not in obj:
                continue
            allowed = self.data["enums"].get(enum_name)
            if allowed is None:
                raise ContractError(f"规范 enum_bindings 指向不存在的枚举：{enum_name}")
            try:
                allowed_value = obj[field] in allowed
            except TypeError:
                # JSON 数组/对象不可哈希时也要返回合同错误，而不是让验证器崩溃。
                allowed_value = False
            if not allowed_value:
                problems.append(f"{path}.{field}: 值 {obj[field]!r} 不在枚举 {enum_name} 中")
        return problems

    def _validate_object(self, obj: Any, kind: str, path: str, depth: int = 0) -> list[str]:
        """按规范的 exact_fields / field_relationships / enum_bindings 递归校验。"""

        if depth > _MAX_VALIDATION_DEPTH:
            return [f"{path}: 校验深度超过 {_MAX_VALIDATION_DEPTH}"]
        if not isinstance(obj, dict):
            return [f"{path}: 必须是 JSON 对象"]
        problems = self._check_exact_fields(obj, kind, path)
        problems += self._check_enums(obj, kind, path)
        for relation, target in self.data["field_relationships"].items():
            owner, field = relation.split(".", 1)
            if owner != kind:
                continue
            is_list = field.endswith("[]")
            name = field[:-2] if is_list else field
            if name not in obj:
                continue
            value = obj[name]
            if not target.startswith("exact_fields."):
                expected = self._resolve_target(target)
                if value != expected:
                    problems.append(f"{path}.{name}: 必须等于规范 {target} 的值 {expected!r}，实际为 {value!r}")
                continue
            child_kind = target.split(".", 1)[1]
            if is_list:
                if not isinstance(value, list):
                    problems.append(f"{path}.{name}: 必须是数组")
                    continue
                for index, child in enumerate(value):
                    problems += self._validate_object(child, child_kind, f"{path}.{name}[{index}]", depth + 1)
            else:
                problems += self._validate_object(value, child_kind, f"{path}.{name}", depth + 1)
        return problems

    # -- 禁用结论字段 -------------------------------------------------------

    def prohibited_field_paths(self, obj: Any, path: str = "$") -> list[str]:
        """深度扫描生产者禁止出现的总体结论字段。"""

        banned = set(self.data["prohibited_producer_fields"])
        found: list[str] = []
        stack: list[tuple[Any, str, int]] = [(obj, path, 0)]
        while stack:
            node, node_path, depth = stack.pop()
            if depth > self.limits["json_max_depth"]:
                found.append(f"{node_path}: JSON 嵌套深度超过 {self.limits['json_max_depth']}")
                continue
            if isinstance(node, dict):
                for key, value in node.items():
                    child_path = f"{node_path}.{key}"
                    if key in banned:
                        found.append(f"{child_path}: 禁止的生产者结论字段 {key}")
                    stack.append((value, child_path, depth + 1))
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    stack.append((value, f"{node_path}[{index}]", depth + 1))
        return sorted(found)

    # -- 原始报告校验 -------------------------------------------------------

    def validate_raw_report(self, report: Any, path: str = "raw_report") -> list[str]:
        """校验一份原始检查报告是否符合 CN v2 规范。返回违规描述列表。"""

        if not isinstance(report, dict):
            return [f"{path}: 必须是 JSON 对象"]
        problems = self._validate_object(report, "raw_report", path)
        problems += self.prohibited_field_paths(report, path)
        problems += self._check_raw_report_integrity(report, path)
        return problems

    def _check_raw_report_integrity(self, report: dict[str, Any], path: str) -> list[str]:
        problems: list[str] = []
        checks = report.get("checks_performed")
        findings = report.get("findings")
        gaps = report.get("gaps")
        if not all(isinstance(item, list) for item in (checks, findings, gaps)):
            return [f"{path}: checks_performed/findings/gaps 必须同时是数组"]

        # 1. 规范声明的 ID 在报告内唯一。
        id_fields = {
            "check_id": checks,
            "finding_id": findings,
            "gap_id": gaps,
        }
        for id_field in self.data["id_integrity"]["unique_within_raw_report"]:
            items = id_fields.get(id_field, [])
            seen: set[str] = set()
            for item in items:
                if not isinstance(item, dict):
                    continue
                value = item.get(id_field)
                if value in seen:
                    problems.append(f"{path}: {id_field} 重复：{value}")
                seen.add(value)

        # 2. finding/gap 的 check_id 必须恰好命中一个 check，且双向一致。
        check_ids = [item.get("check_id") for item in checks if isinstance(item, dict)]
        check_id_set = set(check_ids)
        for label, items, id_field, link_field in (
            ("finding", findings, "finding_id", "finding_ids"),
            ("gap", gaps, "gap_id", "gap_ids"),
        ):
            owned: dict[str, set[str]] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                owner = item.get("check_id")
                if owner not in check_id_set:
                    problems.append(f"{path}: {label} {item.get(id_field)} 的 check_id {owner!r} 未命中任何 check")
                    continue
                owned.setdefault(owner, set()).add(item.get(id_field))
            for check in checks:
                if not isinstance(check, dict):
                    continue
                declared = check.get(link_field)
                if not isinstance(declared, list):
                    continue
                actual = owned.get(check.get("check_id"), set())
                if set(declared) != actual:
                    problems.append(
                        f"{path}: check {check.get('check_id')} 声明的 {link_field}={sorted(declared)} "
                        f"与实际归属的 {sorted(actual)} 不一致"
                    )

        # 3. 证据必须指向本报告已声明的 artifact，杜绝悬空来源映射。
        artifact_ids = {
            item.get("artifact_id")
            for key in ("input_artifacts", "rule_sources")
            for item in report.get(key, [])
            if isinstance(item, dict)
        }
        for label, items in (("finding", findings), ("gap", gaps)):
            for item in items:
                if not isinstance(item, dict):
                    continue
                evidence = item.get("evidence")
                entries = evidence if isinstance(evidence, list) else []
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("artifact_id") not in artifact_ids:
                        problems.append(
                            f"{path}: {label} {item.get('finding_id') or item.get('gap_id')} "
                            f"的证据指向未声明的 artifact_id {entry.get('artifact_id')!r}"
                        )

        # 4. resource_usage 的计数必须与实际集合一致。
        usage = report.get("resource_usage")
        if isinstance(usage, dict):
            for field, actual in (("finding_count", len(findings)), ("gap_count", len(gaps)), ("check_count", len(checks))):
                if usage.get(field) != actual:
                    problems.append(f"{path}.resource_usage.{field}: 声明 {usage.get(field)}，实际 {actual}")

        # 5. 报告声明的资源上限不得与规范冲突，且实际规模不得越限。
        declared_limits = report.get("resource_limits")
        if isinstance(declared_limits, dict):
            for key, value in sorted(declared_limits.items()):
                if key not in self.limits:
                    problems.append(f"{path}.resource_limits: 规范未定义的上限项 {key}")
                elif self.limits[key] != value:
                    problems.append(f"{path}.resource_limits.{key}: 声明 {value!r} 与规范 {self.limits[key]!r} 不一致")
        for field, actual, limit_key in (
            ("findings", len(findings), "max_findings"),
            ("gaps", len(gaps), "max_gaps"),
            ("checks_performed", len(checks), "max_checks"),
        ):
            if actual > self.limits[limit_key]:
                problems.append(f"{path}.{field}: 数量 {actual} 超过规范上限 {self.limits[limit_key]}")
        return problems

    # -- 原子评估校验 -------------------------------------------------------

    def state_axis_errors(self, coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> list[str]:
        """对五轴状态组合逐条应用规范不变量，返回违反的说明。"""

        errors: list[str] = []
        for invariant_id in (item["id"] for item in self.data["state_invariants"]):
            message = _AXIS_INVARIANTS[invariant_id](coverage, result, mode, sufficiency, severity)
            if message:
                errors.append(f"{invariant_id}: {message}")
        return errors

    def legal_state_combinations(self) -> list[tuple[str, str, str, str, str]]:
        """枚举全部合法五轴组合；用于锁定规范状态空间不被悄悄放宽。"""

        enums = self.data["enums"]
        legal: list[tuple[str, str, str, str, str]] = []
        for coverage in enums["coverage"]:
            for result in enums["result_atomic"]:
                for mode in enums["evidence_mode"]:
                    for sufficiency in enums["evidence_sufficiency"]:
                        for severity in enums["severity"]:
                            if not self.state_axis_errors(coverage, result, mode, sufficiency, severity):
                                legal.append((coverage, result, mode, sufficiency, severity))
        return legal

    def validate_atomic_assessment(self, item: Any, path: str = "atomic_assessment") -> list[str]:
        """校验单条原子评估的字段、枚举和全部状态不变量。"""

        problems = self._validate_object(item, "atomic_assessment", path)
        if problems:
            return problems
        evidence = item["evidence"]
        for message in self.state_axis_errors(
            item["coverage"], item["result"], evidence["mode"], evidence["sufficiency"], item["severity"]
        ):
            problems.append(f"{path}: {message}")
        for invariant_id, rule in _ID_INVARIANTS.items():
            message = rule(item)
            if message:
                problems.append(f"{path}: {invariant_id}: {message}")
        for field in ("finding_ids", "gap_ids"):
            if not isinstance(item[field], list) or any(not isinstance(value, str) for value in item[field]):
                problems.append(f"{path}.{field}: 必须是字符串数组")
        return problems

    # -- Bundle 与守恒校验 ---------------------------------------------------

    def validate_bundle(self, bundle: Any, path: str = "bundle") -> list[str]:
        """校验 bundle 的结构、枚举、原子状态和维度覆盖。"""

        if not isinstance(bundle, dict):
            return [f"{path}: 必须是 JSON 对象"]
        problems = self._validate_object(bundle, "bundle", path)
        problems += self.prohibited_field_paths(bundle, path)
        if problems:
            return problems

        # provenance_artifacts 是可选的向后兼容扩展；一旦出现，必须与独立集合哈希成对出现。
        has_provenance = "provenance_artifacts" in bundle
        has_provenance_hash = "provenance_set_sha256" in bundle.get("evidence_binding", {})
        if has_provenance != has_provenance_hash:
            problems.append(
                f"{path}: provenance_artifacts 与 evidence_binding.provenance_set_sha256 必须同时出现或同时省略"
            )
        if has_provenance and not isinstance(bundle.get("provenance_artifacts"), list):
            problems.append(f"{path}.provenance_artifacts: 必须是数组")

        # 三类工件的 ID 必须全局唯一，避免语义证据引用出现歧义。
        collections = [bundle.get("input_artifacts", []), bundle.get("rule_sources", [])]
        if isinstance(bundle.get("provenance_artifacts"), list):
            collections.append(bundle["provenance_artifacts"])
        seen_artifacts: set[Any] = set()
        for collection in collections:
            if not isinstance(collection, list):
                continue
            for artifact in collection:
                if not isinstance(artifact, dict):
                    continue
                artifact_id = artifact.get("artifact_id")
                if not isinstance(artifact_id, str) or not artifact_id:
                    problems.append(
                        f"{path}: 工件 artifact_id 必须是非空字符串，实际为 {artifact_id!r}"
                    )
                    continue
                if artifact_id in seen_artifacts:
                    problems.append(f"{path}: 工件 artifact_id 重复：{artifact_id}")
                seen_artifacts.add(artifact_id)

        provenance_limit = self.data.get("resource_limits", {}).get("provenance_max_artifacts")
        if has_provenance and isinstance(provenance_limit, int) \
                and len(bundle["provenance_artifacts"]) > provenance_limit:
            problems.append(
                f"{path}.provenance_artifacts: 数量 {len(bundle['provenance_artifacts'])} "
                f"超过规范上限 {provenance_limit}"
            )

        for index, assessment in enumerate(bundle["assessments"]):
            problems += self.validate_atomic_assessment(assessment, f"{path}.assessments[{index}]")

        # 41 个维度必须恰好各一条原子评估，条件维度不得静默消失。
        assessed = [item["rule_id"] for item in bundle["assessments"]]
        expected = set(self.dimension_ids)
        duplicates = sorted({value for value in assessed if assessed.count(value) > 1})
        if duplicates:
            problems.append(f"{path}.assessments: 维度重复评估：{duplicates}")
        missing = sorted(expected - set(assessed))
        if missing:
            problems.append(f"{path}.assessments: 缺少维度评估：{missing}")
        unknown = sorted(set(assessed) - expected)
        if unknown:
            problems.append(f"{path}.assessments: 出现规范未定义的维度：{unknown}")

        # 评估引用的 finding/gap 必须在 bundle 内真实存在。
        available_findings = {
            item["finding_id"] for subreport in bundle["subreports"] for item in subreport["findings"]
        }
        available_gaps = {
            item["gap_id"] for subreport in bundle["subreports"] for item in subreport["gaps"]
        } | {item["gap_id"] for item in bundle["semantic_gaps"]}
        for index, assessment in enumerate(bundle["assessments"]):
            for value in assessment.get("finding_ids", []):
                if value not in available_findings:
                    problems.append(f"{path}.assessments[{index}]: 引用了不存在的 finding_id {value}")
            for value in assessment.get("gap_ids", []):
                if value not in available_gaps:
                    problems.append(f"{path}.assessments[{index}]: 引用了不存在的 gap_id {value}")

        # 三份必需的专项报告缺一不可，且每种审查类型只能出现一次。
        required = self.data["finding_conservation"]["required_raw_reports"]
        present = [item["review_type"] for item in bundle["subreports"]]
        if sorted(present) != sorted(required):
            problems.append(f"{path}.subreports: 必须恰好包含 {sorted(required)}，实际为 {sorted(present)}")

        # 语义缺口的维度归属必须真实存在。
        for index, gap in enumerate(bundle["semantic_gaps"]):
            if gap["dimension_id"] not in expected:
                problems.append(f"{path}.semantic_gaps[{index}]: 维度 {gap['dimension_id']} 不在规范 41 维内")

        for limit_key, actual, label in (
            ("verifier_max_subreports", len(bundle["subreports"]), "subreports"),
            ("max_findings", sum(len(item["findings"]) for item in bundle["subreports"]), "findings"),
            ("max_gaps", sum(len(item["gaps"]) for item in bundle["subreports"]) + len(bundle["semantic_gaps"]), "gaps"),
        ):
            if actual > self.limits[limit_key]:
                problems.append(f"{path}.{label}: 数量 {actual} 超过规范上限 {self.limits[limit_key]}")
        return problems

    def check_finding_conservation(
        self, raw_reports: dict[str, dict[str, Any]], bundle: dict[str, Any]
    ) -> list[str]:
        """直接比较原始报告与专项报告，而不是只检查专项报告内部自洽。

        原始 finding/gap 必须逐条、恰好一次、原样出现在下游；rule_id、位置、问题和
        补救建议守恒，状态不得被降级或丢弃。
        """

        problems: list[str] = []
        subreports = {}
        for item in bundle.get("subreports", []) if isinstance(bundle.get("subreports"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("findings"), list) and isinstance(item.get("gaps"), list):
                subreports[item.get("review_type")] = item
        for review_type, raw in raw_reports.items():
            if not isinstance(raw.get("findings"), list) or not isinstance(raw.get("gaps"), list):
                problems.append(f"守恒：{review_type} 原始报告的 findings/gaps 不可用，无法比较")
                continue
            subreport = subreports.get(review_type)
            if subreport is None:
                problems.append(f"守恒：缺少 {review_type} 的专项报告")
                continue
            if subreport.get("raw_report_id") != raw.get("report_id"):
                problems.append(
                    f"守恒：{review_type} 专项报告绑定的 raw_report_id "
                    f"{subreport.get('raw_report_id')!r} 与原始报告 {raw.get('report_id')!r} 不一致"
                )

            for label, raw_items, id_field, downstream_items, origin_field, conserved in (
                ("finding", raw["findings"], "finding_id", subreport["findings"], "origin_raw_finding_id",
                 ("rule_id", "target_id", "location", "status", "problem", "remedy")),
                ("gap", raw["gaps"], "gap_id", subreport["gaps"], "origin_raw_gap_id",
                 ("rule_id", "target_id", "category", "reason", "blocks_assessment")),
            ):
                by_origin: dict[str, list[dict[str, Any]]] = {}
                for item in downstream_items:
                    origin = item.get("origin", {})
                    non_null = [key for key, value in origin.items() if value is not None]
                    if len(non_null) != 1:
                        problems.append(
                            f"守恒：{review_type} 下游 {label} {item.get(id_field)} 的 origin "
                            f"必须恰好一个非空引用，实际为 {non_null}"
                        )
                        continue
                    if non_null[0] != origin_field:
                        problems.append(
                            f"守恒：{review_type} 下游 {label} {item.get(id_field)} 的 origin 字段错位：{non_null[0]}"
                        )
                        continue
                    by_origin.setdefault(origin[origin_field], []).append(item)

                raw_ids = {item[id_field] for item in raw_items}
                for extra in sorted(set(by_origin) - raw_ids):
                    problems.append(f"守恒：{review_type} 下游 {label} 引用了不存在的原始 ID {extra}")
                for raw_item in raw_items:
                    matches = by_origin.get(raw_item[id_field], [])
                    if len(matches) == 0:
                        problems.append(
                            f"守恒：原始 {label} {raw_item[id_field]}（{raw_item['rule_id']}）在下游丢失"
                        )
                        continue
                    if len(matches) > 1:
                        problems.append(
                            f"守恒：原始 {label} {raw_item[id_field]} 在下游出现 {len(matches)} 次，必须恰好一次"
                        )
                    for field in conserved:
                        if matches[0].get(field) != raw_item.get(field):
                            problems.append(
                                f"守恒：原始 {label} {raw_item[id_field]} 的 {field} 被改写："
                                f"{raw_item.get(field)!r} -> {matches[0].get(field)!r}"
                            )
                    if matches[0].get("evidence") != raw_item.get("evidence"):
                        problems.append(f"守恒：原始 {label} {raw_item[id_field]} 的证据来源被改写")
        return problems


    def validate_verification(self, verification: Any, path: str = "verification") -> list[str]:
        """校验验证器自身的输出；存在错误时不得出现申请处置。"""

        if not isinstance(verification, dict):
            return [f"{path}: 必须是 JSON 对象"]
        problems = self._validate_object(verification, "verification", path)
        problems += self.prohibited_field_paths(verification, path)
        if problems:
            return problems
        allowed = set(self.data["enums"]["disposition"])
        disposition = verification["disposition"]
        if verification["errors"]:
            if disposition is not None:
                problems.append(f"{path}.disposition: 存在验证错误时不得给出申请处置")
            if not self.data["verifier_error_handling"]["legal_citation_allowed"]:
                citations = {item["citation"] for item in self.data["dimensions"]}
                for index, item in enumerate(verification["errors"]):
                    if any(citation in item["message"] for citation in citations):
                        problems.append(f"{path}.errors[{index}]: 工具错误不得引用中国专利法条款")
        elif disposition not in allowed:
            problems.append(f"{path}.disposition: 值 {disposition!r} 不在处置枚举中")
        return problems

    # -- 聚合与处置 ---------------------------------------------------------

    def aggregate(self, children: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """按规范的排序、覆盖度和严重度优先级做与输入顺序无关的聚合。"""

        rules = self.data["aggregation"]
        ordered = sorted(children, key=lambda item: item["assessment_id"])
        present = sorted({item["result"] for item in ordered})
        coverage = next(
            (value for value in rules["coverage_priority"] if any(item["coverage"] == value for item in ordered)),
            rules["coverage_priority"][-1],
        )
        severity = next(
            (value for value in rules["severity_priority"] if any(item["severity"] == value for item in ordered)),
            rules["severity_priority"][-1],
        )
        return {
            "child_ids": [item["assessment_id"] for item in ordered],
            "present_results": present,
            "result": present[0] if len(present) == 1 else "MIXED",
            "coverage": coverage,
            "severity": severity,
            "finding_ids": sorted({value for item in ordered for value in item["finding_ids"]}),
            "gap_ids": sorted({value for item in ordered for value in item["gap_ids"]}),
        }

    def derive_disposition(
        self, assessments: list[dict[str, Any]], verifier_errors: Iterable[str] | None = None
    ) -> str | None:
        """按规范优先级派生处置状态；存在验证器错误时不产生任何申请处置。"""

        if verifier_errors:
            return None
        for entry in self.data["disposition"]:
            if _DISPOSITION_RULES[entry["when"]](assessments):
                return entry["value"]
        return None


_CACHED: dict[str, Contract] = {}


def load_contract(path: Path | str | None = None) -> Contract:
    """加载规范并按路径缓存；同一进程内重复加载不重复读盘。"""

    key = str(Path(path) if path is not None else DEFAULT_CONTRACT_PATH)
    if key not in _CACHED:
        _CACHED[key] = Contract.load(key)
    return _CACHED[key]
