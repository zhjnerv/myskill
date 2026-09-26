#!/usr/bin/env python3
"""Print the fixed account-QR footer. The image stays in this skill."""
import base64
import sys
from pathlib import Path

QR = Path(__file__).resolve().parent.parent / "assets" / "account-qr.jpg"

def main() -> None:
    if not QR.is_file():
        raise SystemExit(f"missing account QR: {QR}")
    uri = "data:image/jpeg;base64," + base64.b64encode(QR.read_bytes()).decode("ascii")
    html = (
        '<section style="text-align:center;background:#ffffff;border:1px solid #E5E7EB;border-radius:12px;padding:24px 20px;margin:24px 10px 0;">\n'
        f'  <span leaf=""><img src="{uri}" alt="脑后插管" style="width:200px;max-width:100%;height:auto;display:block;margin:0 auto;"></span>\n'
        '  <p style="margin:12px 0 0;font-size:13px;line-height:1.6;color:#6B7280;letter-spacing:1px;"><span leaf="">长按识别二维码关注</span></p>\n'
        "</section>"
    )
    sys.stdout.buffer.write(html.encode("utf-8"))

if __name__ == "__main__":
    main()
