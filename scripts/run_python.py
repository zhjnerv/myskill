#!/usr/bin/env python3
"""使用项目一键安装环境执行仓库内 Python 脚本。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：run_python.py <仓库内脚本> [参数...]", file=sys.stderr)
        return 3
    root = Path(__file__).resolve().parents[1]
    target = Path(sys.argv[1]).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        print(f"拒绝执行仓库外脚本：{target}", file=sys.stderr)
        return 3
    if not target.is_file():
        print(f"脚本不存在：{target}", file=sys.stderr)
        return 3
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print(
            f"项目虚拟环境不存在：{python}；请先运行 python3 {root / 'scripts/install_codex_skill.py'}",
            file=sys.stderr,
        )
        return 3
    os.execv(str(python), [str(python), str(target), *sys.argv[2:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
