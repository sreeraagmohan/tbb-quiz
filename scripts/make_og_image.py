#!/usr/bin/env python3
"""Draw the link-preview image (LinkedIn, WhatsApp, X) -> assets/og.png.

Run once locally when the wording changes: .venv/bin/python scripts/make_og_image.py
Needs Pillow and the Georgia fonts that ship with macOS.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = Path("/System/Library/Fonts/Supplemental")
BRICK, CREAM, INK = (173, 44, 36), (247, 233, 212), (30, 30, 30)
W, H = 1200, 627


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


img = Image.new("RGB", (W, H), CREAM)
d = ImageDraw.Draw(img)

# Masthead block on the left, like the newsletter's logo.
d.rectangle([0, 0, 520, H], fill=BRICK)
logo = font("Georgia Bold.ttf", 82)
for i, line in enumerate(["The", "Bharat", "Briefing."]):
    d.text((56, 120 + i * 104), line, font=logo, fill=CREAM)

# Pitch on the right.
x = 580
d.text((x, 118), "UPSC PRELIMS PRACTICE", font=font("Georgia Bold.ttf", 26), fill=BRICK)
title = font("Georgia Bold.ttf", 58)
for i, line in enumerate(["Current affairs,", "one question", "at a time."]):
    d.text((x, 170 + i * 70), line, font=title, fill=INK)
body = font("Georgia.ttf", 30)
for i, line in enumerate(["Written from every issue of", "The Bharat Briefing. Free."]):
    d.text((x, 410 + i * 42), line, font=body, fill=(93, 86, 80))

# OMR-style answer bubbles, the quiz's signature detail.
for i, letter in enumerate("abcd"):
    cx, cy, r = x + 22 + i * 64, 535, 20
    filled = letter == "c"
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=3, fill=INK if filled else None)
    d.text((cx, cy), letter, font=font("Georgia Bold.ttf", 22), fill=CREAM if filled else INK, anchor="mm")

out = ROOT / "assets" / "og.png"
out.parent.mkdir(exist_ok=True)
img.save(out, optimize=True)
print(f"wrote {out.relative_to(ROOT)}")
