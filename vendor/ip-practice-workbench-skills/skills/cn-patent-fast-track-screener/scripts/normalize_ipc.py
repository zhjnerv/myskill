from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any

SUBCLASS_RE = re.compile(r"\b([A-HY])\s*([0-9]{2})\s*([A-Z])\b", re.IGNORECASE)
CLASS_ONLY_RE = re.compile(r"^[A-HY][0-9]{2}$", re.IGNORECASE)
FULL_IPC_RE = re.compile(
    r"\b([A-HY])\s*([0-9]{2})\s*([A-Z])\s*([0-9]+)\s*/\s*([0-9]+)\b",
    re.IGNORECASE,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_DEFINITION_LENGTH = 600


def _text_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _truncate_definition(text: str, limit: int = MAX_DEFINITION_LENGTH) -> str:
    if isinstance(text, str) and len(text) > limit:
        return text[: limit - 8] + "... [已截断]"
    return text


def extract_subclass_from_full_ipc(ipc_code: str) -> str:
    """从完整 IPC 分类号提取 4 位小类（如 'G06F 30/27' -> 'G06F'）。"""
    if not isinstance(ipc_code, str):
        return ""
    match = FULL_IPC_RE.search(ipc_code)
    if match:
        return "".join(match.groups()[:3]).upper()
    match = SUBCLASS_RE.search(ipc_code)
    if match:
        return "".join(match.groups()).upper()
    return ""


def normalize_ipc_code(value: Any, allow_full: bool = True) -> str | None:
    """标准化单个 IPC 分类号。

    Args:
        value: 待标准化的字符串。
        allow_full: 是否优先返回完整 IPC 号（含主组/小组）。

    Returns:
        标准化后的分类号字符串；若格式无效则返回 None。
    """
    text = _text_or_empty(value).strip().upper().replace("\u3000", " ")
    if not text:
        return None

    if allow_full:
        match = FULL_IPC_RE.search(text)
        if match:
            section, cls, subclass, main_group, subgroup = match.groups()
            return f"{section}{cls}{subclass} {main_group}/{subgroup}"

    match = SUBCLASS_RE.search(text)
    if not match:
        return None
    code = "".join(match.groups()).upper()
    return code if len(code) == 4 and not CLASS_ONLY_RE.match(code) else None


def normalize_ipc_codes(values: list[Any] | None, allow_full: bool = True) -> list[str]:
    """批量标准化并去重 IPC 代码列表，保持原有顺序。"""
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        code = normalize_ipc_code(value, allow_full=allow_full)
        if code and code not in seen:
            seen.add(code)
            normalized.append(code)
    return normalized


def extract_ipc_codes_from_text(text: Any, allow_full: bool = True) -> list[str]:
    """从自由文本中自动提取所有有效的 IPC 分类号。"""
    text_str = _text_or_empty(text)
    if not text_str:
        return []
    seen: set[str] = set()
    codes: list[str] = []
    full_spans: list[tuple[int, int]] = []

    if allow_full:
        for match in FULL_IPC_RE.finditer(text_str):
            section, cls, subclass, main_group, subgroup = match.groups()
            code = f"{section}{cls}{subclass} {main_group}/{subgroup}"
            full_spans.append(match.span())
            if code not in seen:
                seen.add(code)
                codes.append(code)

    for match in SUBCLASS_RE.finditer(text_str):
        if any(start <= match.start() and match.end() <= end for start, end in full_spans):
            continue
        code = "".join(match.groups()).upper()
        if code not in seen and not CLASS_ONLY_RE.match(code):
            seen.add(code)
            codes.append(code)

    return codes


def load_subclass_definitions(data_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """加载 4 位 IPC 小类的官方中文/英文定义，并进行长度保护截断。"""
    base_dir = data_dir or DEFAULT_DATA_DIR
    gz_path = base_dir / "ipc_subclass_definitions.json.gz"
    json_path = base_dir / "ipc_subclass_definitions.json"

    raw_dict: dict[str, Any] = {}
    if gz_path.exists():
        try:
            with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                raw_dict = json.load(f)
        except Exception:
            pass
    elif json_path.exists():
        try:
            raw_dict = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    safe_dict: dict[str, dict[str, str]] = {}
    for code, item in raw_dict.items():
        if isinstance(item, dict):
            safe_dict[code] = {
                "zh": _truncate_definition(item.get("zh", "")),
                "en": _truncate_definition(item.get("en", "")),
            }
    return safe_dict


def format_normalized_report(
    codes: list[str],
    definitions: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    defs = definitions or {}

    for code in codes:
        subclass = extract_subclass_from_full_ipc(code)
        is_full = "/" in code
        entry: dict[str, Any] = {
            "normalized_code": code,
            "type": "full_ipc" if is_full else "subclass",
            "subclass": subclass,
            "section": code[0] if code else "",
            "is_valid_format": bool(code),
        }
        if subclass in defs:
            entry["definition"] = {
                "zh": _truncate_definition(defs[subclass].get("zh", "")),
                "en": _truncate_definition(defs[subclass].get("en", "")),
            }
        items.append(entry)

    subclasses = list(dict.fromkeys(item["subclass"] for item in items if item["subclass"]))
    full_codes = [item["normalized_code"] for item in items if item["type"] == "full_ipc"]

    return {
        "valid": bool(items),
        "total_count": len(items),
        "all_codes": [item["normalized_code"] for item in items],
        "subclasses": subclasses,
        "full_codes": full_codes,
        "details": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="IPC 专利分类号标准化与有效性校验工具。支持 4 位小类与完整组/小组号规范化提取及定义查询。"
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="待校验的 IPC 代码（可多个，如 G06F30/27 H01M10/0525）",
    )
    parser.add_argument(
        "-i",
        "--ipc",
        action="append",
        dest="ipc_flags",
        help="通过选项传入 IPC 代码，可重复指定",
    )
    parser.add_argument(
        "-t",
        "--text",
        type=str,
        help="包含 IPC 分类号的自由文本（自动从中正则提取有效分类号）",
    )
    parser.add_argument(
        "--subclass-only",
        action="store_true",
        help="强制仅输出 4 位 IPC 小类（剥离主组与小组）",
    )
    parser.add_argument(
        "--with-definitions",
        action="store_true",
        help="附带 4 位小类的中文与英文官方定义（受 600 字安全长度保护）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="数据目录（用于读取 IPC 定义字典）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="输出 JSON 格式结果（默认启用）",
    )

    args = parser.parse_args(argv)

    raw_candidates: list[str] = []
    if args.inputs:
        raw_candidates.extend(args.inputs)
    if args.ipc_flags:
        raw_candidates.extend(args.ipc_flags)

    if args.text:
        extracted = extract_ipc_codes_from_text(args.text, allow_full=not args.subclass_only)
        raw_candidates.extend(extracted)

    if not raw_candidates and not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        if stdin_content:
            extracted = extract_ipc_codes_from_text(stdin_content, allow_full=not args.subclass_only)
            raw_candidates.extend(extracted)

    if not raw_candidates:
        parser.error("请提供待校验的 IPC 分类号或文本。示例: python scripts/normalize_ipc.py G06F30/27 H01M")

    normalized = normalize_ipc_codes(raw_candidates, allow_full=not args.subclass_only)
    defs = load_subclass_definitions(args.data_dir) if args.with_definitions else {}
    report = format_normalized_report(normalized, defs)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
