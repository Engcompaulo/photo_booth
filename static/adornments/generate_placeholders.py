"""Generate the Dia de los Muertos adornment PNG assets and their theme.json files.

Each PNG is an RGBA image with a fully transparent background and a bold, solid,
recognizable adornment that fills the canvas width. The composition engine maps
the asset's full width to ``scale_factor * inter_eye_distance`` pixels, so the
drawable content is drawn edge-to-edge (minimal transparent margin) to read
clearly when composited over a face.

Run from this directory (static/adornments/) with Pillow installed:

    python generate_placeholders.py

Output layout:

    static/adornments/<theme>/<asset>.png
    static/adornments/<theme>/theme.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

# Square working canvas for most assets. Wide/overlay assets use their own size.
SIZE = 512
TRANSPARENT = (0, 0, 0, 0)

# Keys written to theme.json (generator-only keys like the drawing function are
# stripped out).
THEME_JSON_ASSET_KEYS = ("file", "anchor", "scale_factor", "offset_ratio", "rotate_with_face")


def _new(width=SIZE, height=SIZE):
    img = Image.new("RGBA", (width, height), TRANSPARENT)
    return img, ImageDraw.Draw(img)


def _marigold(d, cx, cy, r, base, outline=(90, 30, 10, 255)):
    """Draw a single cempasuchil (marigold) flower centered at (cx, cy)."""
    for k in range(8):
        ang = (math.pi / 4) * k
        px = cx + r * 0.7 * math.cos(ang)
        py = cy + r * 0.7 * math.sin(ang)
        d.ellipse([px - r * 0.5, py - r * 0.5, px + r * 0.5, py + r * 0.5],
                  fill=base, outline=outline, width=2)
    d.ellipse([cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4],
              fill=(120, 60, 10, 255))


# --------------------------------------------------------------------------- #
# calavera
# --------------------------------------------------------------------------- #
def draw_calavera():
    """Sugar-skull (calavera) decoration: eye flowers + nose + decorated grin."""
    img, d = _new(SIZE, SIZE)
    w = h = SIZE
    petal = (120, 40, 160, 255)
    petal2 = (255, 140, 30, 255)
    outline = (20, 10, 30, 255)
    for cx in (w * 0.33, w * 0.67):
        cy = h * 0.34
        r = w * 0.15
        for k in range(8):
            ang = (math.pi / 4) * k
            px = cx + r * math.cos(ang)
            py = cy + r * math.sin(ang)
            d.ellipse([px - r * 0.45, py - r * 0.45, px + r * 0.45, py + r * 0.45],
                      fill=petal2 if k % 2 == 0 else petal, outline=outline, width=2)
        d.ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5], fill=(25, 15, 35, 255))
        d.ellipse([cx - r * 0.18, cy - r * 0.22, cx + r * 0.06, cy + r * 0.02], fill=(255, 255, 255, 230))
    nx, ny = w * 0.5, h * 0.52
    d.ellipse([nx - w * 0.05, ny, nx + w * 0.005, ny + h * 0.06], fill=outline)
    d.ellipse([nx - w * 0.005, ny, nx + w * 0.05, ny + h * 0.06], fill=outline)
    d.polygon([(nx - w * 0.05, ny + h * 0.045), (nx + w * 0.05, ny + h * 0.045),
               (nx, ny + h * 0.12)], fill=outline)
    my = h * 0.72
    d.arc([w * 0.28, my - h * 0.10, w * 0.72, my + h * 0.10], start=10, end=170,
          fill=outline, width=max(4, w // 90))
    for i in range(1, 7):
        x = w * (0.30 + i * 0.058)
        d.line([x, my - h * 0.05, x, my + h * 0.06], fill=outline, width=max(3, w // 110))
    return img


def draw_forehead_flower():
    """A single marigold with leaves, worn on the forehead (above head)."""
    img, d = _new(SIZE, SIZE // 2)
    w, h = SIZE, SIZE // 2
    d.line([w * 0.25, h * 0.75, w * 0.75, h * 0.75], fill=(40, 120, 50, 255), width=max(4, h // 16))
    _marigold(d, w * 0.5, h * 0.48, w * 0.22, (255, 150, 20, 255))
    return img


# --------------------------------------------------------------------------- #
# sombrero
# --------------------------------------------------------------------------- #
def draw_sombrero():
    """Festive charro sombrero: wide brim + crown with a colorful band."""
    img, d = _new()
    w = h = SIZE
    d.ellipse([w * 0.00, h * 0.60, w * 1.00, h * 0.98], fill=(150, 90, 30, 255))
    d.ellipse([w * 0.08, h * 0.64, w * 0.92, h * 0.92], fill=(180, 115, 45, 255))
    d.ellipse([w * 0.30, h * 0.18, w * 0.70, h * 0.74], fill=(170, 105, 40, 255))
    d.rectangle([w * 0.30, h * 0.44, w * 0.70, h * 0.70], fill=(170, 105, 40, 255))
    d.rectangle([w * 0.30, h * 0.58, w * 0.70, h * 0.70], fill=(200, 30, 60, 255))
    for i, col in enumerate([(255, 200, 40, 255), (40, 160, 90, 255), (60, 110, 200, 255)]):
        d.rectangle([w * (0.31 + i * 0.13), h * 0.60, w * (0.31 + i * 0.13 + 0.10), h * 0.68], fill=col)
    return img


def draw_mustache():
    """A bold curled charro mustache, anchored on the mouth."""
    img, d = _new(SIZE, SIZE // 2)
    w, h = SIZE, SIZE // 2
    col = (30, 20, 15, 255)
    # Two swooping halves meeting in the middle, curling up at the tips.
    d.polygon([(w * 0.5, h * 0.35), (w * 0.14, h * 0.30), (w * 0.06, h * 0.52),
               (w * 0.20, h * 0.60), (w * 0.38, h * 0.52), (w * 0.5, h * 0.55)], fill=col)
    d.polygon([(w * 0.5, h * 0.35), (w * 0.86, h * 0.30), (w * 0.94, h * 0.52),
               (w * 0.80, h * 0.60), (w * 0.62, h * 0.52), (w * 0.5, h * 0.55)], fill=col)
    d.ellipse([w * 0.03, h * 0.30, w * 0.16, h * 0.46], fill=col)
    d.ellipse([w * 0.84, h * 0.30, w * 0.97, h * 0.46], fill=col)
    return img


# --------------------------------------------------------------------------- #
# flower_crown
# --------------------------------------------------------------------------- #
def draw_flower_crown():
    """Cempasuchil (marigold) flower crown that sits above the head."""
    img, d = _new(SIZE, SIZE // 2)
    w, h = SIZE, SIZE // 2
    colors = [(255, 140, 20, 255), (255, 190, 30, 255), (200, 40, 90, 255),
              (170, 60, 170, 255), (240, 90, 40, 255)]
    d.line([w * 0.05, h * 0.70, w * 0.95, h * 0.70], fill=(40, 120, 50, 255), width=max(4, h // 20))
    n = 7
    for i in range(n):
        cx = w * (0.08 + i * (0.84 / (n - 1)))
        cy = h * (0.55 if i % 2 == 0 else 0.42)
        _marigold(d, cx, cy, w * 0.085, colors[i % len(colors)])
    return img


# --------------------------------------------------------------------------- #
# catrina
# --------------------------------------------------------------------------- #
def draw_catrina_veil():
    """La Catrina veil + feathered band that sits above the head."""
    img, d = _new()
    w = h = SIZE
    d.ellipse([w * 0.00, h * 0.52, w * 1.00, h * 0.86], fill=(20, 15, 30, 255))
    d.ellipse([w * 0.26, h * 0.14, w * 0.74, h * 0.62], fill=(30, 20, 45, 255))
    for i, col in enumerate([(230, 230, 240, 255), (200, 60, 110, 255), (120, 60, 180, 255)]):
        dx = (i - 1) * w * 0.10
        d.polygon([(w * 0.5 + dx, h * 0.02), (w * 0.5 + dx + w * 0.05, h * 0.30),
                   (w * 0.5 + dx - w * 0.05, h * 0.30)], fill=col)
    rx, ry = w * 0.62, h * 0.50
    for rr in (w * 0.08, w * 0.055, w * 0.03):
        d.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], outline=(210, 40, 80, 255), width=max(3, w // 120))
    return img


def draw_catrina_lips():
    """Stitched Catrina lips (sewn-smile motif) anchored on the mouth."""
    img, d = _new(SIZE, SIZE // 2)
    w, h = SIZE, SIZE // 2
    col = (25, 15, 30, 255)
    d.line([w * 0.18, h * 0.5, w * 0.82, h * 0.5], fill=col, width=max(4, w // 90))
    for i in range(1, 9):
        x = w * (0.18 + i * (0.64 / 9))
        d.line([x, h * 0.34, x, h * 0.66], fill=col, width=max(3, w // 120))
    return img


# --------------------------------------------------------------------------- #
# papel_picado (full-frame overlay)
# --------------------------------------------------------------------------- #
def draw_papel_picado():
    """Papel picado banner strung across the top as a full-frame overlay."""
    w = h = SIZE
    img, d = _new(w, h)
    colors = [(255, 90, 120, 230), (90, 190, 220, 230), (255, 200, 60, 230),
              (150, 220, 120, 230), (200, 120, 230, 230)]
    sy = h * 0.06
    d.line([0, sy, w, sy], fill=(60, 50, 40, 220), width=max(2, w // 240))
    flags = 5
    fw = w / flags
    for i in range(flags):
        x0 = i * fw + fw * 0.08
        x1 = (i + 1) * fw - fw * 0.08
        col = colors[i % len(colors)]
        d.rectangle([x0, sy, x1, sy + h * 0.22], fill=col)
        for hx in (0.3, 0.5, 0.7):
            cx = x0 + (x1 - x0) * hx
            for hy in (0.10, 0.16):
                cy = sy + h * hy
                d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=TRANSPARENT)
        d.polygon([(x0, sy + h * 0.22), (x0 + (x1 - x0) * 0.25, sy + h * 0.18),
                   (x0 + (x1 - x0) * 0.5, sy + h * 0.22),
                   (x0 + (x1 - x0) * 0.75, sy + h * 0.18),
                   (x1, sy + h * 0.22), (x1, sy + h * 0.25), (x0, sy + h * 0.25)],
                  fill=TRANSPARENT)
    return img


# --------------------------------------------------------------------------- #
# marigold_path (full-frame overlay of petals + candles, bottom corners)
# --------------------------------------------------------------------------- #
def draw_marigold_frame():
    """A full-frame overlay: scattered marigold petals + candle flames in corners."""
    w = h = SIZE
    img, d = _new(w, h)
    # Petals scattered along the bottom edge.
    petal_colors = [(255, 150, 20, 220), (255, 190, 40, 220), (240, 110, 30, 220)]
    import random as _r
    rnd = _r.Random(7)
    for _ in range(60):
        px = rnd.uniform(0, w)
        py = rnd.uniform(h * 0.78, h)
        rr = rnd.uniform(w * 0.012, w * 0.03)
        d.ellipse([px - rr, py - rr * 0.6, px + rr, py + rr * 0.6],
                  fill=rnd.choice(petal_colors))
    # Small candle flames in the bottom corners.
    for cx in (w * 0.08, w * 0.92):
        d.polygon([(cx, h * 0.80), (cx - w * 0.02, h * 0.88), (cx + w * 0.02, h * 0.88)],
                  fill=(255, 190, 40, 230))
        d.ellipse([cx - w * 0.012, h * 0.86, cx + w * 0.012, h * 0.90], fill=(255, 120, 20, 230))
    return img


# --------------------------------------------------------------------------- #
# mariachi (mustache + bow tie)
# --------------------------------------------------------------------------- #
def draw_bowtie():
    """A charro bow tie, anchored at the chin."""
    img, d = _new(SIZE, SIZE // 2)
    w, h = SIZE, SIZE // 2
    col = (170, 20, 40, 255)
    d.polygon([(w * 0.5, h * 0.5), (w * 0.14, h * 0.26), (w * 0.14, h * 0.74)], fill=col)
    d.polygon([(w * 0.5, h * 0.5), (w * 0.86, h * 0.26), (w * 0.86, h * 0.74)], fill=col)
    d.rectangle([w * 0.44, h * 0.36, w * 0.56, h * 0.64], fill=(120, 10, 25, 255))
    return img


# --------------------------------------------------------------------------- #
# monarch (butterfly above head — a Dia de los Muertos symbol)
# --------------------------------------------------------------------------- #
def draw_monarch():
    """A monarch butterfly that sits above the head."""
    img, d = _new(SIZE, SIZE // 2)
    w, h = SIZE, SIZE // 2
    orange = (235, 110, 20, 255)
    dark = (30, 20, 15, 255)
    # Body.
    d.ellipse([w * 0.48, h * 0.30, w * 0.52, h * 0.78], fill=dark)
    # Four wings.
    d.ellipse([w * 0.16, h * 0.20, w * 0.49, h * 0.52], fill=orange, outline=dark, width=4)
    d.ellipse([w * 0.51, h * 0.20, w * 0.84, h * 0.52], fill=orange, outline=dark, width=4)
    d.ellipse([w * 0.22, h * 0.50, w * 0.49, h * 0.80], fill=orange, outline=dark, width=4)
    d.ellipse([w * 0.51, h * 0.50, w * 0.78, h * 0.80], fill=orange, outline=dark, width=4)
    # Dark wing veins / spots.
    for wx in (0.30, 0.70):
        for wy in (0.30, 0.62):
            d.ellipse([w * wx - 7, h * wy - 7, w * wx + 7, h * wy + 7], fill=dark)
    # Antennae.
    d.line([w * 0.5, h * 0.30, w * 0.42, h * 0.10], fill=dark, width=3)
    d.line([w * 0.5, h * 0.30, w * 0.58, h * 0.10], fill=dark, width=3)
    return img


THEMES = {
    "calavera": [
        {"file": "calavera.png", "draw": draw_calavera, "anchor": "eyes",
         "scale_factor": 2.4, "offset_ratio": [0.0, 0.15], "rotate_with_face": True},
        {"file": "forehead_flower.png", "draw": draw_forehead_flower, "anchor": "above_head",
         "scale_factor": 1.4, "offset_ratio": [0.0, 0.1], "rotate_with_face": True},
    ],
    "sombrero": [
        {"file": "sombrero.png", "draw": draw_sombrero, "anchor": "above_head",
         "scale_factor": 2.8, "offset_ratio": [0.0, -0.25], "rotate_with_face": True},
        {"file": "mustache.png", "draw": draw_mustache, "anchor": "mouth",
         "scale_factor": 1.5, "offset_ratio": [0.0, -0.1], "rotate_with_face": True},
    ],
    "flower_crown": [
        {"file": "crown.png", "draw": draw_flower_crown, "anchor": "above_head",
         "scale_factor": 2.6, "offset_ratio": [0.0, -0.1], "rotate_with_face": True},
    ],
    "catrina": [
        {"file": "veil.png", "draw": draw_catrina_veil, "anchor": "above_head",
         "scale_factor": 2.8, "offset_ratio": [0.0, -0.2], "rotate_with_face": True},
        {"file": "lips.png", "draw": draw_catrina_lips, "anchor": "mouth",
         "scale_factor": 1.1, "offset_ratio": [0.0, 0.0], "rotate_with_face": True},
    ],
    "papel_picado": [
        {"file": "banner.png", "draw": draw_papel_picado, "anchor": "full_frame",
         "scale_factor": 1.0, "offset_ratio": [0.0, 0.0], "rotate_with_face": False},
    ],
    "marigold_path": [
        {"file": "frame.png", "draw": draw_marigold_frame, "anchor": "full_frame",
         "scale_factor": 1.0, "offset_ratio": [0.0, 0.0], "rotate_with_face": False},
        {"file": "crown.png", "draw": draw_flower_crown, "anchor": "above_head",
         "scale_factor": 2.4, "offset_ratio": [0.0, -0.1], "rotate_with_face": True},
    ],
    "mariachi": [
        {"file": "mustache.png", "draw": draw_mustache, "anchor": "mouth",
         "scale_factor": 1.6, "offset_ratio": [0.0, -0.1], "rotate_with_face": True},
        {"file": "bowtie.png", "draw": draw_bowtie, "anchor": "chin",
         "scale_factor": 1.6, "offset_ratio": [0.0, 0.5], "rotate_with_face": True},
        {"file": "sombrero.png", "draw": draw_sombrero, "anchor": "above_head",
         "scale_factor": 2.8, "offset_ratio": [0.0, -0.25], "rotate_with_face": True},
    ],
    "monarch": [
        {"file": "butterfly.png", "draw": draw_monarch, "anchor": "above_head",
         "scale_factor": 2.2, "offset_ratio": [0.0, -0.05], "rotate_with_face": True},
    ],
}


def generate(root: Path) -> None:
    for theme_name, assets in THEMES.items():
        theme_dir = root / theme_name
        theme_dir.mkdir(parents=True, exist_ok=True)
        for asset in assets:
            img = asset["draw"]()
            img.save(theme_dir / asset["file"], format="PNG")
        theme_json = {
            "name": theme_name,
            "assets": [{k: a[k] for k in THEME_JSON_ASSET_KEYS} for a in assets],
        }
        with (theme_dir / "theme.json").open("w", encoding="utf-8") as fh:
            json.dump(theme_json, fh, indent=2)
            fh.write("\n")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent)
    print("GEN_DONE")
