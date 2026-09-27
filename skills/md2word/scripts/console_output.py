#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台输出兼容层，避免状态图标在旧 Windows 代码页下中断转换。"""

import sys


def configure_console_output():
    """保留当前控制台编码，并将无法编码的字符转为 ASCII 转义序列。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            # 非标准流或旧 Python 环境没有 reconfigure 时保持原行为。
            continue


configure_console_output()
