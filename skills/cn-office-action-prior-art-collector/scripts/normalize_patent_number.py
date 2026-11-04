#!/usr/bin/env python3
"""专利文献号与申请号规范化工具。

提供中国 (CN)、美国 (US)、世界知识产权组织 (WO/PCT)、欧洲 (EP)、日本 (JP) 等
专利号的清洗、规范化、校验位计算及法律类型推断。
无需任何外部依赖，使用纯 Python 标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量与正则表达式
# ---------------------------------------------------------------------------

_CN_CHECK_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]

_US_APP_RE = re.compile(r"^(US)(\d{4})(\d{1,7})(A\d)?$", re.IGNORECASE)
_US_GRANT_RE = re.compile(r"^(US)(\d{1,8})(B\d|C\d|E\d)?$", re.IGNORECASE)
_WO_PAT_RE = re.compile(r"^(WO)(\d+)([A-Z]\d?)?$", re.IGNORECASE)
_CN_PAT_RE = re.compile(r"^(CN)(\d{12,13})(?:\.(?:\d|X))?([A-Z]\d?)?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 中国专利申请号校验位算法
# ---------------------------------------------------------------------------

def validate_cn_check_digit(main_digits: str, check_char: str) -> bool:
    """验证中国专利申请号校验位是否正确。

    算法规则：
    前 8 位或 12 位纯数字分别乘以固定权重 [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]，
    累加和除以 11 取余数；余数 0-9 对应校验位 '0'-'9'，余数 10 对应校验位 'X'。
    """
    if not main_digits.isdigit() or not check_char:
        return False
    weights = _CN_CHECK_WEIGHTS[:len(main_digits)]
    total = sum(int(d) * w for d, w in zip(main_digits, weights))
    remainder = total % 11
    expected = str(remainder) if remainder < 10 else "X"
    return check_char.upper() == expected


def remove_cn_check_digit(application_number: str) -> str | None:
    """去掉中国专利申请号的校验位，返回纯数字主体（通常为 12 位或 8 位）。

    支持输入形式：
    - 202410391620.6A / 202410391620.6 / CN202410391620.6A / CN 202410361819.4.
    - 202110532557x / 202110532557X (12 位数字 + X 校验位，无小数点)
    - 2024103618194 (13 位纯数字，末位为校验位)
    - 202410361819 (12 位纯数字，无校验位)
    - 9 位纯数字 (2003 年前老格式，含 1 位校验位)
    - 8 位纯数字 (2003 年前老格式，无校验位)
    """
    if not application_number:
        return None
    raw = application_number.strip().upper()
    raw = re.sub(r"^(CN|ZL)\s*", "", raw).strip()
    raw = raw.rstrip(".").strip()
    cleaned = re.sub(r"[^A-Z0-9.]", "", raw).rstrip(".")
    if not cleaned:
        return None

    # 移除 .XA / .6 等后缀
    cleaned = re.sub(r"\.[\dXx][A-Za-z]*$", "", cleaned)

    # 格式：YYYYNNNNNNNN.C → 12 位主体 + 小数点 + 校验位
    dot_match = re.match(r"^(\d{12})\.(\d|X)$", cleaned)
    if dot_match:
        return dot_match.group(1)

    # 12 位主体 + X (校验位无小数点)
    x_match = re.match(r"^(\d{12})[Xx]$", cleaned)
    if x_match:
        return x_match.group(1)

    # 13 位纯数字（12 位主体 + 1 位校验位）
    if re.match(r"^\d{13}$", cleaned):
        return cleaned[:12]

    # 12 位纯数字
    if re.match(r"^\d{12}$", cleaned):
        return cleaned

    # 9 位纯数字（2003 年前格式：8 位主体 + 1 位校验位）
    if re.match(r"^\d{9}$", cleaned):
        return cleaned[:8]

    # 8 位纯数字（2003 年前格式）
    if re.match(r"^\d{8}$", cleaned):
        return cleaned

    return None


# ---------------------------------------------------------------------------
# 各国文献号规范化
# ---------------------------------------------------------------------------

def normalize_us_patent_number(document_id: str) -> str:
    """补齐 US 专利公开号/授权号中缺失的前导零。

    - 申请公开号：US + 4位年份 + 7位序号 + 种类码（如 US2014261802A1 -> US20140261802A1）
    - 授权号：US + 7-8位序号 + 种类码（如 US1234B1 -> US0001234B1）
    """
    match = _US_APP_RE.match(document_id)
    if match and len(match.group(3)) < 7:
        prefix, year, serial, kind = match.groups()
        kind = kind or ""
        return f"{prefix}{year}{serial.zfill(7)}{kind}"
    match = _US_GRANT_RE.match(document_id)
    if match and len(match.group(2)) < 7:
        prefix, serial, kind = match.groups()
        kind = kind or ""
        return f"{prefix}{serial.zfill(7)}{kind}"
    return document_id


def normalize_wo_patent_number(document_id: str) -> str:
    """将 WO/PCT 公开号规范化为四位年份 + 六位序号格式。

    例如：WO0210929A1 -> WO2002010929A1，WO200210929A1 -> WO2002010929A1。
    """
    match = _WO_PAT_RE.match(document_id)
    if not match:
        return document_id
    prefix, digits, kind = match.groups()
    kind = kind or ""
    if len(digits) <= 8:
        if len(digits) in {7, 8} and digits.startswith(("19", "20")) and len(digits) == 8:
            year = digits[:4]
            serial = digits[4:].zfill(6)
            return f"{prefix}{year}{serial}{kind}"
        year = f"20{digits[:2]}"
        serial = digits[2:].zfill(6)
        return f"{prefix}{year}{serial}{kind}"
    if len(digits) in {9, 10} and digits.startswith(("19", "20")):
        year = digits[:4]
        serial = digits[4:].zfill(6)
        return f"{prefix}{year}{serial}{kind}"
    return document_id


def normalize_cn_patent_number(document_id: str) -> str:
    """去掉 CN 专利号中的申请号校验位（13 位数字截为 12 位主体），保持公开号不变。"""
    # CN + 12 位数字 + X
    m_no_dot = re.match(r"^(CN)(\d{12})X$", document_id, re.IGNORECASE)
    if m_no_dot:
        return m_no_dot.group(1) + m_no_dot.group(2)

    match = _CN_PAT_RE.match(document_id)
    if not match:
        return document_id
    prefix, digits, kind_suffix = match.groups()
    kind_suffix = kind_suffix or ""
    if len(digits) == 13:
        return f"{prefix}{digits[:12]}{kind_suffix}"
    return f"{prefix}{digits}{kind_suffix}"


def normalize_patent_number(document_id: str) -> str:
    """统一专利号规范化主入口。

    处理流水线：
    1. 文本预清洗（剥离空格、换行、标点符，去 ZL 前缀，转大写）。
    2. 纯数字形态识别：将 12 位/13 位或 8 位/9 位纯数字识别为中国专利并加上 CN 前缀、去除校验位。
    3. 按国家代码依次执行 US 补齐、WO 年份展开、CN 去除校验位。
    """
    raw = document_id.strip().rstrip(".").strip()
    cleaned = re.sub(r"[^A-Z0-9.]", "", raw.upper()).rstrip(".")
    cleaned = re.sub(r"^ZL", "", cleaned)
    if not cleaned:
        return document_id.strip()

    # 纯数字形态识别（带或不带校验位）
    m_12 = re.match(r"^(\d{12})\.?(\d|X)?$", cleaned, re.IGNORECASE)
    if m_12:
        cleaned = "CN" + m_12.group(1)
    else:
        m_8 = re.match(r"^(\d{8})\.?(\d|X)?$", cleaned, re.IGNORECASE)
        if m_8:
            cleaned = "CN" + m_8.group(1)
        else:
            m_7 = re.match(r"^(\d{7})([ABCUY]\d?)$", cleaned, re.IGNORECASE)
            if m_7:
                cleaned = "CN" + cleaned

    cleaned = normalize_us_patent_number(cleaned)
    cleaned = normalize_wo_patent_number(cleaned)
    cleaned = normalize_cn_patent_number(cleaned)

    return cleaned


# ---------------------------------------------------------------------------
# 格式化与类型推断
# ---------------------------------------------------------------------------

def format_application_number(value: str | None) -> str | None:
    """将中国专利申请号格式化为官方标准显示形态（小数点后至多一位校验位）。

    例如：
    - 202110532557X -> 202110532557.X
    - 2022103804860 -> 202210380486.0
    - 202210380486  -> 20221038048.6 (12 位若为含校验位的完整串则格式化末位)
    - CN 202410361819.4. -> 202410361819.4
    """
    if not value:
        return None

    cleaned = value.strip().upper()
    cleaned = re.sub(r"^(CN|ZL)\s*", "", cleaned).strip()
    cleaned = cleaned.rstrip(".").strip()
    cleaned = re.sub(r"[A-WYZ]$", "", cleaned)

    if "." in cleaned:
        parts = cleaned.split(".")
        main = parts[0].strip()
        check_part = "".join(parts[1:]).strip().rstrip(".")
        if check_part:
            return f"{main}.{check_part[0]}"
        return main

    digits = re.sub(r"[^0-9]", "", cleaned)

    if cleaned.endswith("X") and len(digits) == 12:
        return digits + ".X"

    if len(digits) in {8, 9, 12, 13}:
        return digits[:-1] + "." + digits[-1]

    return cleaned


def infer_patent_type_from_number(document_id: str | None) -> str | None:
    """根据号码特征或文献种类代码推断法律类型（发明专利/实用新型专利/外观设计专利）。

    推断依据：
    1. 中国申请号（12-13 位）第 5 位规则：
       - 1: 发明专利
       - 2: 实用新型专利
       - 3: 外观设计专利
       - 8: 进入中国国家阶段的 PCT 发明申请
       - 9: 进入中国国家阶段的 PCT 实用新型申请
    2. 国别前缀 + 种类代码（Kind Code）：
       - CN/DE/US/WO: A/B/C/E 为发明专利；U/Y 为实用新型专利；S 为外观设计专利；DE T 为发明专利（翻译件）。
    """
    if not document_id:
        return None

    doc_id = document_id.strip().upper()
    prefix_match = re.match(r"^([A-Z]{2})", doc_id)
    prefix = prefix_match.group(1) if prefix_match else "CN"
    if doc_id.startswith("ZL"):
        prefix = "CN"

    digits = re.sub(r"[^0-9]", "", doc_id)
    kind_code_match = re.search(r"([A-Z]{1,2}\d?)$", doc_id)
    kind_code = kind_code_match.group(1) if kind_code_match else None

    # 中国申请号特征
    if prefix == "CN" and len(digits) in {12, 13} and digits.startswith(("19", "20")):
        mapping = {
            "1": "发明专利",
            "2": "实用新型专利",
            "3": "外观设计专利",
            "8": "发明专利",
            "9": "实用新型专利",
        }
        if len(digits) >= 5:
            return mapping.get(digits[4])

    # 种类代码判断
    type_map = {
        "CN": {
            "A": "发明专利", "B": "发明专利", "C": "发明专利",
            "U": "实用新型专利", "Y": "实用新型专利",
            "S": "外观设计专利",
        },
        "DE": {
            "A": "发明专利", "B": "发明专利", "C": "发明专利",
            "T": "发明专利",
            "U": "实用新型专利",
            "S": "外观设计专利",
        },
        "US": {
            "A": "发明专利", "B": "发明专利", "E": "发明专利",
            "S": "外观设计专利",
        },
        "WO": {
            "A": "发明专利",
        },
    }

    if kind_code and prefix in type_map:
        base_kind = kind_code[0]
        return type_map[prefix].get(base_kind)

    return None


def is_likely_application_number(document_id: str) -> bool:
    """判定号码是否更有可能是申请号（而非公开号/公告号）。"""
    if not document_id:
        return False

    clean = re.sub(r"[^A-Z0-9]", "", document_id.upper())
    core = re.sub(r"^(CN|ZL)", "", clean)
    digits_only = re.sub(r"[^0-9]", "", core)

    if len(digits_only) in {8, 9, 12, 13}:
        is_cn_form = not re.sub(r"[0-9.Xx]", "", core)
        if not is_cn_form:
            return False
        if re.search(r"[ABUST]$", clean):
            return False
        return True

    return False


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def process_single_number(number: str) -> dict[str, Any]:
    norm = normalize_patent_number(number)
    is_app = is_likely_application_number(number)
    ptype = infer_patent_type_from_number(number) or infer_patent_type_from_number(norm)
    fmt_app = format_application_number(number) if is_app else None

    # 如果是申请号且能提取出主体与校验位，验证校验位
    check_valid: bool | None = None
    clean_digits = re.sub(r"[^0-9X]", "", number.upper())
    clean_digits = re.sub(r"^(CN|ZL)", "", clean_digits)
    if is_app and len(clean_digits) in {9, 13}:
        main = clean_digits[:-1]
        chk = clean_digits[-1]
        check_valid = validate_cn_check_digit(main, chk)

    return {
        "raw_input": number,
        "normalized": norm,
        "is_application_number": is_app,
        "formatted_application_number": fmt_app,
        "patent_type": ptype,
        "check_digit_valid": check_valid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="专利文献号与申请号规范化、校验与类型推断工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("numbers", nargs="*", help="待规范化的专利号或申请号（支持多个）")
    parser.add_argument("-f", "--file", help="从文本文件逐行读取号码")
    parser.add_argument("-o", "--output", help="输出结果 JSON 文件路径（默认输出至 stdout）")
    parser.add_argument("--compact", action="store_true", help="紧凑 JSON 输出")

    args = parser.parse_args()

    input_list: list[str] = list(args.numbers) if args.numbers else []
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"错误: 文件未找到: {args.file}", file=sys.stderr)
            return 1
        for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                input_list.append(line_str)

    if not input_list and not sys.stdin.isatty():
        for line in sys.stdin.read().splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                input_list.append(line_str)

    if not input_list:
        parser.print_help()
        return 0

    results = [process_single_number(n) for n in input_list]
    payload = results[0] if len(results) == 1 else results
    indent = None if args.compact else 2
    output_str = json.dumps(payload, ensure_ascii=False, indent=indent)

    if args.output:
        Path(args.output).write_text(output_str, encoding="utf-8")
    else:
        print(output_str)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
