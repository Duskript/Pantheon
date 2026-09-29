#!/usr/bin/env python3
"""Build a labelled contact sheet from the image-model sweep manifest.

WHY A CONTACT SHEET
-------------------
A model comparison is only useful if it is scannable. Twenty-six separate PNG
attachments in a chat thread cannot be compared - you cannot hold them in view at
once, and you lose track of which file was which model. A single labelled grid puts
every model's output on the same screen, under the same prompt, with its price and
generation time attached to the cell.

INPUT
-----
`manifest.json` written by `image-model-sweep.py`. Each row carries:

    model       the catalogue id, e.g. "fal-ai/nano-banana-pro"
    display     the human name, e.g. "Nano Banana Pro (Gemini 3 Pro Image)"
    price       the catalogue price string, e.g. "$0.15/image (1K)"
    ok          whether generation + download succeeded
    file        absolute path to the downloaded PNG (when ok)
    error       the failure text (when not ok)
    seconds     wall-clock generation time

Rows that failed are still shown, in a final cell, so a partially-successful sweep
never looks like a complete one.

OUTPUT
------
`contact-sheet.png` - dark card grid, 5 columns by default, each cell holding the
image scaled to fit plus the model name, price, real pixel dimensions and time.

Usage
-----
    image-model-contact-sheet.py [--dir DIR] [--cols 5]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# DejaVu ships with the base image and has no missing-glyph surprises for the
# model names and price strings we render here.
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Dark theme so the photographs carry the sheet rather than the chrome.
BG = (18, 18, 20)
CARD = (30, 30, 34)
FG = (240, 240, 245)
DIM = (150, 150, 160)
BAD = (230, 140, 140)


def build_sheet(sweep_dir: Path, cols: int) -> Path:
    """Render the contact sheet and return its path."""
    manifest = json.loads((sweep_dir / "manifest.json").read_text())
    rows = [r for r in manifest if r.get("ok") and r.get("file") and Path(r["file"]).exists()]
    failed = [r for r in manifest if not r.get("ok")]

    # Geometry: fixed cell size keeps the grid regular regardless of each model's
    # native output size, which varies a lot across this catalogue.
    cell_w, cell_h = 430, 300
    img_h = 242
    pad = 14
    n_cells = len(rows) + (1 if failed else 0)
    grid_rows = max(1, (n_cells + cols - 1) // cols)
    header_h = 92

    sheet_w = pad + cols * (cell_w + pad)
    sheet_h = header_h + pad + grid_rows * (cell_h + pad)
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)

    f_title = ImageFont.truetype(FONT_BOLD, 30)
    f_sub = ImageFont.truetype(FONT_REG, 17)
    f_name = ImageFont.truetype(FONT_BOLD, 17)
    f_meta = ImageFont.truetype(FONT_REG, 15)

    draw.text((pad + 6, 20), "Nous Portal image models - one identical prompt",
              font=f_title, fill=FG)
    draw.text((pad + 6, 58),
              f"{len(rows)} models rendered  |  prompt: small business owner at a tidy "
              f"desk, warm morning light, editorial photography",
              font=f_sub, fill=DIM)

    for i, r in enumerate(rows):
        cx = pad + (i % cols) * (cell_w + pad)
        cy = header_h + pad + (i // cols) * (cell_h + pad)
        draw.rounded_rectangle([cx, cy, cx + cell_w, cy + cell_h], radius=10, fill=CARD)

        dims = "?"
        try:
            im = Image.open(r["file"]).convert("RGB")
            # thumbnail() preserves aspect; we then centre the result in the cell so
            # portrait and landscape outputs both sit tidily in the same grid.
            im.thumbnail((cell_w - 16, img_h))
            ox = cx + (cell_w - im.width) // 2
            oy = cy + 8 + (img_h - im.height) // 2
            sheet.paste(im, (ox, oy))
            dims = f"{im.width}x{im.height}"
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not kill the sheet
            draw.text((cx + 10, cy + 20), f"unreadable: {exc}", font=f_meta, fill=BAD)

        ty = cy + img_h + 14
        draw.text((cx + 12, ty), r["display"][:40], font=f_name, fill=FG)
        draw.text((cx + 12, ty + 22),
                  f"{r.get('price', '')}  |  {dims}  |  {r.get('seconds', '?')}s",
                  font=f_meta, fill=DIM)

    if failed:
        i = len(rows)
        cx = pad + (i % cols) * (cell_w + pad)
        cy = header_h + pad + (i // cols) * (cell_h + pad)
        draw.rounded_rectangle([cx, cy, cx + cell_w, cy + cell_h], radius=10, fill=CARD)
        draw.text((cx + 12, cy + 12), f"{len(failed)} model(s) failed",
                  font=f_name, fill=BAD)
        yy = cy + 40
        for r in failed[:6]:
            draw.text((cx + 12, yy), f"- {r['display'][:44]}", font=f_meta, fill=DIM)
            yy += 20

    out = sweep_dir / "contact-sheet.png"
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/home/konan/pantheon/phone-queue/image-model-sweep")
    ap.add_argument("--cols", type=int, default=5)
    args = ap.parse_args()

    sweep_dir = Path(args.dir)
    out = build_sheet(sweep_dir, args.cols)
    manifest = json.loads((sweep_dir / "manifest.json").read_text())
    ok = sum(1 for r in manifest if r.get("ok"))
    print(f"contact sheet: {out}  ({Image.open(out).size[0]}x{Image.open(out).size[1]})")
    print(f"  {ok} rendered, {len(manifest) - ok} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
