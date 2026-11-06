#!/usr/bin/env python3
"""自包含轻量单元测试套件。

覆盖：
1. 专利文献号与申请号清洗、规范化、校验位及类型推断
2. 审查意见通知书（OA）结构化提取、正文审查意见与第5栏对比文件解析
3. 自由资料文本对比文件号召回与抗噪过滤
4. DOCX/纯文本/BOM 文件格式解析
5. 公开下载链接与 Espacenet 备用链接构造、演练（dry-run）模式

全部使用 Python 标准库 unittest，无外部依赖。
"""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

# 将脚本目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_citations import (
    build_citation_context,
    extract_patent_ids_free_text,
    extract_text_from_docx_bytes,
    extract_text_from_plain_bytes,
    parse_free_document_structure,
    parse_office_action_structure,
)
from fetch_patent_documents import (
    build_espacenet_publication_url,
    get_candidate_pdf_urls,
    process_citations_packet,
)
from normalize_patent_number import (
    format_application_number,
    infer_patent_type_from_number,
    is_likely_application_number,
    normalize_cn_patent_number,
    normalize_patent_number,
    normalize_us_patent_number,
    normalize_wo_patent_number,
    remove_cn_check_digit,
    validate_cn_check_digit,
)


class TestPatentNumberNormalization(unittest.TestCase):
    def test_us_normalization(self):
        self.assertEqual(normalize_us_patent_number("US2014261802A1"), "US20140261802A1")
        self.assertEqual(normalize_us_patent_number("US20140261802A1"), "US20140261802A1")
        self.assertEqual(normalize_us_patent_number("US1234B1"), "US0001234B1")
        self.assertEqual(normalize_us_patent_number("WO200210929A1"), "WO200210929A1")

    def test_wo_normalization(self):
        self.assertEqual(normalize_wo_patent_number("WO0210929A1"), "WO2002010929A1")
        self.assertEqual(normalize_wo_patent_number("WO0200001A1"), "WO2002000001A1")
        self.assertEqual(normalize_wo_patent_number("WO200210929A1"), "WO2002010929A1")
        self.assertEqual(normalize_wo_patent_number("CN118161961A"), "CN118161961A")

    def test_cn_normalization(self):
        self.assertEqual(normalize_cn_patent_number("CN2024103618194"), "CN202410361819")
        self.assertEqual(normalize_cn_patent_number("CN202410361819.4"), "CN202410361819")
        self.assertEqual(normalize_cn_patent_number("CN2024103618194A"), "CN202410361819A")
        self.assertEqual(normalize_cn_patent_number("CN118161961A"), "CN118161961A")

    def test_combined_normalization(self):
        self.assertEqual(normalize_patent_number("WO0210929A1"), "WO2002010929A1")
        self.assertEqual(normalize_patent_number("US2014261802A1"), "US20140261802A1")
        self.assertEqual(normalize_patent_number("US10,357,123B2"), "US10357123B2")
        self.assertEqual(normalize_patent_number("US 10,123,456 B2"), "US10123456B2")
        self.assertEqual(normalize_patent_number("WO 2020/123456 A1"), "WO2020123456A1")
        self.assertEqual(normalize_patent_number("CN 1123456 C"), "CN1123456C")
        self.assertEqual(normalize_patent_number("202210380486.0"), "CN202210380486")
        self.assertEqual(normalize_patent_number("202110532557x"), "CN202110532557")
        self.assertEqual(normalize_patent_number("ZL202110532557.X"), "CN202110532557")
        self.assertEqual(normalize_patent_number(" cn 206211640 U "), "CN206211640U")
        self.assertEqual(normalize_patent_number("202110 532557.X"), "CN202110532557")
        self.assertEqual(normalize_patent_number("【202110532557.X】"), "CN202110532557")
        self.assertEqual(normalize_patent_number("CN 202410361819.4."), "CN202410361819")
        self.assertEqual(normalize_patent_number("US10,357,123B2."), "US10357123B2")

    def test_validate_cn_check_digit(self):
        self.assertTrue(validate_cn_check_digit("202410361819", "4"))
        self.assertFalse(validate_cn_check_digit("202410361819", "0"))
        self.assertTrue(validate_cn_check_digit("202410391620", "6"))
        self.assertTrue(validate_cn_check_digit("202210380486", "0"))
        self.assertTrue(validate_cn_check_digit("202110532557", "X"))
        self.assertFalse(validate_cn_check_digit("202110532557", "1"))

    def test_remove_cn_check_digit(self):
        self.assertEqual(remove_cn_check_digit("202410391620.6A"), "202410391620")
        self.assertEqual(remove_cn_check_digit("202410391620.6"), "202410391620")
        self.assertEqual(remove_cn_check_digit("CN 202410361819.4."), "202410361819")
        self.assertEqual(remove_cn_check_digit("202410361819.4."), "202410361819")
        self.assertEqual(remove_cn_check_digit("202110532557x"), "202110532557")
        self.assertEqual(remove_cn_check_digit("2022103804860"), "202210380486")
        self.assertEqual(remove_cn_check_digit("202210380486"), "202210380486")
        self.assertIsNone(remove_cn_check_digit("invalid"))

    def test_format_application_number(self):
        self.assertEqual(format_application_number("202110532557X"), "202110532557.X")
        self.assertEqual(format_application_number("2022103804860"), "202210380486.0")
        self.assertEqual(format_application_number("202110532557.X"), "202110532557.X")
        self.assertEqual(format_application_number("CN 202410361819.4."), "202410361819.4")
        self.assertEqual(format_application_number("CN202410361819.4."), "202410361819.4")
        self.assertEqual(format_application_number(" 202410361819.4."), "202410361819.4")
        self.assertEqual(format_application_number("ZL 202110532557.X."), "202110532557.X")
        self.assertIsNone(format_application_number(None))

    def test_infer_patent_type(self):
        self.assertEqual(infer_patent_type_from_number("202110532557.X"), "发明专利")
        self.assertEqual(infer_patent_type_from_number("202220380486.0"), "实用新型专利")
        self.assertEqual(infer_patent_type_from_number("202330123456.7"), "外观设计专利")
        self.assertEqual(infer_patent_type_from_number("CN206211640U"), "实用新型专利")
        self.assertEqual(infer_patent_type_from_number("US20140261802A1"), "发明专利")

    def test_is_likely_application_number(self):
        self.assertTrue(is_likely_application_number("202410361819.4"))
        self.assertTrue(is_likely_application_number("CN202110532557.X"))
        self.assertFalse(is_likely_application_number("CN114528944A"))
        self.assertFalse(is_likely_application_number("US20200234567A1"))


