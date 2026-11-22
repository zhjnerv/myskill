#!/usr/bin/env python3
"""公开专利文献与申请公开文本检索与下载工具。

核心功能：
1. 中国专利申请号解析：基于 Google Patents 公开检索接口，根据申请号（自动剔除校验位）
   解析获取对应的公开文献号（Publication Number）、标题、申请人及公开日。
2. 专利文献 PDF 下载：按公开号从 Google Patents 官方存储/页面自动获取中文版或英文版
   授权/公开说明书 PDF，严格校验 %PDF- 字节头及文件长度，支持超时控制与重试机制。
3. 官方查阅备用链接生成：当公开源缺少 PDF 或下载受阻时，自动生成对应国家文献的
   Espacenet (欧洲专利局) 官方详情页入口，方便用户手动查阅或下载。
4. 对接提取清单：可直接读取 extract_citations.py 输出的 JSON，批量处理案卷本案公开文本
   与所有对比文件。

完全使用 Python 标准库（urllib.request、json、argparse），无需额外安装第三方依赖。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# 允许从当前脚本同级目录导入 normalize_patent_number
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from normalize_patent_number import (  # noqa: E402
    normalize_patent_number,
    remove_cn_check_digit,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

GOOGLE_PATENTS_XHR_ENDPOINT = "https://patents.google.com/xhr/query"
GOOGLE_PATENTS_SEARCH_URL_TEMPLATE = "https://patents.google.com/?q={query}"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# 链接构造工具
# ---------------------------------------------------------------------------

def build_espacenet_publication_url(document_id: str | None) -> str | None:
    """按公开号或中国申请号生成 Espacenet 官方检索/文献详情页链接。

    支持 CN、US、EP、WO、DE、JP 等国家代码。
    例如：
    - CN114528944A -> https://worldwide.espacenet.com/publicationDetails/biblio?CC=CN&NR=114528944A&KC=A&FT=D
    - 中国申请号（12~13 位数字或 20xxxxxxxxxx.x）-> https://worldwide.espacenet.com/patent/search?q=CN{12位申请号主体}
    """
    if not document_id:
        return None
    raw = document_id.strip().rstrip(".")
    # 中国申请号优先识别（12~13 位数字或 20xxxxxxxxxx.x）
    cn_main = remove_cn_check_digit(raw)
    if cn_main and len(cn_main) == 12:
        return f"https://worldwide.espacenet.com/patent/search?q=CN{cn_main}"

    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    match = re.match(r"^([A-Z]{2})(\d+)([A-Z]\d?)?$", cleaned)
    if not match:
        return None
    country_code, number, kind_code = match.groups()
    kind_code = kind_code or ""
    query = urlencode({
        "CC": country_code,
        "NR": f"{number}{kind_code}",
        "KC": kind_code,
        "FT": "D",
    })
    return f"https://worldwide.espacenet.com/publicationDetails/biblio?{query}"


def get_candidate_pdf_urls(document_id: str, direct_url: str | None = None) -> list[str]:
    """生成待尝试的公开 PDF 下载链接列表。"""
    normalized = normalize_patent_number(document_id).strip().upper()
    urls: list[str] = []
    if direct_url:
        urls.append(direct_url.strip())
    # 优先中文，其次英文
    urls.append(f"https://patents.google.com/patent/{normalized}/zh.pdf")
    urls.append(f"https://patents.google.com/patent/{normalized}/en.pdf")
    return urls


# ---------------------------------------------------------------------------
# 申请号检索公开号 (Google Patents XHR)
# ---------------------------------------------------------------------------

def resolve_cn_application_number(
    application_number: str,
    timeout_seconds: int = 30,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """通过 Google Patents 检索申请号（自动剥离校验位）获取公开文献号及著录信息。"""
    normalized = application_number.strip()
    if not normalized:
        raise ValueError("申请号为空，无法检索公开文献号")

    search_query = remove_cn_check_digit(normalized)
    if not search_query:
        raise ValueError(f"申请号格式无法识别校验位: {normalized}")

    def _execute_query(q: str) -> dict[str, Any]:
        encoded_q = quote(f"({q})")
        url = f"{GOOGLE_PATENTS_XHR_ENDPOINT}?url=q%3D{encoded_q}&exp=&tags="
        req = Request(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://patents.google.com/",
            },
        )
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with urlopen(req, timeout=timeout_seconds) as resp:
                    data = resp.read().decode("utf-8")
                    return json.loads(data)
            except HTTPError as exc:
                if exc.code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                    time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
                    continue
                raise RuntimeError(f"Google Patents 请求失败: HTTP {exc.code}") from exc
            except (TimeoutError, socket.timeout, URLError) as exc:
                last_err = exc
                if attempt < max_attempts:
                    time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
                    continue
                raise RuntimeError(f"Google Patents 网络连接超时/失败: {exc}") from exc
        if last_err:
            raise RuntimeError(f"Google Patents 网络连接失败: {last_err}") from last_err
        raise RuntimeError("Google Patents 请求未返回数据")

    # 尝试 1: 纯数字或原始查询主体
    response = _execute_query(search_query)
    clusters = response.get("results", {}).get("cluster", [])

    # 尝试 2: 若纯数字未搜到，加 CN 前缀再试
    if not clusters and search_query.isdigit():
        response = _execute_query(f"CN{search_query}")
        clusters = response.get("results", {}).get("cluster", [])

    if not clusters:
        raise RuntimeError(f"Google Patents 未找到申请号 {application_number} 对应的公开文献")

    result_list = clusters[0].get("result", [])
    if not result_list:
        raise RuntimeError(f"Google Patents 检索结果列表为空: {application_number}")

    patent = result_list[0].get("patent", {})
    pub_number = patent.get("publication_number", "").strip()
    if not pub_number:
        raise RuntimeError(f"Google Patents 未返回公开号: {application_number}")

    pdf_path = patent.get("pdf")
    pdf_url = f"https://patentimages.storage.googleapis.com/{pdf_path}" if pdf_path else None

    return {
        "ok": True,
        "application_number": normalized,
        "search_query": search_query,
        "publication_number": pub_number,
        "title": patent.get("title"),
        "applicant": patent.get("assignee"),
        "inventor": patent.get("inventor"),
        "publication_date": patent.get("publication_date"),
        "direct_pdf_url": pdf_url,
        "source_url": GOOGLE_PATENTS_SEARCH_URL_TEMPLATE.format(query=quote(search_query)),
        "espacenet_url": build_espacenet_publication_url(pub_number),
    }


# ---------------------------------------------------------------------------
# PDF 下载执行
# ---------------------------------------------------------------------------

def query_google_patents_pdf_url(document_id: str, timeout_seconds: int = 10) -> str | None:
    """尝试通过 Google Patents XHR 查询文献在 Google Cloud Storage 中的直接 PDF 路径。"""
    try:
        encoded_q = quote(f"({document_id})")
        url = f"{GOOGLE_PATENTS_XHR_ENDPOINT}?url=q%3D{encoded_q}&exp=&tags="
        req = Request(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "*/*",
                "Referer": "https://patents.google.com/",
            },
        )
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            clusters = data.get("results", {}).get("cluster", [])
            if clusters:
                results = clusters[0].get("result", [])
                if results:
                    pdf_path = results[0].get("patent", {}).get("pdf")
                    if pdf_path:
                        return f"https://patentimages.storage.googleapis.com/{pdf_path}"
    except Exception:
        pass
    return None


def download_patent_pdf(
    document_id: str,
    output_dir: Path | str,
    direct_url: str | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> dict[str, Any]:
    """下载指定专利文献的 PDF 说明书。

    校验规则：
    - HTTP 状态码 200
    - 返回字节流以 b"%PDF-" 开头（防止把 404 / 验证码 HTML 误存为 PDF）
    - 文件长度大于 1000 字节
    """
    normalized = normalize_patent_number(document_id).strip().upper()
    out_dir = Path(output_dir)
    target_path = out_dir / f"{normalized}.pdf"

    # 若未指定直接下载直链，先尝试通过 XHR 查询官方直存 CDN 路径
    if not direct_url and not dry_run:
        direct_url = query_google_patents_pdf_url(normalized, timeout_seconds=min(10, timeout_seconds))

    candidate_urls = get_candidate_pdf_urls(normalized, direct_url)
    espacenet_url = build_espacenet_publication_url(normalized)

    if dry_run:
        return {
            "document_id": normalized,
            "ok": True,
            "dry_run": True,
            "target_path": str(target_path),
            "candidate_urls": candidate_urls,
            "fallback_url": espacenet_url,
            "error_message": None,
        }

    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://patents.google.com/",
    }

    last_error: str | None = None

    for url in candidate_urls:
        req = Request(url, headers=headers)
        for attempt in range(1, max_retries + 2):
            try:
                with urlopen(req, timeout=timeout_seconds) as resp:
                    status = getattr(resp, "status", 200)
                    if status == 200:
                        content = resp.read()
                        if content.startswith(b"%PDF-") and len(content) > 1000:
                            target_path.write_bytes(content)
                            return {
                                "document_id": normalized,
                                "ok": True,
                                "dry_run": False,
                                "target_path": str(target_path),
                                "file_size_bytes": len(content),
                                "source_url": url,
                                "fallback_url": espacenet_url,
                                "error_message": None,
                            }
                        last_error = f"返回内容非有效 PDF（长度: {len(content)} 字节）"
            except HTTPError as exc:
                if exc.code in RETRYABLE_STATUS_CODES and attempt <= max_retries:
                    time.sleep((2 ** attempt) + random.uniform(0.5, 1.0))
                    continue
                if exc.code == 404:
                    last_error = f"HTTP 404: {url}"
                    break
                last_error = f"HTTP {exc.code}: {url}"
            except Exception as exc:
                last_error = f"网络请求异常: {exc}"
                if attempt <= max_retries:
                    time.sleep(1.0)
                    continue
                break

    return {
        "document_id": normalized,
        "ok": False,
        "dry_run": False,
        "target_path": None,
        "file_size_bytes": None,
        "source_url": None,
        "fallback_url": espacenet_url,
        "error_message": last_error or "未找到可用 PDF 文件",
    }


# ---------------------------------------------------------------------------
# 批量与案卷模式调度
# ---------------------------------------------------------------------------

def process_citations_packet(
    packet_data: dict[str, Any],
    output_dir: Path | str,
    dry_run: bool = False,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """读取 extract_citations.py 生成的 JSON 数据包，自动完成本案公开检索与对比文件取材。"""
    out_dir = Path(output_dir)
    biblio = packet_data.get("bibliographic_items", {})
    app_num = biblio.get("application_number")

    app_resolution: dict[str, Any] | None = None
    app_download: dict[str, Any] | None = None

    # 1. 尝试检索并补齐本案申请公开文本
    if app_num:
        try:
            if dry_run:
                app_resolution = {
                    "ok": True,
                    "application_number": app_num,
                    "dry_run": True,
                    "note": "dry-run: 跳过实际公开号网络查询",
                }
            else:
                app_resolution = resolve_cn_application_number(app_num, timeout_seconds=timeout_seconds)
                pub_num = app_resolution.get("publication_number")
                direct_pdf = app_resolution.get("direct_pdf_url")
                if pub_num:
                    app_download = download_patent_pdf(
                        pub_num,
                        output_dir=out_dir / "application",
                        direct_url=direct_pdf,
                        dry_run=dry_run,
                        timeout_seconds=timeout_seconds,
                    )
        except Exception as exc:
            app_resolution = {
                "ok": False,
                "application_number": app_num,
                "error": str(exc),
                "fallback_url": build_espacenet_publication_url(app_num),
            }

    # 2. 依次下载各对比文件
    cited_docs = packet_data.get("cited_documents", [])
    prior_art_results: list[dict[str, Any]] = []

    for idx, item in enumerate(cited_docs):
        doc_id = item.get("document_id")
        if not doc_id:
            continue
        # 避免并发限流，真实下载时适当引入间隔
        if not dry_run and idx > 0:
            time.sleep(random.uniform(1.0, 2.0))

        res = download_patent_pdf(
            doc_id,
            output_dir=out_dir / "prior_art",
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )
        res["label"] = item.get("label", f"对比文件{idx + 1}")
        res["role"] = item.get("role", "prior_art")
        res["raw_context"] = item.get("raw_context", "")
        prior_art_results.append(res)

    success_count = sum(1 for r in prior_art_results if r.get("ok"))
    total_count = len(prior_art_results)

    return {
        "status": "complete" if success_count == total_count else "partial",
        "dry_run": dry_run,
        "application_resolution": app_resolution,
        "application_download": app_download,
        "prior_art_documents": prior_art_results,
        "stats": {
            "total_prior_art": total_count,
            "success_prior_art": success_count,
            "failed_prior_art": total_count - success_count,
        },
    }


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="专利文献 PDF 下载与公开号检索工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("patent_ids", nargs="*", help="待检索/下载的专利公开号或申请号")
    parser.add_argument("--from-json", help="extract_citations.py 输出的 JSON 文件路径")
    parser.add_argument("-o", "--output-dir", default="./downloads", help="PDF 文件保存根目录 (默认: ./downloads)")
    parser.add_argument("--resolve-app", action="store_true", help="将输入的号码作为申请号解析公开号")
    parser.add_argument("--dry-run", action="store_true", help="演练模式：仅生成候选链接与备用链接，不发起真实下载")
    parser.add_argument("--timeout", type=int, default=30, help="网络请求超时秒数 (默认: 30)")
    parser.add_argument("--compact", action="store_true", help="紧凑 JSON 输出")

    args = parser.parse_args()

    # 模式 A: 从 extract_citations.py 的 JSON 导入
    if args.from_json:
        json_path = Path(args.from_json)
        if not json_path.exists():
            print(f"错误: JSON 文件不存在: {args.from_json}", file=sys.stderr)
            return 1
        data = json.loads(json_path.read_text(encoding="utf-8"))
        result = process_citations_packet(
            data,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout,
        )
        indent = None if args.compact else 2
        print(json.dumps(result, ensure_ascii=False, indent=indent))
        return 0

    # 模式 B: 直接指定专利号/申请号或从 stdin 读取
    ids = list(args.patent_ids)
    if not ids and not sys.stdin.isatty():
        raw_stdin = sys.stdin.read().strip()
        if raw_stdin.startswith("{") and raw_stdin.endswith("}"):
            try:
                data = json.loads(raw_stdin)
                result = process_citations_packet(
                    data,
                    output_dir=args.output_dir,
                    dry_run=args.dry_run,
                    timeout_seconds=args.timeout,
                )
                indent = None if args.compact else 2
                print(json.dumps(result, ensure_ascii=False, indent=indent))
                return 0
            except json.JSONDecodeError:
                pass
        for line in raw_stdin.splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                ids.append(line_str)

    if not ids:
        parser.print_help()
        return 0

    results: list[dict[str, Any]] = []
    out_dir = Path(args.output_dir)

    for item in ids:
        if args.resolve_app:
            if args.dry_run:
                results.append({
                    "application_number": item,
                    "dry_run": True,
                    "search_query": remove_cn_check_digit(item),
                    "note": "dry-run: 跳过实际公开号网络查询",
                })
            else:
                try:
                    res = resolve_cn_application_number(item, timeout_seconds=args.timeout)
                    results.append(res)
                except Exception as exc:
                    results.append({
                        "application_number": item,
                        "ok": False,
                        "error": str(exc),
                        "fallback_url": build_espacenet_publication_url(item),
                    })
        else:
            dl_res = download_patent_pdf(
                item,
                output_dir=out_dir,
                dry_run=args.dry_run,
                timeout_seconds=args.timeout,
            )
            results.append(dl_res)

    indent = None if args.compact else 2
    payload = results[0] if len(results) == 1 else results
    print(json.dumps(payload, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
