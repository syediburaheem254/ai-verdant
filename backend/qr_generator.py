"""
AI Verdant — QR code generator

Generates the QR sticker that gets pasted on the sensor box. Scanning it
opens /portal/<device_id> on your backend, which shows the latest reading
and links into the full AI Verdant dashboard.

Usage:
    python qr_generator.py device-001
    python qr_generator.py device-001 --out device-001-qr.png
"""

import argparse
import qrcode
from config import Config


def generate(device_id: str, out_path: str):
    url = f"{Config.PUBLIC_BASE_URL}/portal/{device_id}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0d1512", back_color="#eafff1")
    img.save(out_path)
    print(f"Saved QR code for {device_id} -> {out_path}")
    print(f"It encodes: {url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("device_id", help="Unique ID of the sensor box, e.g. device-001")
    parser.add_argument("--out", default=None, help="Output PNG path")
    args = parser.parse_args()
    out = args.out or f"{args.device_id}-qr.png"
    generate(args.device_id, out)
