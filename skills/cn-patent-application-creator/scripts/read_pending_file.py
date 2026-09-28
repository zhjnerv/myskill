#!/usr/bin/env python3
"""读取人工修改过的待决文件，整理成第二轮可消费的决议。不改申请文件。"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cn_drafting_io import DraftingOutputGuard
from pending_file import (
    RESOLUTIONS_SCHEMA_ID,
    PendingFileError,
    parse_pending_file,
    to_resolution_item,
)

EXIT_SUCCESS = 0
EXIT_INPUT_ERROR = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="把待决文件中的决定和标注整理为决议 JSON")
    parser.add_argument("--pending-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.pending_file
    try:
        raw = source.read_bytes()
    except OSError as exc:
        print(f"读取待决文件失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    if raw.startswith(b"\xef\xbb\xbf"):
        print("待决文件含 BOM，必须使用 UTF-8 无 BOM", file=sys.stderr)
        return EXIT_INPUT_ERROR
    try:
        parsed = parse_pending_file(raw.decode("utf-8"))
        guard = DraftingOutputGuard([source], [args.output])
    except (PendingFileError, UnicodeDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    items = [to_resolution_item(item) for item in parsed["items"]]
    retired = [to_resolution_item({**item, "retired": True}) for item in parsed["retired"]]
    summary = {
        "unresolved": 0,
        "accept_default": 0,
        "choose": 0,
        "instruct": 0,
        "retired": len(retired),
    }
    for item in items:
        summary[item["resolution"]] = summary.get(item["resolution"], 0) + 1
    payload = {
        "schema_id": RESOLUTIONS_SCHEMA_ID,
        "source_path": str(source),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "legal_effect": "ADVISORY_ONLY",
        "items": items,
        "retired": retired,
        "summary": summary,
    }
    try:
        guard.write_texts((json.dumps(payload, ensure_ascii=False, indent=2) + "\n",))
    except (OSError, ValueError) as exc:
        print(f"写入决议失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(f"UNRESOLVED={summary['unresolved']}")
    print(f"ACCEPT_DEFAULT={summary['accept_default']}")
    print(f"CHOOSE={summary['choose']}")
    print(f"INSTRUCT={summary['instruct']}")
    print(f"RETIRED={summary['retired']}")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
