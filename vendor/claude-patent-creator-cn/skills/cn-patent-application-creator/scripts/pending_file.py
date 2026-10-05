"""待决文件.md 的生成与回读。

人只改每条的「决定」和「标注」。机器刷新问题时保留这两节，并且不复用已经出现过的编号。
"""
from __future__ import annotations

import re
from typing import Any

PENDING_FILENAME = "待决文件.md"
SCHEMA_ID = "cn-patent-pending-decisions/v1"
RESOLUTIONS_SCHEMA_ID = "cn-patent-pending-resolutions/v1"

TARGET_KINDS = {
    "process", "ledger", "claim", "specification", "abstract", "drawing", "review", "application",
}
DECISION_PLACEHOLDER = "未决"
ANNOTATION_PLACEHOLDER = "（在此填写。留空表示这一条仍未决定。）"
ACCEPT_DEFAULT = {"采纳默认", "维持默认", "同意默认", "接受默认"}
ITEM_RE = re.compile(
    r"<!--\s*item:(D\d{3})\s*-->\s*(.*?)<!--\s*/item:(D\d{3})\s*-->",
    re.DOTALL,
)
RETIRED_RE = re.compile(
    r"<!--\s*retired:(\d+)\s*-->\s*(.*?)<!--\s*/retired:(\d+)\s*-->",
    re.DOTALL,
)
CHOOSE_RE = re.compile(r"^选择[:：]\s*(.+)$", re.DOTALL)
FENCE_MARKERS = ("<!-- item:", "<!-- /item:", "<!-- retired:", "<!-- /retired:")


class PendingFileError(ValueError):
    """待决文件无法安全解析；调用方不得覆盖原文件。"""


def stable_key(key: str, kind: str, locator: str) -> str:
    return f"{key}::{kind}:{locator}"


def _machine_text(value: Any) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    for marker in FENCE_MARKERS:
        text = text.replace(marker, marker.replace("<", "＜"))
    return text.strip()


def _note_is_safe(text: str) -> None:
    for marker in FENCE_MARKERS:
        if marker in text:
            raise PendingFileError("决定或标注里不能包含条目边界注释")
    for line in text.splitlines():
        if line.strip() in {"### 决定", "### 标注"}:
            raise PendingFileError("决定或标注里不能另起「决定」或「标注」标题")


def _clean_note(text: str) -> str:
    _note_is_safe(text)
    return text.strip("\n")


def _is_blank(text: str, placeholder: str) -> bool:
    return text.strip() in {"", placeholder}


def display_decision(text: str) -> str:
    cleaned = _clean_note(text)
    if _is_blank(cleaned, DECISION_PLACEHOLDER):
        return DECISION_PLACEHOLDER
    return cleaned


def display_annotation(text: str) -> str:
    cleaned = _clean_note(text)
    if _is_blank(cleaned, ANNOTATION_PLACEHOLDER):
        return ANNOTATION_PLACEHOLDER
    return cleaned


def _field(body: str, label: str, required: bool = False) -> str:
    matched = re.search(rf"(?m)^- {re.escape(label)}：(.*)$", body)
    if matched is None:
        if required:
            raise PendingFileError(f"缺少「{label}」")
        return ""
    return matched.group(1).strip()


def _section(body: str, heading: str, next_heading: str | None) -> str:
    if next_heading:
        pattern = (
            rf"(?ms)^### {re.escape(heading)}[ \t]*\n"
            rf"(.*?)^### {re.escape(next_heading)}[ \t]*$"
        )
    else:
        pattern = rf"(?ms)^### {re.escape(heading)}[ \t]*\n(.*)\Z"
    matched = re.search(pattern, body)
    if matched is None:
        raise PendingFileError(f"缺少「{heading}」")
    return matched.group(1).strip("\n")


def _options(body: str) -> list[str]:
    options: list[str] = []
    capturing = False
    for line in body.splitlines():
        if line.startswith("- 备选："):
            capturing = True
            rest = line.split("：", 1)[1].strip()
            if rest and rest != "无":
                options.append(rest)
            continue
        if not capturing:
            continue
        if line.startswith("  - "):
            options.append(line[4:].strip())
            continue
        break
    return options


def _impacts(body: str) -> list[str]:
    raw = _field(body, "影响")
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[、,]", raw) if item.strip()]


