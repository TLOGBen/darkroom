"""Preset library speed (CONTRACT-preset-library K20, KP7): the real 1466 presets, copied to a temporary library.

The user's preset folder is only read (copied byte for byte into %TEMP%/darkroom-bench-lib-*/xmp, which is deleted
afterwards). Thresholds (never relaxed): cold load (no index) median of 3 <= 2.0 s; list_presets(query) and
preset_groups() 200 calls each p95 <= 20 ms; rename / move / favorite 50 each (lock, re-read, atomic write) p95
<= 150 ms; importing 20 files <= 1.5 s; save_user_preset 20 calls p95 <= 300 ms; the first list_presets after
another facade changed the index <= 200 ms. Skipped like B7 / R1 (darkroom_app.gpucheck) while the GPU is really
busy; --force measures anyway. A miss prints a cProfile top 20 of that step (ADR-0003: profile before anything else).

  python -s tools/bench_preset_library.py [--force] [--keep]
"""
import argparse
import cProfile
import io
import os
import pstats
import shutil
import statistics
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

LIMITS = {"cold load (median of 3)": 2.0, "list_presets(query) p95": 0.020, "preset_groups p95": 0.020,
          "rename p95": 0.150, "move p95": 0.150, "favorite p95": 0.150, "import 20": 1.5,
          "save_user_preset p95": 0.300, "list after external change (max of 10)": 0.200}   # verbatim (K20)


def p95(xs):
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)]


def profiled(fn):
    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    out = io.StringIO()
    pstats.Stats(pr, stream=out).sort_stats("cumulative").print_stats(20)
    return out.getvalue()


def gpu_skip():
    from darkroom_app import gpucheck
    busy, reason = gpucheck.gpu_busy()
    if busy is None or busy:
        return True, "[K20] 跳過：" + reason
    return False, "[K20] GPU 閒置，照常量測：" + reason


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="measure even while the GPU is busy")
    ap.add_argument("--keep", action="store_true", help="keep the temporary library")
    a = ap.parse_args(argv)
    skip, msg = gpu_skip()
    print(msg)
    if skip and not a.force:
        return 0
    from darkroom_app import config
    from darkroom_app.composition import build_facade
    from darkroom_app.presets import Library
    real = config.preset_dir()
    root = tempfile.mkdtemp(prefix="darkroom-bench-lib-")
    pd = os.path.join(root, "xmp")
    os.makedirs(pd)
    names = sorted(n for n in os.listdir(real) if n.lower().endswith(".xmp"))
    for n in names:
        shutil.copyfile(os.path.join(real, n), os.path.join(pd, n))      # the real folder is only read
    print(f"暫存庫：{root}（{len(names)} 個 xmp）")
    res, profiles = {}, {}
    try:
        cold = []
        for _ in range(3):
            t = time.perf_counter()
            Library(pd)
            cold.append(time.perf_counter() - t)
        res["cold load (median of 3)"] = statistics.median(cold)
        f = build_facade(pd)
        ids = [r["id"] for r in f.list_presets()["items"]]
        words = ["a", "Film", "電影", "warm", "x", "人像", "B&W", "e"]
        t_q = []
        for i in range(200):
            t = time.perf_counter()
            f.list_presets(words[i % len(words)])
            t_q.append(time.perf_counter() - t)
        res["list_presets(query) p95"] = p95(t_q)
        t_g = []
        for _ in range(200):
            t = time.perf_counter()
            f.preset_groups()
            t_g.append(time.perf_counter() - t)
        res["preset_groups p95"] = p95(t_g)
        for label, fn in (("rename p95", lambda i: f.rename_preset(ids[i], f"名稱 {i}")),
                          ("move p95", lambda i: f.move_preset(ids[i], f"Bench - 群 {i % 7}")),
                          ("favorite p95", lambda i: f.set_favorite(ids[i], i % 2 == 0))):
            ts = []
            for i in range(50):
                t = time.perf_counter()
                fn(i)
                ts.append(time.perf_counter() - t)
            res[label] = p95(ts)
            if res[label] > LIMITS[label]:
                profiles[label] = profiled(lambda: fn(51))
        src = os.path.join(root, "src")
        os.makedirs(src)
        for i, n in enumerate(names[:20]):
            with open(os.path.join(pd, n), "rb") as fh:
                data = fh.read()
            with open(os.path.join(src, f"new-{i:02d}.xmp"), "wb") as fh:
                fh.write(data + f"\n<!-- bench {i} -->\n".encode())       # new content, not a duplicate
        t = time.perf_counter()
        r = f.import_presets([src])
        res["import 20"] = time.perf_counter() - t
        assert all(x["ok"] for x in r["results"]) and len(r["results"]) == 20, r
        ts = []
        for i in range(20):
            t = time.perf_counter()
            f.save_user_preset(f"bench {i}", preset_id=ids[i], strength=120, overrides={"Exposure2012": 0.1})
            ts.append(time.perf_counter() - t)
        res["save_user_preset p95"] = p95(ts)
        other = build_facade(pd)
        ts = []
        for i in range(10):
            other.set_favorite(ids[100 + i], True)
            t = time.perf_counter()
            listing = f.list_presets()
            ts.append(time.perf_counter() - t)
            assert any(x["id"] == ids[100 + i] and x["favorite"] for x in listing["items"])
        res["list after external change (max of 10)"] = max(ts)
        if res["cold load (median of 3)"] > LIMITS["cold load (median of 3)"]:
            profiles["cold load (median of 3)"] = profiled(lambda: Library(pd))
    finally:
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)
    ok = True
    for k, lim in LIMITS.items():
        good = res[k] <= lim
        ok &= good
        print(f"{'OK ' if good else 'MISS'} {k}: {res[k] * 1000:.1f} ms（門檻 {lim * 1000:.0f} ms）")
    for k, text in profiles.items():
        print(f"\n[cProfile] {k}\n{text}")
    print("K20：全部達標" if ok else "K20：有未達標項目")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
