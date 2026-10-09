"""Photo library speed (CONTRACT-photo-library PL16, PLP7): thumbnails, the warm grid and the fingerprint.

Everything is made by the script in %TEMP%/darkroom-bench-photos-*: 500 4000x3000 JPEG q90 without an embedded
thumbnail, 50 4000x3000 HEIC without thumbnails, one ~10 MB photo and one 2 GB file; data_dir is a folder next to
them. The real preset library is only read; the real %LOCALAPPDATA%/darkroom is never touched. Thresholds (never
relaxed, PL16):
  (a) cold (empty thumbnail cache): from the folder_thumbnails call, the first 40 thumbnails each obtainable within
      1.5 s in total; all 500 in the cache within 15 s
  (b) warm (a fresh service, full cache): folder_thumbnails <= 0.3 s; 500 thumbnail() calls <= 2 s with the photo
      files opened 0 times
  (c) 50 HEIC cold: first 40 <= 4 s, all <= 12 s
  (d) fingerprint: a 2 GB file already in the OS cache >= 600 MB/s single-threaded; the ~10 MB photo's fingerprint
      (what open_photo adds) <= 30 ms
"Cold" only means the thumbnail cache is empty; the OS file cache is not controlled (its state is printed as "files
just written"). Skipped like B7 / R1 (darkroom_app.gpucheck) while the GPU is really busy; --force measures anyway
(this bench does not use the GPU, so forced numbers count). A miss prints the stage split (read / hash / decode+encode
/ write) and a cProfile top 20 of that step (ADR-0003: profile before anything else).

  python -s tools/bench_photo_library.py [--force] [--keep] [--jpegs 500] [--heics 50] [--gb 2]
"""
import argparse
import builtins
import cProfile
import io
import os
import pstats
import shutil
import sys
import tempfile
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

LIMITS = {"(a) cold JPEG: first 40": 1.5, "(a) cold JPEG: all 500": 15.0, "(b) warm: folder_thumbnails": 0.3,
          "(b) warm: 500 thumbnail()": 2.0, "(b) warm: photo opens": 0, "(c) cold HEIC: first 40": 4.0,
          "(c) cold HEIC: all 50": 12.0, "(d) fingerprint MB/s (min)": 600.0, "(d) open_photo extra ms": 30.0}
FIRST_SCREEN = 40


def gpu_skip():
    from darkroom_app import gpucheck
    busy, reason = gpucheck.gpu_busy()
    if busy is None or busy:
        return True, "[PL16] 跳過：" + reason
    return False, "[PL16] GPU 閒置，照常量測：" + reason


def profiled(fn):
    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    out = io.StringIO()
    pstats.Stats(pr, stream=out).sort_stats("cumulative").print_stats(20)
    return out.getvalue()


def make_jpegs(folder, n, w=4000, h=3000):
    import cv2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.stack([xx / w, yy / h, 0.5 + 0.4 * np.sin(xx / 97) * np.cos(yy / 61)], -1)
    for i in range(n):
        img = np.clip(base + 0.02 * ((i % 7) - 3), 0, 1)
        img[:: 50 + i % 13] *= 0.9                      # different content per file (different fingerprints)
        ok, buf = cv2.imencode(".jpg", (img * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 90])
        assert ok
        with open(os.path.join(folder, f"bench_{i:04d}.jpg"), "wb") as f:
            f.write(buf.tobytes())                      # cv2 writes no EXIF: no embedded thumbnail
        if i % 50 == 49:
            print(f"  JPEG {i + 1}/{n}", flush=True)


def make_heics(folder, n, w=4000, h=3000):
    import pillow_heif
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.stack([xx / w, yy / h, 0.5 + 0.4 * np.sin(xx / 97) * np.cos(yy / 61)], -1)
    for i in range(n):
        img = (np.clip(base + 0.02 * ((i % 7) - 3), 0, 1) * 255).astype(np.uint8)
        hf = pillow_heif.from_bytes(mode="RGB", size=(w, h), data=np.ascontiguousarray(img).tobytes())
        hf.save(os.path.join(folder, f"bench_{i:03d}.heic"), quality=80)   # no thumbnails
        if i % 10 == 9:
            print(f"  HEIC {i + 1}/{n}", flush=True)


