"""Draw the app icons (a simple radar) into docs/icons/. Dev-only dependency: Pillow.

    python scripts/make_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "docs" / "icons"
BG = (13, 27, 42)
RING = (46, 196, 182)
SWEEP = (46, 196, 182, 90)
DOT = (255, 209, 102)


def radar(size: int, safe: float = 1.0, rounded: bool = False) -> Image.Image:
    scale = 4  # supersample for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), BG + (255,))
    d = ImageDraw.Draw(img, "RGBA")
    cx = cy = s / 2
    r_max = s * 0.38 * safe
    w = max(int(s * 0.018), 2)
    for k in (1.0, 0.68, 0.36):
        r = r_max * k
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RING, width=w)
    # sweep wedge
    d.pieslice([cx - r_max, cy - r_max, cx + r_max, cy + r_max], start=-90, end=-30, fill=SWEEP)
    ang = math.radians(-30)
    d.line([cx, cy, cx + r_max * math.cos(ang), cy + r_max * math.sin(ang)], fill=RING, width=w)
    # rising "blip"
    bx, by, br = cx + r_max * 0.45, cy - r_max * 0.48, s * 0.035 * safe
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=DOT)
    img = img.resize((size, size), Image.LANCZOS)
    if rounded:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22, fill=255)
        img.putalpha(mask)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    radar(180).convert("RGB").save(OUT / "apple-touch-icon.png")  # iOS rounds corners itself
    radar(192).convert("RGB").save(OUT / "icon-192.png")
    radar(512).convert("RGB").save(OUT / "icon-512.png")
    radar(512, safe=0.8).convert("RGB").save(OUT / "icon-maskable-512.png")
    radar(64, rounded=True).save(OUT / "favicon.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
