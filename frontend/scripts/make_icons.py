"""The site's icons and default social card, drawn once and committed.

    python frontend/scripts/make_icons.py

Needs Pillow (any recent version). The outputs live in frontend/public and
are checked in, so this only runs again when the wordmark changes.

The card is the wordmark on the site's ground with its accent rule: what a
link to the home page, or to any page without art of its own, shows in a
Discord or Reddit unfurl.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PUBLIC = Path(__file__).resolve().parent.parent / "public"

DEEP = (5, 7, 10)
INK = (234, 242, 248)
INK_DIM = (154, 172, 189)
ACCENT = (10, 200, 185)
GOLD = (200, 170, 110)

# Any of these draws a serviceable condensed-ish wordmark; the first found wins.
FONTS = [
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def wordmark(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], size: int) -> None:
    """RIFTLINE with the accent full stop, centred in ``box``."""
    f = font(size)
    text = "RIFTLINE"
    left, top, right, bottom = box
    w = draw.textlength(text, font=f)
    dot = draw.textlength(".", font=f)
    x = left + (right - left - w - dot) / 2
    y = top + (bottom - top) / 2
    draw.text((x, y), text, font=f, fill=INK, anchor="lm")
    draw.text((x + w, y), ".", font=f, fill=ACCENT, anchor="lm")


def card() -> None:
    img = Image.new("RGB", (1200, 630), DEEP)
    d = ImageDraw.Draw(img)
    # The accent rule the site uses as its one repeated motif.
    d.rectangle((0, 0, 6, 630), fill=ACCENT)
    wordmark(d, (0, 150, 1200, 380), 150)
    tag = font(38)
    d.text((600, 440), "League of Legends stats with the working shown", font=tag, fill=INK_DIM, anchor="mm")
    d.text((600, 500), "riftline.rhasta.space", font=font(28), fill=GOLD, anchor="mm")
    img.save(PUBLIC / "og-default.png", optimize=True)


def icon(size: int, name: str) -> None:
    img = Image.new("RGB", (size, size), DEEP)
    d = ImageDraw.Draw(img)
    f = font(int(size * 0.72))
    d.rectangle((0, 0, max(2, size // 32), size), fill=ACCENT)
    w = d.textlength("R", font=f)
    dot = d.textlength(".", font=f)
    x = (size - w - dot) / 2 + size * 0.02
    d.text((x, size / 2), "R", font=f, fill=INK, anchor="lm")
    d.text((x + w, size / 2), ".", font=f, fill=ACCENT, anchor="lm")
    img.save(PUBLIC / name, optimize=True)


def main() -> int:
    PUBLIC.mkdir(exist_ok=True)
    card()
    icon(512, "icon-512.png")
    icon(192, "icon-192.png")
    icon(180, "apple-touch-icon.png")
    icon(32, "favicon-32.png")
    Image.open(PUBLIC / "icon-192.png").save(
        PUBLIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
    )
    for name in ("og-default.png", "icon-512.png", "icon-192.png", "apple-touch-icon.png", "favicon-32.png", "favicon.ico"):
        print(f"{name}: {(PUBLIC / name).stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
