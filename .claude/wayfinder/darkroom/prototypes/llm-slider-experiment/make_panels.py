"""Render the models' adjustments with render.py and build side-by-side PNGs.

python -s make_panels.py
  panels/<photo>.png        original | 35B seed101 | PE-I2I seed101, with diagnosis + values below
  panels/wish_<photo>.png   original | 35B neutral | 35B wish | PE neutral | PE wish
All renders are a ROUGH approximation of Lightroom (see render.py), not the final engine.
"""
import json
import os
import sys
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render  # noqa: E402
from analyze import PHOTO_ORDER, fmt_adj  # noqa: E402
from run_sliders import PHOTOS_DIR, PHOTOS_JSON, WISHES, ADJ_KEYS  # noqa: E402

FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msjh.ttc")
f_title = ImageFont.truetype(FONT, 22)
f_txt = ImageFont.truetype(FONT, 16)
PANEL_H = 440
OUT = os.path.join(HERE, "panels")


def rec(m, photo, run):
    p = os.path.join(HERE, "raw", m, f"{photo}__{run}.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def adj_of(r):
    return ((r or {}).get("parsed") or {}).get("adjustments") or {}


def text_block(draw, x, y, w, lines, font=f_txt, fill=(30, 30, 30)):
    cw = max(10, int(w / 8.6))
    for ln in lines:
        for sub in textwrap.wrap(ln, cw) or [""]:
            draw.text((x, y), sub, font=font, fill=fill)
            y += 21
    return y


def describe(r, label):
    if not r or not r.get("valid"):
        return [f"{label}: (no valid response)"]
    p = r["parsed"]
    d = p["diagnosis"]
    return [f"{label}  ({r['wall_s']}s)",
            f"Diag: {d['subject']} | WB {d['white_balance']} | exp {d['exposure']} | contrast {d['contrast']}",
            "Problems: " + "; ".join(d["main_problems"]),
            "Values: " + fmt_adj(p["adjustments"]),
            "Intent: " + p["intent"]]


def main():
    os.makedirs(OUT, exist_ok=True)
    photos = {p["id"]: p for p in json.load(open(PHOTOS_JSON, encoding="utf-8"))}
    for pid in PHOTO_ORDER:
        im = Image.open(os.path.join(PHOTOS_DIR, photos[pid]["file"])).convert("RGB")
        im.thumbnail((1400, 1400))
        src = np.asarray(im)
        tiles = [("Original", src)]
        rA, rB = rec("A", pid, "base_s101"), rec("B", pid, "base_s101")
        tiles.append(("35B-A3B seed101", render.apply(src, adj_of(rA))))
        tiles.append(("PE-I2I seed101", render.apply(src, adj_of(rB))))
        build(os.path.join(OUT, f"{pid}.png"), pid, tiles,
              [describe(rA, "35B-A3B"), describe(rB, "PE-I2I")])
        if pid in WISHES:
            w = WISHES[pid]
            rs = [("A", "base_s101", "35B neutral"), ("A", f"{w['tag']}_s101", "35B WISH"),
                  ("B", "base_s101", "PE neutral"), ("B", f"{w['tag']}_s101", "PE WISH")]
            tiles = [("Original", src)] + [(lab, render.apply(src, adj_of(rec(m, pid, run)))) for m, run, lab in rs]
            texts = []
            for m, run, lab in rs:
                r = rec(m, pid, run)
                texts.append([lab, fmt_adj(adj_of(r)), "Intent: " + (((r or {}).get("parsed") or {}).get("intent") or "-")])
            build(os.path.join(OUT, f"wish_{pid}.png"), f"{pid}  WANT: {w['want']} / NOT: {w['avoid']}", tiles, texts)
        print("panel", pid, flush=True)


def build(path, title, tiles, texts):
    ims = []
    for lab, a in tiles:
        t = Image.fromarray(a)
        t = t.resize((max(1, round(t.width * PANEL_H / t.height)), PANEL_H), Image.LANCZOS)
        ims.append((lab, t))
    W = sum(t.width for _, t in ims) + 10 * (len(ims) + 1)
    W = max(W, 1200)
    col_w = (W - 10 * (len(texts) + 1)) // len(texts)
    # measure text height
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    hs = [text_block(tmp, 0, 0, col_w, t) for t in texts]
    H = 40 + 28 + PANEL_H + 20 + max(hs) + 20
    canvas = Image.new("RGB", (W, H), (245, 245, 242))
    dr = ImageDraw.Draw(canvas)
    dr.text((10, 8), title + "   [rough approximate render, not Lightroom]", font=f_title, fill=(0, 0, 0))
    x = 10
    for lab, t in ims:
        dr.text((x, 42), lab, font=f_txt, fill=(60, 60, 60))
        canvas.paste(t, (x, 68))
        x += t.width + 10
    y0 = 68 + PANEL_H + 20
    for i, t in enumerate(texts):
        text_block(dr, 10 + i * (col_w + 10), y0, col_w, t)
    canvas.save(path, optimize=True)


if __name__ == "__main__":
    main()
