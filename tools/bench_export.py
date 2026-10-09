"""Batch export throughput check (CONTRACT-export XP8, ADR-0003).

Makes 20 synthetic 24 MP (6000x4000) 8-bit sRGB JPEGs (different noise, EXIF with Orientation 1) and a synthetic
preset with a tone curve, exports one other photo first (warm-up, not counted), then exports the 20 in one
`build_facade(...).export` call as JPEG q92 into a temp folder. Pass:

  (a) wall time / 20 <= 0.8 s per photo
  (b) the stages overlap: wall time <= 0.7 x the sum over all photos of read + render + encode/write times

The median of each stage is printed. Skipped (reason printed) only while the GPU is really busy (the B7 / R1 rule
of darkroom_app.gpucheck) or without CUDA; --force measures anyway and labels the result.

  python -s tools/bench_export.py [--force] [--keep]
"""
import argparse
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

N_PHOTOS = 20                                # verbatim (XP8)
WIDTH, HEIGHT = 6000, 4000                   # verbatim (XP8)
QUALITY = 92                                 # verbatim (XP8)
PER_PHOTO_LIMIT_S = 0.8                      # verbatim (XP8)
OVERLAP_LIMIT = 0.7                          # verbatim (XP8)
PRESET = '''<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:ProcessVersion="11.0"
   crs:Version="15.3"
   crs:Exposure2012="+0.30"
   crs:Contrast2012="+15"
   crs:Highlights2012="-30"
   crs:Shadows2012="+25"
   crs:Clarity2012="+10"
   crs:Vibrance="+12"
   >
   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">bench curve</rdf:li>
    </rdf:Alt>
   </crs:Name>
   <crs:ToneCurvePV2012>
    <rdf:Seq>
     <rdf:li>0, 12</rdf:li>
     <rdf:li>64, 58</rdf:li>
     <rdf:li>128, 132</rdf:li>
     <rdf:li>192, 205</rdf:li>
     <rdf:li>255, 248</rdf:li>
    </rdf:Seq>
   </crs:ToneCurvePV2012>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
'''


def gpu_check():
    """(skip, message): skip without CUDA or while the GPU is really busy (darkroom_app.gpucheck, rule B7 / R1)."""
    import torch
    from darkroom_app import gpucheck
    if not torch.cuda.is_available():
        return True, "[XP8] 跳過：沒有 CUDA"
    busy, reason = gpucheck.gpu_busy()
    if busy is None or busy:
        return True, "[XP8] 跳過：" + reason
    return False, "[XP8] GPU 閒置，照常量測：" + reason


def _exif_app1():
    """APP1 Exif with Make, Model, Orientation 1 and a DateTimeOriginal."""
    import struct
    from PIL import Image
    ex = Image.Exif()
    ex[0x010F], ex[0x0110], ex[0x0112] = "BenchCam", "B-24", 1
    ex[0x8769] = {0x9003: "2026:10:09 12:00:00", 0x8827: 200}
    body = ex.tobytes()
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def make_photos(folder, n=N_PHOTOS, width=WIDTH, height=HEIGHT):
    """n + 1 JPEGs (the last one is the warm-up photo), each with its own noise; returns their paths."""
    import cv2
    import numpy as np
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    base = np.stack([xx / width, yy / height, 0.5 + 0.35 * np.sin(xx / 97.0) * np.cos(yy / 71.0)], -1)
    base = (np.clip(base, 0, 1) * 220 + 10).astype(np.uint8)
    app1 = _exif_app1()
    paths = []
    for i in range(n + 1):
        rng = np.random.default_rng(1000 + i)
        img = base + rng.integers(0, 24, base.shape, dtype=np.uint8)
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
        assert ok
        data = enc.tobytes()
        p = os.path.join(folder, f"bench-{i:02d}.jpg" if i < n else "warmup.jpg")
        with open(p, "wb") as f:
            f.write(data[:2] + app1 + data[2:])
        paths.append(p)
    return paths[:n], paths[n]