def _location(body: str) -> tuple[str, str]:
    raw = _field(body, "位置", required=True)
    kind, separator, locator = raw.partition(":")
    if not separator or kind not in TARGET_KINDS or not locator.strip():
        raise PendingFileError(f"位置无法解析：{raw}")
    return kind, locator.strip()


def _item_from_body(item_id: str, body: str, retired: bool) -> dict[str, Any]:
    numbered = _field(body, "编号")
    heading = re.search(r"(?m)^### 原 (D\d{3})\s*$" if retired else r"(?m)^## (D\d{3})\s*$", body)
    if heading is None:
        raise PendingFileError(f"{item_id} 缺少标题")
    if heading.group(1) != item_id or (numbered and numbered != item_id):
        raise PendingFileError(f"{item_id} 的编号不一致")
    kind, locator = _location(body)
    key = _field(body, "键", required=True)
    if not key:
        raise PendingFileError(f"{item_id} 缺少键")
    decision = _section(body, "决定", "标注")
    annotation = _section(body, "标注", None)
    _note_is_safe(decision)
    _note_is_safe(annotation)
    return {
        "id": item_id,
        "key": key,
        "kind": kind,
        "locator": locator,
        "decider": _field(body, "决策人"),
        "impact": _impacts(body),
        "question": _field(body, "问题"),
        "adopted_default": _field(body, "已采用默认"),
        "options": _options(body),
        "decision": decision,
        "annotation": annotation,
        "retired": retired,
    }


def parse_pending_file(text: str) -> dict[str, list[dict[str, Any]]]:
    if text.startswith("\ufeff"):
        raise PendingFileError("待决文件含 BOM，必须使用 UTF-8 无 BOM")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for start_id, body, end_id in ITEM_RE.findall(text):
        if start_id != end_id:
            raise PendingFileError(f"{start_id} 的条目边界不一致")
        if start_id in seen:
            raise PendingFileError(f"编号重复：{start_id}")
        seen.add(start_id)
        items.append(_item_from_body(start_id, body, retired=False))
    retired: list[dict[str, Any]] = []
    for start_no, body, end_no in RETIRED_RE.findall(text):
        if start_no != end_no:
            raise PendingFileError("已退出条目的边界不一致")
        heading = re.search(r"(?m)^### 原 (D\d{3})\s*$", body)
        if heading is None:
            raise PendingFileError("已退出条目缺少原编号")
        if heading.group(1) in seen:
            raise PendingFileError(f"编号重复：{heading.group(1)}")
        seen.add(heading.group(1))
        retired.append(_item_from_body(heading.group(1), body, retired=True))
    if "### 决定" in text and not items and not retired:
        raise PendingFileError("待决文件有人工章节，但条目边界无法解析，拒绝覆盖")
    return {"items": items, "retired": retired}


def load_existing(text: str) -> dict[str, list[dict[str, Any]]]:
    """旧版表格没有人工章节，可以整份替换；新版解析失败则必须停。"""
    if "<!-- item:" not in text and "<!-- retired:" not in text and "### 决定" not in text:
        return {"items": [], "retired": []}
    return parse_pending_file(text)


def _render_active(decision: dict[str, Any], note: dict[str, str]) -> str:
    item_id = decision["id"]
    kind = decision["target"]["kind"]
    locator = decision["target"]["locator"]
    options = decision.get("options") or []
    if options:
        option_lines = ["- 备选：", *[f"  - {_machine_text(item)}" for item in options]]
    else:
        option_lines = ["- 备选：无"]
    lines = [
        f"<!-- item:{item_id} -->",
        f"## {item_id}",
        "",
        f"- 编号：{item_id}",
        f"- 键：{_machine_text(decision['key'])}",
        f"- 位置：{kind}:{_machine_text(locator)}",
        f"- 决策人：{_machine_text(decision['decider'])}",
        f"- 影响：{_machine_text('、'.join(decision.get('impact') or []))}",
        f"- 问题：{_machine_text(decision['question'])}",
        f"- 已采用默认：{_machine_text(decision['adopted_default'])}",
        *option_lines,
        (
            f"- 来源：{_machine_text(decision['source']['tool_id'])} / "
            f"{_machine_text(decision['source']['rule_id'])}"
        ),
        "",
        "### 决定",
        "",
        display_decision(note.get("decision", "")),
        "",
        "### 标注",
        "",
        display_annotation(note.get("annotation", "")),
        "",
        f"<!-- /item:{item_id} -->",
        "",
    ]
    return "\n".join(lines)


