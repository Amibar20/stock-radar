"""Draw the app icons into docs/icons/. Dev-only dependency: Pillow.

    python scripts/make_icons.py

Design: a dark "liquid glass" tile with blue/violet ambient light, a glass disc with radar rings and a soft
sweep, and a glowing rising price line ending in a bright point (radar + market in one mark).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "docs" / "icons"
SS = 4  # supersampling factor


def _radial(size: int, cx: float, cy: float, radius: float, color: tuple[int, int, int], alpha: int) -> Image.Image:
    """A soft radial light blob."""
    layer = Image.new("RGBA", (size, size), color + (0,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=alpha)
    layer.putalpha(mask.filter(ImageFilter.GaussianBlur(radius * 0.45)))
    return layer


def draw(size: int, safe: float = 1.0) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (6, 8, 16, 255))
    # vertical base gradient
    grad = Image.linear_gradient("L").resize((s, s))
    top = Image.new("RGBA", (s, s), (16, 22, 48, 255))
    img = Image.composite(img, top, grad)
    # ambient light
    img.alpha_composite(_radial(s, s * 0.82, s * 0.12, s * 0.55, (10, 132, 255), 150))
    img.alpha_composite(_radial(s, s * 0.12, s * 0.92, s * 0.5, (124, 92, 255), 120))

    cx, cy = s / 2, s / 2
    R = s * 0.34 * safe

    # glass disc: translucent fill, top sheen, bright rim
    disc = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(disc)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(255, 255, 255, 22))
    sheen = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse([cx - R * 0.92, cy - R * 0.98, cx + R * 0.92, cy + R * 0.1], fill=(255, 255, 255, 26))
    disc.alpha_composite(sheen.filter(ImageFilter.GaussianBlur(s * 0.02)))
    d = ImageDraw.Draw(disc)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=(190, 220, 255, 120), width=max(int(s * 0.006), 2))
    for k in (0.68, 0.38):
        r = R * k
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(170, 205, 255, 62), width=max(int(s * 0.004), 1))

    # radar sweep: a wedge that fades out behind the leading edge
    sweep = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    lead = -38  # degrees (0 = east, clockwise)
    for i in range(60):
        a0 = lead - (i + 1) * 1.2
        sd.pieslice([cx - R, cy - R, cx + R, cy + R], start=a0, end=lead - i * 1.2,
                    fill=(90, 200, 255, int(115 * (1 - i / 60) ** 1.8)))
    disc.alpha_composite(sweep)
    la = math.radians(lead)
    ImageDraw.Draw(disc).line([cx, cy, cx + R * math.cos(la), cy + R * math.sin(la)],
                              fill=(140, 220, 255, 150), width=max(int(s * 0.005), 1))
    # keep everything inside the disc
    clip = Image.new("L", (s, s), 0)
    ImageDraw.Draw(clip).ellipse([cx - R - 4, cy - R - 4, cx + R + 4, cy + R + 4], fill=255)
    disc.putalpha(ImageChops.multiply(disc.getchannel("A"), clip))
    img.alpha_composite(disc)

    # rising price line with glow
    pts_rel = [(-0.78, 0.42), (-0.48, 0.18), (-0.26, 0.30), (0.02, -0.04), (0.22, 0.06), (0.50, -0.30), (0.70, -0.52)]
    pts = [(cx + x * R, cy + y * R) for x, y in pts_rel]
    w = max(int(s * 0.03 * safe), 3)
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(pts, fill=(60, 180, 255, 255), width=w * 3, joint="curve")
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.03)))
    line = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    ld.line(pts, fill=(235, 248, 255, 255), width=w, joint="curve")
    for p in pts[:-1]:  # round the joints and the start
        ld.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=(235, 248, 255, 255))
    img.alpha_composite(line)

    # bright end point
    ex, ey = pts[-1]
    img.alpha_composite(_radial(s, ex, ey, s * 0.07 * safe, (120, 210, 255), 255))
    r = w * 1.15
    ImageDraw.Draw(img).ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.LANCZOS)


def rounded(img: Image.Image, radius: float = 0.225) -> Image.Image:
    size = img.size[0]
    mask = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * SS - 1, size * SS - 1], radius=size * SS * radius, fill=255)
    out = img.copy()
    out.putalpha(mask.resize((size, size), Image.LANCZOS))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(180).convert("RGB").save(OUT / "apple-touch-icon.png")  # iOS rounds the corners itself
    draw(192).convert("RGB").save(OUT / "icon-192.png")
    draw(512).convert("RGB").save(OUT / "icon-512.png")
    draw(512, safe=0.8).convert("RGB").save(OUT / "icon-maskable-512.png")
    rounded(draw(64)).save(OUT / "favicon.png")
    preview_dir = OUT.parent.parent / "out"  # large rounded preview for review (out/ is git-ignored)
    if preview_dir.exists():
        rounded(draw(1024)).save(preview_dir / "icon-preview.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