def make_big(path, gb):
    chunk = (np.arange(1 << 20, dtype=np.uint8) * 7).tobytes()
    with open(path, "wb") as f:
        for _ in range(int(gb * 1024)):
            f.write(chunk)


def cold_run(facade, folder, n, first=FIRST_SCREEN):
    """(seconds until the first `first` thumbnails are obtainable, seconds until all are cached)."""
    lib = facade._photo_library
    t0 = time.perf_counter()
    listing = facade.folder_thumbnails(folder)
    for item in listing["items"][:first]:
        facade.thumbnail(item["path"])                  # direct requests jump the queue (PL12)
    t_first = time.perf_counter() - t0
    assert lib.wait_thumbnails(600)
    t_all = time.perf_counter() - t0
    assert all(i["cached"] for i in facade.folder_thumbnails(folder)["items"]), "not everything is cached"
    return t_first, t_all


def stage_split(paths, data_dir):
    """Median seconds of read / hash / decode+encode / write for the first 20 files (for a miss)."""
    import statistics
    from darkroom_app import safe_write
    from darkroom_app.services import photo_library as pl
    out_dir = os.path.join(data_dir, "profile-split")
    os.makedirs(out_dir, exist_ok=True)
    rows = {"read": [], "hash": [], "decode+encode": [], "write": []}
    for k, p in enumerate(paths[:20]):
        t = time.perf_counter()
        with open(p, "rb") as f:
            data = f.read()
        rows["read"].append(time.perf_counter() - t)
        t = time.perf_counter()
        pl.fingerprint_bytes(data)
        rows["hash"].append(time.perf_counter() - t)
        t = time.perf_counter()
        jpeg = pl.make_thumbnail(data, os.path.splitext(p)[1].lower())
        rows["decode+encode"].append(time.perf_counter() - t)
        t = time.perf_counter()
        safe_write.create_new(os.path.join(out_dir, f"{k}.jpg"), out_dir, jpeg, preset_dir=os.path.dirname(data_dir))
        rows["write"].append(time.perf_counter() - t)
    return {k: statistics.median(v) * 1000 for k, v in rows.items()}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="measure even while the GPU is busy")
    ap.add_argument("--keep", action="store_true", help="keep the temporary photos and data_dir")
    ap.add_argument("--jpegs", type=int, default=500)
    ap.add_argument("--heics", type=int, default=50)
    ap.add_argument("--gb", type=float, default=2.0)
    a = ap.parse_args(argv)
    skip, msg = gpu_skip()
    print(msg)
    if skip and not a.force:
        return 0
    from darkroom_app import config
    from darkroom_app.composition import build_facade
    from darkroom_app.services import photo_library as pl
    preset_dir = config.preset_dir()                  # the real presets, only read
    root = tempfile.mkdtemp(prefix="darkroom-bench-photos-")
    jpegs, heics, data = (os.path.join(root, n) for n in ("jpeg", "heic", "data"))
    os.makedirs(jpegs)
    os.makedirs(heics)
    res, profiles = {}, {}
    try:
        t = time.perf_counter()
        print(f"產生 {a.jpegs} 張 4000×3000 JPEG q90（無內嵌縮圖）…", flush=True)
        make_jpegs(jpegs, a.jpegs)
        print(f"產生 {a.heics} 張 4000×3000 HEIC（無縮圖）…", flush=True)
        make_heics(heics, a.heics)
        print(f"  照片產生 {time.perf_counter() - t:.0f} s；OS 檔案快取狀態：剛寫入（未控制）", flush=True)
        print(f"暫存：{root}；data_dir：{data}；執行緒 {pl.THUMB_WORKERS}", flush=True)

        f = build_facade(preset_dir, data_dir=data)
        res["(a) cold JPEG: first 40"], res["(a) cold JPEG: all 500"] = cold_run(f, jpegs, a.jpegs)
        res["(c) cold HEIC: first 40"], res["(c) cold HEIC: all 50"] = cold_run(f, heics, a.heics)

        g = build_facade(preset_dir, data_dir=data)   # a fresh service: everything from the index and the cache
        opened = []
        real_open = builtins.open
        photos_prefix = os.path.normcase(jpegs) + os.sep

        def spy(file, *args, **kw):
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.normcase(os.fsdecode(file)).startswith(photos_prefix):
                opened.append(file)
            return real_open(file, *args, **kw)
        builtins.open = spy
        try:
            t = time.perf_counter()
            listing = g.folder_thumbnails(jpegs)
            res["(b) warm: folder_thumbnails"] = time.perf_counter() - t
            assert all(i["cached"] and i["fingerprint"] for i in listing["items"]), "warm listing not all cached"
            t = time.perf_counter()
            for item in listing["items"]:
                g.thumbnail(item["path"])
            res["(b) warm: 500 thumbnail()"] = time.perf_counter() - t
        finally:
            builtins.open = real_open
        res["(b) warm: photo opens"] = len(opened)

        big = os.path.join(root, "big.bin")
        print(f"產生 {a.gb:g} GB 檔案並讀一次（進 OS 快取）…", flush=True)
        make_big(big, a.gb)
        with open(big, "rb") as fh:
            while fh.read(1 << 24):
                pass
        best = 0.0
        for _ in range(2):
            t = time.perf_counter()
            pl.fingerprint(big)
            best = max(best, os.path.getsize(big) / (1 << 20) / (time.perf_counter() - t))
        res["(d) fingerprint MB/s (min)"] = best
        ten = os.path.join(root, "ten.jpg")
        shutil.copyfile(os.path.join(jpegs, "bench_0000.jpg"), ten)
        with open(ten, "ab") as fh:
            fh.write(b"\0" * max(0, 10 * (1 << 20) - os.path.getsize(ten)))   # ~10 MB (padding after EOI is legal)
        pl.fingerprint(ten)
        times = []
        for _ in range(5):
            t = time.perf_counter()
            pl.fingerprint(ten)
            times.append(time.perf_counter() - t)
        res["(d) open_photo extra ms"] = sorted(times)[len(times) // 2] * 1000

        if (res["(a) cold JPEG: first 40"] > LIMITS["(a) cold JPEG: first 40"]
                or res["(a) cold JPEG: all 500"] > LIMITS["(a) cold JPEG: all 500"]):
            paths = [os.path.join(jpegs, n) for n in sorted(os.listdir(jpegs))]
            profiles["(a) JPEG stage split (median ms)"] = str(stage_split(paths, data))
            profiles["(a) JPEG cProfile"] = profiled(lambda: [pl.make_thumbnail(open(p, "rb").read(), ".jpg") for p in paths[:20]])
        if (res["(c) cold HEIC: first 40"] > LIMITS["(c) cold HEIC: first 40"]
                or res["(c) cold HEIC: all 50"] > LIMITS["(c) cold HEIC: all 50"]):
            paths = [os.path.join(heics, n) for n in sorted(os.listdir(heics))]
            profiles["(c) HEIC stage split (median ms)"] = str(stage_split(paths, data))
            profiles["(c) HEIC cProfile"] = profiled(lambda: [pl.make_thumbnail(open(p, "rb").read(), ".heic") for p in paths[:10]])
        if res["(b) warm: 500 thumbnail()"] > LIMITS["(b) warm: 500 thumbnail()"]:
            profiles["(b) warm cProfile"] = profiled(lambda: [g.thumbnail(i["path"]) for i in listing["items"][:100]])
        if res["(d) fingerprint MB/s (min)"] < LIMITS["(d) fingerprint MB/s (min)"]:
            profiles["(d) fingerprint cProfile"] = profiled(lambda: pl.fingerprint(big))
    finally:
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)
    ok = True
    for k, lim in LIMITS.items():
        v = res[k]
        if k == "(d) fingerprint MB/s (min)":
            good, shown = v >= lim, f"{v:.0f} MB/s（門檻 ≥ {lim:.0f}）"
        elif k == "(d) open_photo extra ms":
            good, shown = v <= lim, f"{v:.1f} ms（門檻 ≤ {lim:.0f}）"
        elif k == "(b) warm: photo opens":
            good, shown = v == lim, f"{v} 次（門檻 {lim}）"
        else:
            good, shown = v <= lim, f"{v:.2f} s（門檻 ≤ {lim:g}）"
        ok &= good
        print(f"{'OK ' if good else 'MISS'} {k}: {shown}")
    for k, text in profiles.items():
        print(f"\n[{k}]\n{text}")
    print("PL16：全部達標" if ok else "PL16：有未達標項目")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