def _render_retired(item: dict[str, Any], index: int) -> str:
    lines = [
        f"<!-- retired:{index} -->",
        f"### 原 {item['id']}",
        "",
        f"- 编号：{item['id']}",
        f"- 键：{_machine_text(item['key'])}",
        f"- 位置：{item['kind']}:{_machine_text(item['locator'])}",
        f"- 问题：{_machine_text(item.get('question') or '本轮机器清单已没有这一条。')}",
        "- 说明：编号继续占用，避免审稿版里的旧标记被新问题拿去用。",
        "",
        "### 决定",
        "",
        display_decision(item.get("decision", "")),
        "",
        "### 标注",
        "",
        display_annotation(item.get("annotation", "")),
        "",
        f"<!-- /retired:{index} -->",
        "",
    ]
    return "\n".join(lines)


def render_pending_file(
    *,
    case_id: str,
    generated_at: str,
    application_name: str,
    decisions: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
    retired: list[dict[str, Any]],
) -> str:
    lines = [
        "# 待决文件",
        "",
        "本文件与最终专利申请文件放在同一目录。请只改每条的「决定」和「标注」。",
        "不要改编号、键、位置，也不要删除条目边界。第二轮只读这两节，再修订申请文件。",
        "审稿版会在对应位置另起黄底段落，写明问题、当前稿做法和备选；只看审稿版就能选择。改这个文件不会自动改 docx。",
        "",
        f"- 案号：{_machine_text(case_id)}",
        f"- 申请文件：{_machine_text(application_name)}",
        f"- 生成时间：{_machine_text(generated_at)}",
        f"- 机器合同：{SCHEMA_ID}",
        "",
    ]
    if not decisions:
        lines.extend(["当前无待决事项。" if not retired else "当前机器清单没有新的待决事项。", ""])
    else:
        lines.extend(["## 待决定的事项", ""])
        for decision in decisions:
            key = stable_key(
                decision["key"], decision["target"]["kind"], decision["target"]["locator"],
            )
            lines.append(_render_active(decision, notes.get(key, {})))
    if retired:
        lines.extend([
            "## 已退出本轮机器清单",
            "",
            "这些条目这次没有再出现。编号不要删，也不要拿去标新问题。",
            "",
        ])
        for index, item in enumerate(retired, start=1):
            lines.append(_render_retired(item, index))
    return "\n".join(lines).rstrip() + "\n"


def classify_note(decision: str, annotation: str, options: list[str]) -> dict[str, Any]:
    decision_text = decision.strip()
    annotation_text = annotation.strip()
    if decision_text == DECISION_PLACEHOLDER:
        decision_text = ""
    if annotation_text == ANNOTATION_PLACEHOLDER:
        annotation_text = ""
    selected = None
    unmatched = False
    choose = CHOOSE_RE.fullmatch(decision_text)
    if choose and decision_text:
        selected_text = choose.group(1).strip()
        if selected_text in options:
            selected = selected_text
        else:
            unmatched = True
    if not decision_text and not annotation_text:
        resolution = "unresolved"
    elif decision_text in ACCEPT_DEFAULT and not annotation_text:
        resolution = "accept_default"
    elif selected and not annotation_text:
        resolution = "choose"
    else:
        resolution = "instruct"
    instruction_parts = [part for part in (decision_text, annotation_text) if part]
    return {
        "resolution": resolution,
        "selected_option": selected,
        "option_unmatched": unmatched,
        "decision_text": decision_text,
        "annotation": annotation_text,
        "instruction": "\n".join(instruction_parts),
    }


def to_resolution_item(item: dict[str, Any]) -> dict[str, Any]:
    classified = classify_note(
        item.get("decision", ""), item.get("annotation", ""), item.get("options") or [],
    )
    return {
        "id": item["id"],
        "key": item["key"],
        "target": {"kind": item["kind"], "locator": item["locator"]},
        "decider": item.get("decider") or "",
        "question": item.get("question") or "",
        "adopted_default": item.get("adopted_default") or "",
        "options": list(item.get("options") or []),
        "retired": bool(item.get("retired")),
        **classified,
    }