def measure(folder, n=N_PHOTOS, width=WIDTH, height=HEIGHT, log=print):
    """Run the XP8 measurement with every file inside `folder`. Returns a dict of the numbers."""
    from darkroom_app import encoding
    from darkroom_app import engine as engine_mod
    from darkroom_app.composition import build_facade
    from darkroom_app.services import export as export_mod
    photos_dir, presets_dir, out_dir = (os.path.join(folder, d) for d in ("photos", "presets", "out"))
    for d in (photos_dir, presets_dir, out_dir):
        os.makedirs(d)
    with open(os.path.join(presets_dir, "bench-curve.xmp"), "w", encoding="utf-8", newline="\n") as f:
        f.write(PRESET)
    t0 = time.perf_counter()
    photos, warm = make_photos(photos_dir, n, width, height)
    log(f"[XP8] 測試圖：{n} 張 {width}×{height} JPEG q{QUALITY}（產生 {time.perf_counter() - t0:.1f} 秒）")
    eng = engine_mod.Engine()
    try:
        facade = build_facade(presets_dir, engine=eng)
        item = {"preset_id": "bench-curve", "strength": 100}
        res = facade.export([{"path": warm, **item}], "jpeg", QUALITY, out_dir)["results"]
        if not res[0]["ok"]:
            raise RuntimeError(res[0]["error"])
        stages = {"read_image": [], "read_exif": [], "render": [], "write": []}
        lock = threading.Lock()

        def timed(name, fn):
            def wrapper(*a, **k):
                t = time.perf_counter()
                try:
                    return fn(*a, **k)
                finally:
                    with lock:
                        stages[name].append(time.perf_counter() - t)
            return wrapper
        with mock.patch.object(export_mod, "read_image", timed("read_image", export_mod.read_image)), \
                mock.patch.object(encoding, "read_exif", timed("read_exif", encoding.read_exif)), \
                mock.patch.object(eng, "render_full", timed("render", eng.render_full)), \
                mock.patch.object(export_mod.ExportService, "_write", timed("write", export_mod.ExportService._write)):
            t = time.perf_counter()
            res = facade.export([{"path": p, **item} for p in photos], "jpeg", QUALITY, out_dir)["results"]
            wall = time.perf_counter() - t
        failed = [r for r in res if not r["ok"]]
        if failed:
            raise RuntimeError(failed[0]["error"])
    finally:
        eng.shutdown()
    # the read stage is read_image + read_exif (both on the one reader thread, in order)
    stages["read"] = [a + b for a, b in zip(stages.pop("read_image"), stages.pop("read_exif"))]
    total = sum(sum(v) for v in stages.values())
    out = {"wall": wall, "per_photo": wall / n, "stage_sum": total, "overlap": wall / total,
           "median": {k: statistics.median(v) for k, v in stages.items()}}
    m = out["median"]
    log(f"[XP8] 每段中位數：讀檔 {m['read']:.3f} 秒、渲染 {m['render']:.3f} 秒、編碼寫檔 {m['write']:.3f} 秒")
    log(f"[XP8] 牆鐘 {wall:.2f} 秒（{out['per_photo']:.3f} 秒／張，門檻 ≤ {PER_PHOTO_LIMIT_S}）；"
        f"分段加總 {total:.2f} 秒，重疊比 {out['overlap']:.3f}（門檻 ≤ {OVERLAP_LIMIT}）")
    out["ok"] = out["per_photo"] <= PER_PHOTO_LIMIT_S and out["overlap"] <= OVERLAP_LIMIT
    return out


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="measure even while the GPU is busy")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder (prints its path)")
    a = ap.parse_args(argv)
    skip, msg = gpu_check()
    print(msg, flush=True)
    if skip and not a.force:
        return 0
    folder = tempfile.mkdtemp(prefix="darkroom-bench-export-")
    try:
        out = measure(folder, log=lambda s: print(s, flush=True))
    finally:
        if a.keep:
            print(f"[XP8] 暫存資料夾：{folder}")
        else:
            shutil.rmtree(folder, ignore_errors=True)
    tag = "（GPU 忙碌時以 --force 量測）" if skip else ""
    print(f"[XP8] {'通過' if out['ok'] else '未通過'}{tag}", flush=True)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
