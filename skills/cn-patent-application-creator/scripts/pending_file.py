"""待决文件.md 的生成与回读。

人只改每条的「决定」和「标注」。机器刷新问题时保留这两节，并且不复用已经出现过的编号。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
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
DEFER_DECISIONS = {"暂缓", "暂缓决定", "先不决定", "稍后决定"}
# 采纳默认可以在“当前稿仍是该做法”时直接收掉。选择和指示不是源稿已改的证据。
EVIDENCE_RESOLUTIONS = {"choose", "instruct"}
APPLICATION_EVIDENCE_SCHEMA_ID = "cn-patent-pending-application-evidence/v1"
SOURCE_BINDING_NOTE = (
    "只证明应用声明绑定了当前源稿的路径和哈希，不证明备选或指示已经在语义上写入文书。"
)
ACCEPT_DEFAULT_NOTE = "采纳默认，且问题、已采用默认和备选与当前稿一致。这只说明当前稿仍是该默认做法。"
DECISION_ONLY_NOTE = "已记下人的决定，但没有绑定当前源稿的落实证据，不能当作已落实。"
REOPENED_NOTE = "问题、已采用默认或备选已变化，旧决定不再视为已落实。"
READ_ONLY_NOTE = "回读只记录人的决定，不核对当前源稿，不能当作已落实。"
BINDING_NOTES = {
    "accept_default_current_draft": ACCEPT_DEFAULT_NOTE,
    "source_hash_bound": SOURCE_BINDING_NOTE,
    "decision_only": DECISION_ONLY_NOTE,
    "reopened": REOPENED_NOTE,
    "none": "",
    "not_verified": READ_ONLY_NOTE,
}
CHOOSE_RE = re.compile(r"^选择[:：]\s*(.+)$", re.DOTALL)
BINDING_SOURCE_RE = re.compile(r"^sha256=([0-9a-f]{64}) path=(.+)$")
FENCE_MARKERS = ("<!-- item:", "<!-- /item:", "<!-- retired:", "<!-- /retired:")
FENCE_LIKE_RE = re.compile(r"(?:item|retired)\s*:")
FENCE_BODY_RE = re.compile(
    r"^\s*(?P<closing>/)?(?P<kind>item|retired):(?P<ident>\S+)\s*$"
)


class PendingFileError(ValueError):
    """待决文件无法安全解析；调用方不得覆盖原文件。"""


def stable_key(key: str, kind: str, locator: str) -> str:
    return f"{key}::{kind}:{locator}"


def content_fingerprint(question: Any, adopted_default: Any, options: list[Any] | None) -> str:
    """问题、已采用默认和备选的内容版本。只按这三项，不按条目 key。"""

    payload = {
        "question": _machine_text(question),
        "adopted_default": _machine_text(adopted_default),
        "options": [_machine_text(item) for item in (options or [])],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _metadata(body: str) -> str:
    """绑定标记只认决定标题之前的机器字段，避免人写的决定伪造落实。"""

    matched = re.search(r"(?m)^### 决定[ \t]*$", body)
    if matched is None:
        return body
    return body[:matched.start()]


def _reject_unsafe_relative(raw: str) -> None:
    if not raw or raw.startswith(("/", "\\")) or "\\" in raw:
        raise PendingFileError(f"落实源稿路径必须是案件目录内的相对路径：{raw}")
    parts = Path(raw).parts
    if not parts or any(part in {"", ".."} for part in parts):
        raise PendingFileError(f"落实源稿路径超出案件目录：{raw}")


def _binding(body: str) -> tuple[str, str, list[dict[str, str]]]:
    meta = _metadata(body)
    binding = _field(meta, "落实绑定")
    decision_fp = _field(meta, "落实决定")
    sources: list[dict[str, str]] = []
    for line in meta.splitlines():
        if not line.startswith("- 落实源稿："):
            continue
        raw = line.split("：", 1)[1].strip()
        matched = BINDING_SOURCE_RE.fullmatch(raw)
        if matched is None:
            raise PendingFileError("落实源稿无法解析")
        sources.append({"sha256": matched.group(1), "path": matched.group(2)})
    if binding and binding != "source_hash_bound":
        raise PendingFileError("落实绑定无法识别")
    if decision_fp and not re.fullmatch(r"[0-9a-f]{64}", decision_fp):
        raise PendingFileError("落实决定无法识别")
    if binding and (not decision_fp or not sources):
        raise PendingFileError("落实绑定缺少决定或源稿")
    if (decision_fp or sources) and binding != "source_hash_bound":
        raise PendingFileError("落实源稿缺少落实绑定")
    for source in sources:
        _reject_unsafe_relative(source["path"])
    return binding, decision_fp, sources


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
    binding, decision_fp, sources = _binding(body)
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
        "content_version": _field(body, "内容版本"),
        "stale_decision": _field(body, "失效决定"),
        "application_binding": binding,
        "application_decision": decision_fp,
        "application_sources": sources,
        "retired": retired,
    }


def _scan_fences(text: str) -> list[tuple[str, str, bool, int, int]]:
    """按出现顺序抽出条目边界。残缺、变形的边界直接失败，不跳过。"""

    fences: list[tuple[str, str, bool, int, int]] = []
    cursor = 0
    while True:
        open_at = text.find("<!--", cursor)
        if open_at < 0:
            break
        close_at = text.find("-->", open_at + 4)
        if close_at < 0:
            tail = text[open_at:]
            if FENCE_LIKE_RE.search(tail):
                raise PendingFileError("条目边界残缺，拒绝覆盖原文件")
            break
        body = text[open_at + 4:close_at]
        if FENCE_LIKE_RE.search(body):
            matched = FENCE_BODY_RE.fullmatch(body)
            if matched is None:
                raise PendingFileError("条目边界无法识别，拒绝覆盖原文件")
            kind = matched.group("kind")
            ident = matched.group("ident")
            if kind == "item" and not re.fullmatch(r"D\d{3}", ident):
                raise PendingFileError(f"条目编号无法识别：{ident}")
            if kind == "retired" and not re.fullmatch(r"\d+", ident):
                raise PendingFileError(f"已退出条目序号无法识别：{ident}")
            fences.append((kind, ident, bool(matched.group("closing")), open_at, close_at + 3))
        cursor = close_at + 3
    return fences


def parse_pending_file(text: str) -> dict[str, list[dict[str, Any]]]:
    if text.startswith("\ufeff"):
        raise PendingFileError("待决文件含 BOM，必须使用 UTF-8 无 BOM")
    fences = _scan_fences(text)
    items: list[dict[str, Any]] = []
    retired: list[dict[str, Any]] = []
    seen: set[str] = set()
    retired_indexes: set[str] = set()
    open_fence: tuple[str, str, int] | None = None
    for kind, ident, closing, marker_start, marker_end in fences:
        if not closing:
            if open_fence is not None:
                raise PendingFileError("条目边界嵌套或重叠，拒绝覆盖原文件")
            if kind == "item" and ident in seen:
                raise PendingFileError(f"编号重复：{ident}")
            if kind == "retired" and ident in retired_indexes:
                raise PendingFileError(f"已退出条目序号重复：{ident}")
            open_fence = (kind, ident, marker_end)
            continue
        if open_fence is None:
            raise PendingFileError("条目结束标记没有对应的开始标记，拒绝覆盖原文件")
        open_kind, open_ident, body_start = open_fence
        if open_kind != kind or open_ident != ident:
            raise PendingFileError("条目开始与结束标记不一致，拒绝覆盖原文件")
        body = text[body_start:marker_start]
        if kind == "item":
            seen.add(ident)
            items.append(_item_from_body(ident, body, retired=False))
        else:
            retired_indexes.add(ident)
            heading = re.search(r"(?m)^### 原 (D\d{3})\s*$", body)
            if heading is None:
                raise PendingFileError("已退出条目缺少原编号")
            item_id = heading.group(1)
            if item_id in seen:
                raise PendingFileError(f"编号重复：{item_id}")
            seen.add(item_id)
            retired.append(_item_from_body(item_id, body, retired=True))
        open_fence = None
    if open_fence is not None:
        raise PendingFileError("条目边界未闭合，拒绝覆盖原文件")
    decision_count = len(re.findall(r"(?m)^### 决定\s*$", text))
    parsed_count = len(items) + len(retired)
    if decision_count != parsed_count:
        if decision_count and not parsed_count:
            raise PendingFileError("待决文件有人工章节，但条目边界无法解析，拒绝覆盖")
        raise PendingFileError("存在未能归入条目的决定内容，拒绝覆盖原文件")
    return {"items": items, "retired": retired}


def load_existing(text: str) -> dict[str, list[dict[str, Any]]]:
    """旧版表格没有人工章节，可以整份替换；新版解析失败则必须停。"""
    if "<!-- item:" not in text and "<!-- retired:" not in text and "### 决定" not in text:
        return {"items": [], "retired": []}
    return parse_pending_file(text)


def _note_lines(decision: dict[str, Any], note: dict[str, Any]) -> list[str]:
    version = note.get("content_version") or content_fingerprint(
        decision.get("question", ""),
        decision.get("adopted_default", ""),
        list(decision.get("options") or []),
    )
    lines = [f"- 内容版本：{version}"]
    stale = _machine_text(note.get("stale_decision", ""))
    if stale:
        lines.append(f"- 失效决定：{stale}")
    sources = list(note.get("application_sources") or [])
    decision_fp = str(note.get("application_decision") or "")
    if note.get("application_binding") == "source_hash_bound" and decision_fp and sources:
        lines.append("- 落实绑定：source_hash_bound")
        lines.append(f"- 落实决定：{decision_fp}")
        for source in sources:
            lines.append(f"- 落实源稿：sha256={source['sha256']} path={source['path']}")
    return lines


def _render_active(decision: dict[str, Any], note: dict[str, Any]) -> str:
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
        *_note_lines(decision, note),
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
    options = item.get("options") or []
    if options:
        option_lines = ["- 备选：", *[f"  - {_machine_text(option)}" for option in options]]
    else:
        option_lines = ["- 备选：无"]
    version = item.get("content_version") or ""
    lines = [
        f"<!-- retired:{index} -->",
        f"### 原 {item['id']}",
        "",
        f"- 编号：{item['id']}",
        f"- 键：{_machine_text(item['key'])}",
        f"- 位置：{item['kind']}:{_machine_text(item['locator'])}",
        f"- 问题：{_machine_text(item.get('question') or '本轮机器清单已没有这一条。')}",
        f"- 已采用默认：{_machine_text(item.get('adopted_default') or '')}",
        *option_lines,
    ]
    if version:
        lines.append(f"- 内容版本：{version}")
    if item.get("stale_decision"):
        lines.append(f"- 失效决定：{_machine_text(item.get('stale_decision') or '')}")
    lines.extend([
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
    ])
    return "\n".join(lines)


def _append_items(lines: list[str], decisions: list[dict[str, Any]], notes: dict[str, dict[str, Any]]) -> None:
    for decision in decisions:
        key = stable_key(
            decision["key"], decision["target"]["kind"], decision["target"]["locator"],
        )
        lines.append(_render_active(decision, notes.get(key, {})))


def render_pending_file(
    *,
    case_id: str,
    generated_at: str,
    application_name: str,
    decisions: list[dict[str, Any]],
    notes: dict[str, dict[str, Any]],
    retired: list[dict[str, Any]],
    applied: list[dict[str, Any]] | None = None,
) -> str:
    applied = applied or []
    lines = [
        "# 待决文件",
        "",
        "本文件与最终专利申请文件放在同一目录。请只改每条的「决定」和「标注」。",
        "不要改编号、键、位置、内容版本，也不要删除条目边界。第二轮只读这两节，再修订申请文件。",
        "审稿版只给仍未落实的事项另起黄底段落。采纳默认且内容版本未变时，不再重复提问。",
        "选中备选，或写下修改指示，只表示已经决定；源稿没有按此改过之前，事项和决定都留在这里。",
        "改这个文件不会自动改 docx。",
        "",
        f"- 案号：{_machine_text(case_id)}",
        f"- 申请文件：{_machine_text(application_name)}",
        f"- 生成时间：{_machine_text(generated_at)}",
        f"- 机器合同：{SCHEMA_ID}",
        "",
    ]
    if not decisions:
        if applied:
            lines.extend(["当前没有仍待落实的事项。", ""])
        else:
            lines.extend(["当前无待决事项。" if not retired else "当前机器清单没有新的待决事项。", ""])
    else:
        lines.extend(["## 仍待落实的事项", ""])
        _append_items(lines, decisions, notes)
    if applied:
        lines.extend([
            "## 已落实的决定",
            "",
            "采纳默认，且问题、已采用默认和备选仍与当前稿一致的，记在这里。",
            "选中备选，或写下修改指示的，只有落实证据绑定了当前源稿哈希才记在这里。该绑定不证明语义上已经改对。",
            "问题、默认做法或备选实质变化后会重新打开。",
            "",
        ])
        _append_items(lines, applied, notes)
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
    elif decision_text in DEFER_DECISIONS and not annotation_text:
        resolution = "defer"
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


def decision_binding_fingerprint(classified: dict[str, Any]) -> str:
    payload = {
        "resolution": classified.get("resolution") or "",
        "selected_option": classified.get("selected_option") or "",
        "decision_text": classified.get("decision_text") or "",
        "annotation": classified.get("annotation") or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_inside(case_dir: Path, raw: str) -> Path:
    _reject_unsafe_relative(raw)
    root = case_dir.resolve()
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise PendingFileError(f"落实源稿路径超出案件目录：{raw}")
    if not candidate.is_file():
        raise PendingFileError(f"落实证据指向的源稿不存在：{raw}")
    return candidate


def _same_path(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False


def _copy_sources(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    copied = []
    for item in sources:
        copied.append({"path": str(item["path"]), "sha256": str(item["sha256"])})
    return copied


def _reset_source_binding(note: dict[str, Any]) -> None:
    note["application_binding"] = ""
    note["application_decision"] = ""
    note["application_sources"] = []


def _store_source_binding(
    note: dict[str, Any], classified: dict[str, Any], sources: list[dict[str, Any]],
) -> None:
    note["application_binding"] = "source_hash_bound"
    note["application_decision"] = decision_binding_fingerprint(classified)
    note["application_sources"] = _copy_sources(sources)


def _sources_match(case_dir: Path, sources: list[dict[str, Any]]) -> bool:
    if not sources:
        return False
    for source in sources:
        path = _resolve_inside(case_dir, str(source.get("path") or ""))
        if _sha256_file(path) != source.get("sha256"):
            return False
    return True


def _content_state(note: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    current_options = list(decision.get("options") or [])
    current_fp = content_fingerprint(
        decision.get("question", ""),
        decision.get("adopted_default", ""),
        current_options,
    )
    previous_options = list(note.get("options") or [])
    note_fp = content_fingerprint(
        note.get("question", ""),
        note.get("adopted_default", ""),
        previous_options,
    )
    bound = str(note.get("content_version") or "") or note_fp
    classified = classify_note(
        str(note.get("decision", "")),
        str(note.get("annotation", "")),
        previous_options or current_options,
    )
    return {
        "current_fp": current_fp,
        "note_fp": note_fp,
        "bound": bound,
        "same_content": bound == current_fp and note_fp == current_fp,
        "classified": classified,
    }


def _stale_text(classified: dict[str, Any]) -> str:
    parts = [str(classified.get("decision_text") or ""), str(classified.get("annotation") or "")]
    return "\n".join(part for part in parts if part)


def _persisted_source_binding_holds(
    note: dict[str, Any], classified: dict[str, Any], case_dir: Path | None,
) -> bool:
    if case_dir is None or note.get("application_binding") != "source_hash_bound":
        return False
    if str(note.get("application_decision") or "") != decision_binding_fingerprint(classified):
        return False
    sources = note.get("application_sources") or []
    if not isinstance(sources, list) or not sources:
        return False
    try:
        return _sources_match(case_dir, sources)
    except PendingFileError:
        return False


def _blank_note(current_fp: str) -> dict[str, Any]:
    return {
        "decision": "",
        "annotation": "",
        "content_version": current_fp,
        "stale_decision": "",
        "application_binding": "",
        "application_decision": "",
        "application_sources": [],
    }


def to_resolution_item(item: dict[str, Any]) -> dict[str, Any]:
    """回读只分类人的文字。applied 恒为 false，不把决定当成源稿已经改过。"""

    classified = classify_note(
        item.get("decision", ""), item.get("annotation", ""), item.get("options") or [],
    )
    content_version = item.get("content_version") or content_fingerprint(
        item.get("question", ""), item.get("adopted_default", ""), item.get("options") or [],
    )
    resolved = classified["resolution"] in {"accept_default", "choose", "instruct"}
    binding = "not_verified" if resolved else "none"
    return {
        "id": item["id"],
        "key": item["key"],
        "target": {"kind": item["kind"], "locator": item["locator"]},
        "decider": item.get("decider") or "",
        "question": item.get("question") or "",
        "adopted_default": item.get("adopted_default") or "",
        "options": list(item.get("options") or []),
        "retired": bool(item.get("retired")),
        "content_version": content_version,
        "status": "resolved" if resolved else "pending",
        "resolved": resolved,
        "applied": False,
        "application_binding": binding,
        "application_binding_note": BINDING_NOTES[binding],
        **classified,
    }


def _resolution_record(
    decision: dict[str, Any],
    classified: dict[str, Any],
    *,
    content_version: str,
    current_content_version: str,
    status: str,
    applied: bool,
    resolved: bool,
    application_binding: str,
    application_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": decision["id"],
        "key": decision["key"],
        "target": {
            "kind": decision["target"]["kind"],
            "locator": decision["target"]["locator"],
        },
        "resolution": classified["resolution"],
        "selected_option": classified["selected_option"],
        "decision_text": classified["decision_text"],
        "annotation": classified["annotation"],
        "question": str(decision.get("question") or ""),
        "adopted_default": str(decision.get("adopted_default") or ""),
        "options": [str(item) for item in (decision.get("options") or [])],
        "content_version": content_version,
        "current_content_version": current_content_version,
        "status": status,
        "resolved": resolved,
        "applied": applied,
        "application_binding": application_binding,
        "application_binding_note": BINDING_NOTES[application_binding],
        "application_sources": _copy_sources(application_sources),
    }


def _append_resolution(
    resolutions: list[dict[str, Any]],
    decision: dict[str, Any],
    classified: dict[str, Any],
    *,
    content_version: str,
    current_content_version: str,
    status: str,
    applied: bool,
    resolved: bool,
    application_binding: str,
    application_sources: list[dict[str, Any]] | None = None,
) -> None:
    resolutions.append(_resolution_record(
        decision, classified,
        content_version=content_version,
        current_content_version=current_content_version,
        status=status,
        applied=applied,
        resolved=resolved,
        application_binding=application_binding,
        application_sources=application_sources or [],
    ))


def split_resolved(
    decisions: list[dict[str, Any]],
    notes: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]] | None = None,
    case_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """只把已落实的事项移出活动清单。活动对象本身不追加新字段。"""

    evidence = evidence or {}
    active: list[dict[str, Any]] = []
    applied_items: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    for decision in decisions:
        key = stable_key(decision["key"], decision["target"]["kind"], decision["target"]["locator"])
        note = notes.get(key)
        if note is None:
            current_fp = content_fingerprint(
                decision.get("question", ""),
                decision.get("adopted_default", ""),
                list(decision.get("options") or []),
            )
            notes[key] = _blank_note(current_fp)
            active.append(decision)
            continue
        state = _content_state(note, decision)
        classified = state["classified"]
        current_fp = state["current_fp"]
        bound = state["bound"]
        resolution = classified["resolution"]
        substantive = resolution in {"accept_default", *EVIDENCE_RESOLUTIONS}
        if substantive and bound != current_fp:
            _append_resolution(
                resolutions, decision, classified,
                content_version=bound,
                current_content_version=current_fp,
                status="reopened",
                applied=False,
                resolved=False,
                application_binding="reopened",
            )
            note["stale_decision"] = _stale_text(classified)
            note["decision"] = ""
            note["annotation"] = ""
            note["content_version"] = current_fp
            _reset_source_binding(note)
            active.append(decision)
            continue
        if substantive and not state["same_content"]:
            _reset_source_binding(note)
            note["content_version"] = current_fp
            note["stale_decision"] = ""
            _append_resolution(
                resolutions, decision, classified,
                content_version=current_fp,
                current_content_version=current_fp,
                status="resolved",
                applied=False,
                resolved=True,
                application_binding="decision_only",
            )
            active.append(decision)
            continue
        if resolution == "accept_default":
            _reset_source_binding(note)
            note["content_version"] = current_fp
            note["stale_decision"] = ""
            _append_resolution(
                resolutions, decision, classified,
                content_version=current_fp,
                current_content_version=current_fp,
                status="applied",
                applied=True,
                resolved=True,
                application_binding="accept_default_current_draft",
            )
            applied_items.append(decision)
            continue
        if resolution in EVIDENCE_RESOLUTIONS:
            fingerprint = decision_binding_fingerprint(classified)
            evidence_item = evidence.get(key)
            sources = None
            if evidence_item and evidence_item.get("decision_fingerprint") == fingerprint:
                sources = list(evidence_item.get("sources") or [])
            elif _persisted_source_binding_holds(note, classified, case_dir):
                sources = list(note.get("application_sources") or [])
            if sources:
                _store_source_binding(note, classified, sources)
                note["content_version"] = current_fp
                note["stale_decision"] = ""
                _append_resolution(
                    resolutions, decision, classified,
                    content_version=current_fp,
                    current_content_version=current_fp,
                    status="applied",
                    applied=True,
                    resolved=True,
                    application_binding="source_hash_bound",
                    application_sources=sources,
                )
                applied_items.append(decision)
                continue
            _reset_source_binding(note)
            note["content_version"] = current_fp
            note["stale_decision"] = ""
            _append_resolution(
                resolutions, decision, classified,
                content_version=current_fp,
                current_content_version=current_fp,
                status="resolved",
                applied=False,
                resolved=True,
                application_binding="decision_only",
            )
            active.append(decision)
            continue
        note["content_version"] = current_fp
        _reset_source_binding(note)
        if resolution == "defer":
            _append_resolution(
                resolutions, decision, classified,
                content_version=current_fp,
                current_content_version=current_fp,
                status="pending",
                applied=False,
                resolved=False,
                application_binding="none",
            )
        active.append(decision)
    return active, applied_items, resolutions


def _require_mapping_fields(item: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = set(item) - allowed
    if extra:
        raise PendingFileError(f"{label}含不能识别的字段：{', '.join(sorted(extra))}")


def _parse_evidence_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise PendingFileError("落实证据的条目必须是对象")
    _require_mapping_fields(item, {
        "key", "target", "resolution", "selected_option", "decision_text",
        "annotation", "content_version", "sources",
    }, "落实证据条目")
    key = item.get("key")
    if not isinstance(key, str) or not key:
        raise PendingFileError("落实证据缺少 key")
    target = item.get("target")
    if not isinstance(target, dict):
        raise PendingFileError("落实证据的 target 不正确")
    _require_mapping_fields(target, {"kind", "locator"}, "落实证据的位置")
    kind = target.get("kind")
    locator = target.get("locator")
    if kind not in TARGET_KINDS or not isinstance(locator, str) or not locator.strip():
        raise PendingFileError("落实证据的位置不正确")
    resolution = item.get("resolution")
    if resolution not in EVIDENCE_RESOLUTIONS:
        raise PendingFileError("落实证据只接受 choose 或 instruct")
    decision_text = item.get("decision_text")
    if not isinstance(decision_text, str):
        raise PendingFileError("落实证据缺少决定原文")
    annotation = item.get("annotation", "")
    if not isinstance(annotation, str):
        raise PendingFileError("落实证据的标注必须是字符串")
    selected = item.get("selected_option", None)
    if resolution == "choose":
        if not isinstance(selected, str) or not selected:
            raise PendingFileError("choose 的落实证据必须给出选中的备选")
    else:
        if "selected_option" in item and selected not in (None, ""):
            raise PendingFileError("instruct 的落实证据不能另报一个已选备选")
        selected = None
    content_version = item.get("content_version")
    if not isinstance(content_version, str) or not re.fullmatch(r"[0-9a-f]{64}", content_version):
        raise PendingFileError("落实证据的内容版本不正确")
    sources = item.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PendingFileError("落实证据必须给出至少一个当前源稿")
    parsed_sources = []
    for source in sources:
        if not isinstance(source, dict):
            raise PendingFileError("落实证据的源稿字段不正确")
        _require_mapping_fields(source, {"path", "sha256"}, "落实证据的源稿")
        raw_path = source.get("path")
        digest = source.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise PendingFileError("落实证据的源稿字段不正确")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PendingFileError(f"落实证据的源稿哈希不正确：{raw_path}")
        _reject_unsafe_relative(raw_path)
        parsed_sources.append({"path": raw_path, "sha256": digest})
    return {
        "key": key,
        "kind": kind,
        "locator": locator.strip(),
        "resolution": resolution,
        "selected_option": selected,
        "decision_text": decision_text,
        "annotation": annotation,
        "content_version": content_version,
        "sources": parsed_sources,
    }


def _require_decision_match(note: dict[str, Any], decision: dict[str, Any], parsed: dict[str, Any]) -> str:
    state = _content_state(note, decision)
    classified = state["classified"]
    if parsed["content_version"] != state["current_fp"] or not state["same_content"]:
        raise PendingFileError("落实证据的内容版本与当前待决不一致")
    if (
        parsed["resolution"] != classified["resolution"]
        or parsed["decision_text"] != classified["decision_text"]
        or parsed["annotation"] != classified["annotation"]
        or parsed["selected_option"] != classified["selected_option"]
    ):
        raise PendingFileError("落实证据与待决文件中的决定不一致")
    return decision_binding_fingerprint(classified)


def index_application_evidence(
    path: Path | None,
    *,
    case_dir: Path,
    case_id: str,
    decisions: list[dict[str, Any]],
    notes: dict[str, dict[str, Any]],
    forbidden_outputs: list[Path] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    """核对落实证据。只证明声明绑定当前源稿字节，不判断正文是否已经按决定改对。"""

    if path is None:
        return {}, []
    if not path.is_file():
        raise PendingFileError(f"找不到落实证据：{path}")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PendingFileError("落实证据含 BOM，必须使用 UTF-8 无 BOM")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PendingFileError(f"落实证据不是 UTF-8 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise PendingFileError("落实证据必须是对象")
    _require_mapping_fields(payload, {"schema_id", "case_id", "items", "binding_note"}, "落实证据")
    if payload.get("schema_id") != APPLICATION_EVIDENCE_SCHEMA_ID:
        raise PendingFileError("落实证据的 schema_id 不正确")
    if payload.get("case_id") != case_id:
        raise PendingFileError("落实证据的案号与 --case-dir 不一致")
    if "binding_note" in payload and not isinstance(payload["binding_note"], str):
        raise PendingFileError("落实证据的 binding_note 必须是字符串")
    items = payload.get("items")
    if not isinstance(items, list):
        raise PendingFileError("落实证据的 items 必须是数组")
    decisions_by_key = {
        stable_key(item["key"], item["target"]["kind"], item["target"]["locator"]): item
        for item in decisions
    }
    indexed: dict[str, dict[str, Any]] = {}
    source_paths: list[Path] = []
    forbidden = forbidden_outputs or []
    for raw_item in items:
        parsed = _parse_evidence_item(raw_item)
        key = stable_key(parsed["key"], parsed["kind"], parsed["locator"])
        if key in indexed:
            raise PendingFileError(f"落实证据重复：{key}")
        decision = decisions_by_key.get(key)
        note = notes.get(key)
        if decision is None or note is None:
            raise PendingFileError(f"落实证据找不到仍带着人的决定的事项：{key}")
        verified = []
        for source in parsed["sources"]:
            file_path = _resolve_inside(case_dir, source["path"])
            if any(_same_path(file_path, output) for output in forbidden):
                raise PendingFileError("落实证据不能绑定本次要改写的待决文件或汇总 JSON")
            if _sha256_file(file_path) != source["sha256"]:
                raise PendingFileError(f"落实证据的源稿哈希与当前文件不一致：{source['path']}")
            verified.append({"path": source["path"], "sha256": source["sha256"]})
            source_paths.append(file_path)
        indexed[key] = {
            "sources": verified,
            "decision_fingerprint": _require_decision_match(note, decision, parsed),
        }
    return indexed, source_paths
