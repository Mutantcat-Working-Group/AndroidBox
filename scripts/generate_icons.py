#!/usr/bin/env python3
"""Generate desktop icons from logo.png (requires Pillow)."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def main():
    with Image.open(ROOT / "logo.png") as source:
        image = source.convert("RGBA")
    if image.size != (1024, 1024):
        raise ValueError("logo.png must be 1024x1024")
    icons = ROOT / "packaging/icons"
    icons.mkdir(parents=True, exist_ok=True)
    png = image.resize((512, 512), Image.Resampling.LANCZOS)
    for path in (ROOT / "data/AppIcon.png", ROOT / "androidbox/assets/AppIcon.png"):
        png.save(path)
    image.save(icons / "AndroidBox.ico", sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
    image.save(icons / "AndroidBox.icns")


if __name__ == "__main__":
    main()
