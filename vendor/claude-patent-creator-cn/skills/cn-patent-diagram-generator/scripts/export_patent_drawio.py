#!/usr/bin/env python3
"""使用 Draw.io Desktop CLI 导出中国专利附图，并写入 DPI 与证据报告。"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_drawio() -> str:
    for name in ("drawio", "draw.io"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
        Path(r"C:\Program Files\draw.io\draw.io.exe"),
        Path(os.environ.get("LOCALAPPDATA", ""), r"Programs\draw.io\draw.io.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("未找到 Draw.io Desktop CLI（drawio/draw.io）")


def cli_version(binary: str) -> str:
    # Windows 中文系统的默认代码页可能无法解码 Draw.io 的 UTF-8/本地化输出；
    # 导出证据只需要版本字符串，遇到异常字节时保留可读替换字符即可。
    result = subprocess.run(
        [binary, "--version"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=20, check=False,
    )
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[-1] if value else "unknown"


def run_export(binary: str, source: Path, output: Path, fmt: str, width: int, border: int) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="patent_drawio_export_") as raw:
        temp = Path(raw) / f"export.{fmt}"
        command = [
            binary, "-x", "-f", fmt, "--size", "diagram", "--theme", "light",
            "--border", str(border), "-o", str(temp),
        ]
        if os.name == "nt":
            # Windows 无头/远端会话下 Electron 需要软件渲染，否则 GPU 进程崩溃导致导出失败
            command.extend(["--no-sandbox", "--disable-gpu", "--use-gl=swiftshader"])
        if fmt == "png":
            command.extend(["--width", str(width)])
        command.append(str(source))
        attempts = [command]
        if sys.platform.startswith("linux") and shutil.which("xvfb-run"):
            attempts.insert(0, [shutil.which("xvfb-run") or "xvfb-run", "-a", *command])
        messages: list[str] = []
        for attempt in attempts:
            result = subprocess.run(
                attempt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120, check=False,
            )
            messages.append((result.stdout or "") + (result.stderr or ""))
            if result.returncode == 0 and temp.is_file() and temp.stat().st_size > 0:
                shutil.copy2(temp, output)
                return attempt
        raise RuntimeError("Draw.io CLI 导出失败：" + " | ".join(message.strip()[-500:] for message in messages))


def png_chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("输出不是有效 PNG")
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = data[offset + 8 + length:offset + 12 + length]
        yield kind, payload, crc
        offset += 12 + length


def chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def set_png_dpi(path: Path, dpi: float) -> None:
    data = path.read_bytes()
    ppm = round(dpi / 0.0254)
    phys = struct.pack(">IIB", ppm, ppm, 1)
    parts = [PNG_SIGNATURE]
    inserted = False
    for kind, payload, _crc in png_chunks(data):
        if kind == b"pHYs":
            if not inserted:
                parts.append(chunk(b"pHYs", phys))
                inserted = True
            continue
        parts.append(chunk(kind, payload))
        if kind == b"IHDR" and not inserted:
            parts.append(chunk(b"pHYs", phys))
            inserted = True
    path.write_bytes(b"".join(parts))


def paeth_predictor(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_up and distance_left <= distance_upper_left:
        return left
    if distance_up <= distance_upper_left:
        return up
    return upper_left


def png_content_bounds(path: Path, white_threshold: int = 245) -> dict[str, Any]:
    """复算PNG非白内容边界；已有Pillow时使用快速路径，否则使用标准库。"""
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            mask = rgb.point(lambda value: 0 if value >= white_threshold else 255)
            bounds = mask.getbbox()
            if bounds is None:
                raise ValueError("PNG未检测到非白图形内容")
            minimum_x, minimum_y, right, bottom = bounds
            maximum_x, maximum_y = right - 1, bottom - 1
            width, height = rgb.size
        margins = {
            "left": minimum_x,
            "top": minimum_y,
            "right": width - 1 - maximum_x,
            "bottom": height - 1 - maximum_y,
        }
        return {
            "content_bounds": [minimum_x, minimum_y, maximum_x, maximum_y],
            "content_width": maximum_x - minimum_x + 1,
            "content_height": maximum_y - minimum_y + 1,
            "margins": margins,
            "maximum_margin": max(margins.values()),
            "white_threshold": white_threshold,
            "inspection_engine": "pillow"
        }
    chunks = list(png_chunks(path.read_bytes()))
    ihdr = next((payload for kind, payload, _crc in chunks if kind == b"IHDR"), None)
    if ihdr is None or len(ihdr) != 13:
        raise ValueError("PNG缺少有效IHDR")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
    if bit_depth != 8 or interlace != 0 or compression != 0 or filtering != 0:
        raise ValueError(f"不支持的PNG编码：bit_depth={bit_depth}, interlace={interlace}")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"不支持的PNG color_type：{color_type}")
    compressed = b"".join(payload for kind, payload, _crc in chunks if kind == b"IDAT")
    raw = zlib.decompress(compressed)
    stride = width * channels
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError(f"PNG扫描行长度异常：{len(raw)} != {expected}")
    previous = bytearray(stride)
    offset = 0
    minimum_x = width
    minimum_y = height
    maximum_x = maximum_y = -1
    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        filtered = raw[offset:offset + stride]
        offset += stride
        row = bytearray(stride)
        for index, value in enumerate(filtered):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = (value + left) & 0xFF
            elif filter_type == 2:
                decoded = (value + up) & 0xFF
            elif filter_type == 3:
                decoded = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                decoded = (value + paeth_predictor(left, up, upper_left)) & 0xFF
            else:
                raise ValueError(f"未知PNG过滤器：{filter_type}")
            row[index] = decoded
        for x in range(width):
            start = x * channels
            pixel = row[start:start + channels]
            if color_type == 0:
                red = green = blue = pixel[0]
                alpha = 255
            elif color_type == 2:
                red, green, blue = pixel
                alpha = 255
            elif color_type == 4:
                red = green = blue = pixel[0]
                alpha = pixel[1]
            else:
                red, green, blue, alpha = pixel
            # 把透明度合成到白色背景后判断是否属于图形内容。
            red = (red * alpha + 255 * (255 - alpha)) // 255
            green = (green * alpha + 255 * (255 - alpha)) // 255
            blue = (blue * alpha + 255 * (255 - alpha)) // 255
            if min(red, green, blue) < white_threshold:
                minimum_x = min(minimum_x, x)
                minimum_y = min(minimum_y, y)
                maximum_x = max(maximum_x, x)
                maximum_y = max(maximum_y, y)
        previous = row
    if maximum_x < 0:
        raise ValueError("PNG未检测到非白图形内容")
    margins = {
        "left": minimum_x,
        "top": minimum_y,
        "right": width - 1 - maximum_x,
        "bottom": height - 1 - maximum_y,
    }
    return {
        "content_bounds": [minimum_x, minimum_y, maximum_x, maximum_y],
        "content_width": maximum_x - minimum_x + 1,
        "content_height": maximum_y - minimum_y + 1,
        "margins": margins,
        "maximum_margin": max(margins.values()),
        "white_threshold": white_threshold,
        "inspection_engine": "stdlib_png_decoder",
    }


def inspect_png(path: Path, white_threshold: int = 245) -> dict[str, Any]:
    width = height = None
    dpi = None
    for kind, payload, _crc in png_chunks(path.read_bytes()):
        if kind == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif kind == b"pHYs" and len(payload) == 9:
            xppm, yppm, unit = struct.unpack(">IIB", payload)
            if unit == 1:
                dpi = [round(xppm * 0.0254, 4), round(yppm * 0.0254, 4)]
    return {
        "width": width,
        "height": height,
        "dpi": dpi,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        **png_content_bounds(path, white_threshold),
    }


def drawio_page_width(path: Path) -> int:
    root = ET.parse(path).getroot()
    model = root.find("./diagram/mxGraphModel") if root.tag == "mxfile" else root
    if model is None:
        raise ValueError("drawio 缺少 mxGraphModel")
    try:
        return int(float(model.get("pageWidth", "0")))
    except ValueError as exc:
        raise ValueError("drawio pageWidth 无效") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 Draw.io Desktop 官方引擎导出专利附图")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--png", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--width", type=int, help="最终像素宽度；省略时按 drawio pageWidth × DPI/96 计算")
    parser.add_argument("--dpi", type=float, default=300.0)
    parser.add_argument("--border", type=int, default=10)
    parser.add_argument("--white-threshold", type=int, default=245)
    parser.add_argument("--max-margin", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        source = args.input.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        binary = find_drawio()
        version = cli_version(binary)
        width = args.width or round(drawio_page_width(source) * args.dpi / 96.0)
        if width <= 0:
            raise ValueError("导出宽度必须大于 0")
        png_command = run_export(binary, source, args.png.resolve(), "png", width, args.border)
        set_png_dpi(args.png.resolve(), args.dpi)
        png_inspection = inspect_png(args.png.resolve(), args.white_threshold)
        if png_inspection["maximum_margin"] > args.max_margin:
            raise ValueError(
                f"PNG白边超过上限：{png_inspection['margins']}，maximum={args.max_margin}"
            )
        outputs: dict[str, Any] = {"png": {"path": str(args.png.resolve()), **png_inspection}}
        commands = {"png": png_command}
        report = {
            "schema_id": "cn-patent-drawio-export/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "renderer": {"kind": "drawio_desktop_cli", "binary": binary, "version": version},
            "source": {"path": str(source), "sha256": sha256(source)},
            "parameters": {"width": width, "dpi": args.dpi, "border": args.border, "size": "diagram", "theme": "light", "white_threshold": args.white_threshold, "maximum_margin_pixels": args.max_margin},
            "commands": commands,
            "outputs": outputs,
            "status": "PASS",
        }
    except Exception as exc:
        report = {"schema_id": "cn-patent-drawio-export/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