class TestCitationExtractor(unittest.TestCase):
    def test_parse_office_action_structure(self):
        sample_oa = """
发文日：2025 年07 月25 日
申请号：202210380486.0
申请人：宁波示例电器有限公司
发明创造名称：粉囊包咖啡机的自动掉包装置
第一次审查意见通知书

5. 本通知书是在进行了检索的情况下作出的。
本通知书引用下列对比文件(其编号在今后的审查过程中继续沿用)：
CN114528944A
CN113159095B

6.审查的结论性意见：
权利要求1-2不具备创造性。

本申请涉及一种粉囊包咖啡机的自动掉包装置，经审查，现提出以下审查意见。
1. 权利要求1-2不符合专利法第二十二条第三款的规定，不具备创造性。
审查员姓名:李四

检索报告
CN999999999A
""".strip()
        parsed = parse_office_action_structure(sample_oa)
        self.assertEqual(parsed["mode"], "office_action")
        self.assertEqual(parsed["bibliographic_items"]["application_number"], "202210380486.0")
        self.assertEqual(parsed["bibliographic_items"]["title"], "粉囊包咖啡机的自动掉包装置")
        self.assertEqual(parsed["bibliographic_items"]["notice_title"], "第一次审查意见通知书")
        self.assertEqual(parsed["bibliographic_items"]["patent_type"], "发明专利")

        cited_ids = [c["document_id"] for c in parsed["cited_documents"]]
        self.assertEqual(cited_ids, ["CN114528944A", "CN113159095B"])
        # 确保检索报告中的文献被排除
        self.assertNotIn("CN999999999A", cited_ids)

        self.assertEqual(len(parsed["objections"]), 1)
        self.assertEqual(parsed["objections"][0]["claim_numbers"], [1, 2])
        self.assertEqual(parsed["objections"][0]["legal_basis"], "专利法第二十二条第三款")
        self.assertTrue(parsed["bibliographic_items"]["check_digit_valid"])

    def test_objection_splitting_single_newline_and_scope(self):
        """测试单换行排版下多条审查意见被正确拆分，且 raw_text 不包含全文。"""
        sample_text = """
申请号：202210380486.0
发明创造名称：粉囊包咖啡机的自动掉包装置
第一次审查意见通知书
5. 本通知书引用下列对比文件：
CN114528944A
6. 审查结论
审查意见：
1. 权利要求1-3不具备专利法第22条第3款规定的创造性。对比文件1公开了……
2. 权利要求4不符合专利法第26条第4款的规定。
""".strip()
        parsed = parse_office_action_structure(sample_text)
        objections = parsed["objections"]
        self.assertEqual(len(objections), 2)

        obj1 = objections[0]
        self.assertEqual(obj1["objection_id"], "OBJ-1")
        self.assertEqual(obj1["claim_numbers"], [1, 2, 3])
        self.assertEqual(obj1["legal_basis"], "专利法第22条第3款")
        self.assertEqual(obj1["raw_text"], "1. 权利要求1-3不具备专利法第22条第3款规定的创造性。对比文件1公开了……")
        self.assertNotIn("权利要求4", obj1["raw_text"])
        self.assertNotIn("审查意见：", obj1["raw_text"])

        obj2 = objections[1]
        self.assertEqual(obj2["objection_id"], "OBJ-2")
        self.assertEqual(obj2["claim_numbers"], [4])
        self.assertEqual(obj2["legal_basis"], "专利法第26条第4款")
        self.assertEqual(obj2["raw_text"], "2. 权利要求4不符合专利法第26条第4款的规定。")
        self.assertNotIn("权利要求1-3", obj2["raw_text"])

    def test_mailing_date_fallback_ignores_section_five_and_citation_dates(self):
        """测试发文日无前缀回退时，严禁拾取第5栏或含公开日/对比文件行的日期；确定不了时返回 None。"""
        # 情况 A: 正文第5栏包含公开日，封面无发文日 -> 应返回 None
        text_no_date = """
申请号：202210380486.0
发明创造名称：测试装置
第一次审查意见通知书
5. 本通知书引用下列对比文件：
CN114528944A 公开日：2022年05月10日
6. 结论
审查意见：
1. 权利要求1不具备新颖性。
""".strip()
        parsed_no = parse_office_action_structure(text_no_date)
        self.assertIsNone(parsed_no["bibliographic_items"]["mailing_date"])

        # 情况 B: 封面首行无前缀日期，但第5栏有对比文件公开日 -> 应正确拾取封面首行日期
        text_with_front_date = """
2025年07月25日
申请号：202210380486.0
发明创造名称：测试装置
第一次审查意见通知书
5. 本通知书引用下列对比文件：
CN114528944A 公开日：2022年05月10日
6. 结论
审查意见：
1. 权利要求1不具备新颖性。
""".strip()
        parsed_with = parse_office_action_structure(text_with_front_date)
        self.assertEqual(parsed_with["bibliographic_items"]["mailing_date"], "2025年07月25日")

    def test_check_digit_valid_in_bibliographic(self):
        """测试著录项中直接提供 check_digit_valid 字段。"""
        # 正确校验位
        t_valid = "申请号：202210380486.0\n第一次审查意见通知书\n"
        self.assertTrue(parse_office_action_structure(t_valid)["bibliographic_items"]["check_digit_valid"])

        # 错误校验位
        t_invalid = "申请号：202210380486.9\n第一次审查意见通知书\n"
        self.assertFalse(parse_office_action_structure(t_invalid)["bibliographic_items"]["check_digit_valid"])

        # 无校验位纯 12 位
        t_none = "申请号：202210380486\n第一次审查意见通知书\n"
        self.assertIsNone(parse_office_action_structure(t_none)["bibliographic_items"]["check_digit_valid"])

    def test_expanded_body_start_markers(self):
        """测试扩充后的正文起点标记（具体意见如下 / 一、审查意见 / 审查意见:）。"""
        for marker in ("一、审查意见", "具体意见如下", "审查意见:"):
            sample = f"""
申请号：202210380486.0
第一次审查意见通知书
5. 本通知书引用下列对比文件：
CN114528944A
6. 结论
{marker}
1. 权利要求1不符合专利法第22条第2款规定，不具备新颖性。
"""
            parsed = parse_office_action_structure(sample)
            self.assertEqual(len(parsed["objections"]), 1, f"Failed on marker: {marker}")
            self.assertEqual(parsed["objections"][0]["claim_numbers"], [1])
            self.assertIn("不具备新颖性", parsed["objections"][0]["raw_text"])

    def test_free_text_extraction_and_noise_filtering(self):
        text = (
            "本方案参考了 CN114528944A 和 CN113159095B 的公开文本，"
            "对照 US20200234567A1，以及 WO2019123456A1 的记载。"
            "设备型号 CN12345 的传感器不可识别。"
            "截至 US2024 年的统计。"
            "本案申请号 202210380486.5 对应公开文本。"
        )
        ids = extract_patent_ids_free_text(text)
        self.assertIn("CN114528944A", ids)
        self.assertIn("CN113159095B", ids)
        self.assertIn("US20200234567A1", ids)
        self.assertIn("WO2019123456A1", ids)

        # 误命中过滤验证
        self.assertFalse(any(x.startswith("CN12345") for x in ids))
        self.assertFalse(any(x.startswith("US2024") for x in ids))

        parsed = parse_free_document_structure("交底书.md", text)
        self.assertEqual(parsed["mode"], "free_text")
        self.assertEqual(len(parsed["cited_documents"]), len(ids))

    def test_free_text_email_with_special_formats(self):
        """测试包含带逗号 US 号、带斜杠 WO 号、7位早期 CN 号及本案申请号提取与抗噪。"""
        email_text = (
            "Dear colleague, regarding the opposition we rely on US 10,123,456 B2 "
            "and the Chinese granted patent CN 1123456 C, as well as WO 2020/123456 A1. "
            "Please also note the product model CN12345 and our internal ref US-2024-07 "
            "are not patents. The client's own application is CN 202410361819.4."
        )
        parsed = parse_free_document_structure("email.txt", email_text)
        self.assertEqual(parsed["mode"], "free_text")

        # 著录项提取本案申请号及校验位有效性
        self.assertEqual(parsed["bibliographic_items"]["application_number"], "202410361819.4")
        self.assertTrue(parsed["bibliographic_items"]["check_digit_valid"])

        # 对比文件列表
        cited_ids = [c["document_id"] for c in parsed["cited_documents"]]
        self.assertIn("US10123456B2", cited_ids)
        self.assertIn("CN1123456C", cited_ids)
        self.assertIn("WO2020123456A1", cited_ids)
        self.assertEqual(len(cited_ids), 3)

        # 严格拦截干扰项与本案申请号混入
        self.assertNotIn("CN12345", cited_ids)
        self.assertNotIn("US-2024-07", cited_ids)
        self.assertNotIn("CN202410361819", cited_ids)
        self.assertNotIn("202410361819.4", cited_ids)

    def test_section_five_special_formats(self):
        """测试通知书第 5 栏带逗号 US 号、带斜杠 WO 号、7位早期 CN 号及末尾标点清洗。"""
        sample_oa = """
申请号：202410361819.4
发明创造名称：测试申请
第一次审查意见通知书

5. 本通知书引用下列对比文件：
US 10,123,456 B2
US10,357,123B2
CN 1123456 C
WO 2020/123456 A1
CN114528944A.
CN12345
US-2024-07

6. 结论
审查意见：
1. 权利要求1不具备新颖性。
""".strip()
        parsed = parse_office_action_structure(sample_oa)
        cited_ids = [c["document_id"] for c in parsed["cited_documents"]]
        self.assertIn("US10123456B2", cited_ids)
        self.assertIn("US10357123B2", cited_ids)
        self.assertIn("CN1123456C", cited_ids)
        self.assertIn("WO2020123456A1", cited_ids)
        self.assertIn("CN114528944A", cited_ids)
        self.assertNotIn("CN12345", cited_ids)
        self.assertNotIn("US-2024-07", cited_ids)

    def test_punctuation_stripping(self):
        """测试句末粘连句号被正确剥离。"""
        text = "The application is CN 202410361819.4. Cited document is US10,357,123B2."
        parsed = parse_free_document_structure("doc.txt", text)
        self.assertEqual(parsed["bibliographic_items"]["application_number"], "202410361819.4")
        self.assertFalse(parsed["bibliographic_items"]["application_number"].endswith("."))
        cited_ids = [c["document_id"] for c in parsed["cited_documents"]]
        self.assertEqual(cited_ids, ["US10357123B2"])

    def test_file_parsers(self):
        # 1. UTF-8 带 BOM
        bom_bytes = b"\xef\xbb\xbf\xe4\xb8\xad\xe6\x96\x87\xe6\xb5\x8b\xe8\xaf\x95"
        self.assertEqual(extract_text_from_plain_bytes(bom_bytes), "中文测试")

        # 2. GBK
        gbk_bytes = "中文GBK测试".encode("gbk")
        self.assertEqual(extract_text_from_plain_bytes(gbk_bytes), "中文GBK测试")

        # 3. 内存构建最小 DOCX 测试
        docx_buffer = io.BytesIO()
        with zipfile.ZipFile(docx_buffer, "w") as zf:
            xml_content = (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b'<w:body>'
                b'<w:p><w:r><w:t>DOCX\xe6\xb5\x8b\xe8\xaf\x95\xe6\xae\xb5\xe8\x90\xbd</w:t></w:r></w:p>'
                b'</w:body>'
                b'</w:document>'
            )
            zf.writestr("word/document.xml", xml_content)
        extracted_docx = extract_text_from_docx_bytes(docx_buffer.getvalue())
        self.assertIn("DOCX测试段落", extracted_docx)


