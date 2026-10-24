#!/usr/bin/env python3
"""风格应用器的本地演示入口。

生产流程请直接运行 ``style_applicator.py`` 生成 JSON 风格简报；本文件只用于
开发者快速查看相同数据，避免把演示输出当作起草交接合同。
"""

from __future__ import annotations

import argparse
import json

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "cn-patent-application-creator" / "scripts"))
from style_applicator import build_style_brief, load_style_guide  # noqa: E402
from template_style_contract import StyleGuideValidationError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="风格应用器演示")
    parser.add_argument("--style-guide", help="风格指南 JSON 文件")
    parser.add_argument("--available-features", type=int, default=12)
    parser.add_argument("--available-variations", type=int, default=4)
    parser.add_argument("--available-components", type=int, default=6)
    args = parser.parse_args()

    try:
        guide = load_style_guide(args.style_guide)
        brief = build_style_brief(
            guide,
            available_features=args.available_features,
            available_variations=args.available_variations,
            available_components=args.available_components,
        )
    except (StyleGuideValidationError, ValueError) as exc:
        print(f"错误：{exc}")
        return 2

    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
