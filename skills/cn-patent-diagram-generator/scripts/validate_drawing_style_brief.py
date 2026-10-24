#!/usr/bin/env python3
"""校验用户范例样式合同的文件绑定、视觉复用边界和批准状态。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "analyze_drawing_reference.py"
spec = importlib.util.spec_from_file_location("drawing_reference_analyzer", SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError(SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style-brief", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    try:
        report = module.validate_style_brief(args.style_brief.resolve(), args.case_dir.resolve(), not args.allow_pending)
    except Exception as exc:
        report = {"schema_id": "cn-patent-drawing-style-brief-validation/v1", "status": "FAIL", "errors": [{"code": "STYLE-BRIEF-INPUT", "message": f"{type(exc).__name__}: {exc}"}]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
