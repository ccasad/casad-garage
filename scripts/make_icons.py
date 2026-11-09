"""Regenerate the app icons (NFR-17) from one 1024 px master drawing.

Run: uv run python scripts/make_icons.py
Writes the PNGs and icon.svg under app/static/icons/, keeping their names.
"""

import colorsys
from pathlib import Path

from PIL import Image, ImageDraw

SLUG = "casad-garage"
SIZE = 1024
SS = 2  # supersampling for smooth edges
OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"

HUE = sum(ord(c) for c in SLUG) * 47 % 360
_r, _g, _b = colorsys.hls_to_rgb(HUE / 360, 0.42, 0.55)
BG = (round(_r * 255), round(_g * 255), round(_b * 255))
FG = (255, 255, 255)

# The car, side view, in 1024 px master coordinates. It spans x 162-862 and
# y 335-715, inside the central 80% (102-922) that stays visible when masked.
# Each shape: (kind, geometry, colour). "bg" shapes cut windows and wheel arches.
DY = -35
SHAPES = [
    ("rrect", (162, 500 + DY, 862, 660 + DY, 50), "fg"),  # lower body
    ("poly", [(290, 510 + DY), (385, 370 + DY), (650, 370 + DY), (745, 510 + DY)], "fg"),  # cabin
    (
        "poly",
        [(350, 500 + DY), (410, 405 + DY), (500, 405 + DY), (500, 500 + DY)],
        "bg",
    ),  # rear window
    (
        "poly",
        [(540, 500 + DY), (540, 405 + DY), (633, 405 + DY), (692, 500 + DY)],
        "bg",
    ),  # front window
    ("circle", (320, 660 + DY, 112), "bg"),  # wheel arches
    ("circle", (704, 660 + DY, 112), "bg"),
    ("circle", (320, 660 + DY, 84), "fg"),  # tyres
    ("circle", (704, 660 + DY, 84), "fg"),
    ("circle", (320, 660 + DY, 34), "bg"),  # hubs
    ("circle", (704, 660 + DY, 34), "bg"),
]


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def master() -> Image.Image:
    s = SIZE * SS
    image = Image.new("RGB", (s, s), BG)
    draw = ImageDraw.Draw(image)
    for kind, g, colour in SHAPES:
        fill = FG if colour == "fg" else BG
        if kind == "rrect":
            x0, y0, x1, y1, r = g
            draw.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], r * SS, fill=fill)
        elif kind == "poly":
            draw.polygon([(x * SS, y * SS) for x, y in g], fill=fill)
        else:
            cx, cy, r = g
            draw.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], fill=fill)
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def svg() -> str:
    parts = []
    for kind, g, colour in SHAPES:
        fill = _hex(FG) if colour == "fg" else _hex(BG)
        if kind == "rrect":
            x0, y0, x1, y1, r = g
            parts.append(
                f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="{r}" fill="{fill}"/>'
            )
        elif kind == "poly":
            pts = " ".join(f"{x},{y}" for x, y in g)
            parts.append(f'<polygon points="{pts}" fill="{fill}"/>')
        else:
            parts.append(f'<circle cx="{g[0]}" cy="{g[1]}" r="{g[2]}" fill="{fill}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">'
        f'<rect width="{SIZE}" height="{SIZE}" fill="{_hex(BG)}"/>' + "".join(parts) + "</svg>\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    image = master()
    targets = {
        "icon-192.png": (192, "RGBA"),
        "icon-512.png": (512, "RGBA"),
        "icon-maskable-512.png": (512, "RGBA"),
        "apple-touch-icon.png": (180, "RGB"),
    }
    for name, (size, mode) in targets.items():
        image.resize((size, size), Image.LANCZOS).convert(mode).save(OUT / name, optimize=True)
    (OUT / "icon.svg").write_text(svg())
    print(f"hue {HUE}, background {_hex(BG)}")


if __name__ == "__main__":
    main()