class TestDocumentFetcher(unittest.TestCase):
    def test_build_espacenet_url(self):
        url_cn = build_espacenet_publication_url("CN114528944A")
        self.assertIn("worldwide.espacenet.com", url_cn)
        self.assertIn("CC=CN", url_cn)
        self.assertIn("NR=114528944A", url_cn)
        self.assertIn("KC=A", url_cn)

        url_us = build_espacenet_publication_url("US20200234567A1")
        self.assertIn("CC=US", url_us)
        self.assertIn("KC=A1", url_us)

    def test_build_espacenet_url_for_cn_application(self):
        """测试中国申请号（12-13位纯数字或含小数点）返回检索链接而非 None。"""
        url_dot = build_espacenet_publication_url("202410361819.4")
        self.assertEqual(url_dot, "https://worldwide.espacenet.com/patent/search?q=CN202410361819")

        url_prefix = build_espacenet_publication_url("CN 202410361819.4.")
        self.assertEqual(url_prefix, "https://worldwide.espacenet.com/patent/search?q=CN202410361819")

        url_13 = build_espacenet_publication_url("2024103618194")
        self.assertEqual(url_13, "https://worldwide.espacenet.com/patent/search?q=CN202410361819")

        url_12 = build_espacenet_publication_url("202410361819")
        self.assertEqual(url_12, "https://worldwide.espacenet.com/patent/search?q=CN202410361819")

        # 普通公开号仍生成 publicationDetails
        url_pub = build_espacenet_publication_url("CN1123456C")
        self.assertIn("publicationDetails", url_pub)
        self.assertIn("NR=1123456C", url_pub)

    def test_candidate_pdf_urls(self):
        urls = get_candidate_pdf_urls("CN114528944A", direct_url="https://example.com/direct.pdf")
        self.assertEqual(urls[0], "https://example.com/direct.pdf")
        self.assertIn("https://patents.google.com/patent/CN114528944A/zh.pdf", urls)
        self.assertIn("https://patents.google.com/patent/CN114528944A/en.pdf", urls)

    def test_process_citations_packet_dry_run(self):
        packet = {
            "bibliographic_items": {
                "application_number": "202210380486.0",
                "title": "测试专利",
            },
            "cited_documents": [
                {"label": "对比文件1", "document_id": "CN114528944A", "role": "prior_art"},
                {"label": "对比文件2", "document_id": "US20200234567A1", "role": "prior_art"},
            ],
        }
        res = process_citations_packet(packet, output_dir="./downloads", dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["status"], "complete")
        self.assertEqual(len(res["prior_art_documents"]), 2)
        self.assertTrue(res["prior_art_documents"][0]["ok"])
        self.assertEqual(
            Path("downloads") / "prior_art" / "CN114528944A.pdf",
            Path(res["prior_art_documents"][0]["target_path"]),
        )


if __name__ == "__main__":
    unittest.main()
