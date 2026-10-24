"""把稳定性领域夹具的文本模板材料化到临时目录。

`figure-1.drawio.txt` 与 `figure-2.drawio.txt` 是 Draw.io XML 文本测试模板，
不是正式交付附图。真实 PNG 只写到调用方给出的临时目录；文本模板也只在该目录复制一份供检查器读取。
本模块不供正式检查器导入，也不会在源码目录补造缺失产物。
"""
from __future__ import annotations

import binascii
import json
import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DOMAIN_DIR = Path(__file__).resolve().parents[1] / "skills/cn-patent-diagram-generator/assets/stability/domain"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def synthesize_png(width: int, height: int, margin: int, rgb: list[int]) -> bytes:
    """按公开参数生成无时间戳的 RGB PNG。四边留白等于 margin，内部为纯色。"""
    if width <= margin * 2 or height <= margin * 2:
        raise ValueError("PNG 内容区必须大于留白")
    if len(rgb) != 3 or any(not isinstance(channel, int) or channel < 0 or channel > 255 for channel in rgb):
        raise ValueError("rgb 必须是三个 0–255 整数")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ink = bytes(rgb)
    white = b"\xff\xff\xff"
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            inside = margin <= x < width - margin and margin <= y < height - margin
            raw.extend(ink if inside else white)
    compressed = zlib.compress(bytes(raw), 9)
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


def materialize_domain(destination: Path, source: Path = DOMAIN_DIR) -> Path:
    """复制文本夹具，并只在 destination 里生成 PNG。"""
    import shutil

    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source_resolved or source_resolved in destination_resolved.parents:
        raise ValueError("不能在源码夹具目录生成 PNG 或母版副本")
    if destination.exists():
        raise ValueError("目标目录必须是尚未创建的临时目录")
    # *.drawio 只匹配正式附图后缀，不会排除 figure-N.drawio.txt 文本模板。
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("*.png", "*.drawio"))
    spec = json.loads((destination / "png-synthesis.json").read_text(encoding="utf-8"))
    if spec.get("schema_id") != "cn-patent-domain-png-synthesis/v1":
        raise ValueError("PNG 合成参数 schema 不正确")
    for image in spec["images"]:
        payload = synthesize_png(image["width"], image["height"], image["margin"], image["rgb"])
        (destination / image["filename"]).write_bytes(payload)
    return destination


def remap_domain_path(path: Path, materialized: Path, source: Path = DOMAIN_DIR) -> Path:
    """合同里的 domain 文本路径改指向本次临时副本，其他报告路径保持不变。"""
    try:
        relative = path.resolve().relative_to(source.resolve())
    except ValueError:
        return path
    return materialized / relative
