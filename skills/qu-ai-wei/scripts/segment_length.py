#!/usr/bin/env python3
"""Measure preselected editable prose; this is not a Markdown/protection parser."""

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata


BOUNDARY = re.compile(r"[。？！，；]|\n[^\S\n]*\n")


def measure(text: str) -> dict:
    """Count nonempty fragments without joining separate prose paragraphs."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lengths = []
    for fragment in BOUNDARY.split(text):
        length = sum(
            1 for char in fragment
            if not char.isspace() and not unicodedata.category(char).startswith("P")
        )
        if length:
            lengths.append(length)
    total = sum(lengths)
    count = len(lengths)
    # Compare integers, so rounding cannot turn a result below 10 into a pass.
    status = "not_applicable" if not count else ("pass" if total >= 10 * count else "fail")
    return {
        "status": status,
        "characters": total,
        "segments": count,
        "average": round(total / count, 4) if count else None,
        "minimum_average": 10,
        "segment_lengths": lengths,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="UTF-8 plain prose file, or - for stdin; exclude protected text first")
    args = parser.parse_args()
    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        parser.error(str(error))
    result = measure(text)
    print(json.dumps(result, ensure_ascii=True))
    return {"pass": 0, "fail": 1, "not_applicable": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
