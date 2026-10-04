"""Preview latency check (contract B7).

Starts the darkroom server on a free port, opens a 24 MP test photo (a public test photo upscaled into a temp
folder, or a synthetic one) and simulates dragging a slider at 60 Hz for 10 s with latest-wins sending: only
the newest parameters wait, and they go out as soon as the previous response has arrived. Round trip = request
sent -> JPEG received and decoded. Pass: median < 100 ms and p95 < 150 ms.

Skipped (reason printed) only while the GPU is really busy: median of 5 nvidia-smi utilization readings over
about 1 s above 15 %, or a ComfyUI process on the GPU whose /queue is not empty (unreachable = idle).
--force measures anyway and labels the result.

  python -s tools/bench_preview.py [--seconds 10] [--force] [--port 0]
"""
import argparse
import asyncio
import math
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from darkroom_app import gpucheck  # noqa: E402

HZ = 60
SECONDS = 10.0
MEGAPIXELS = 24.0
MEDIAN_LIMIT_MS = 100.0
P95_LIMIT_MS = 150.0
PHOTO = os.path.join(REPO, ".claude", "wayfinder", "darkroom", "prototypes", "llm-pick-experiment", "photos",
                     "landscape_lighthouse.png")


def gpu_check(**kw):
    """(skip, message). Skip only while someone is really using the GPU (see darkroom_app.gpucheck)."""
    busy, reason = gpucheck.gpu_busy(**kw)
    if busy is None or busy:
        return True, "[B7] 跳過：" + reason
    return False, "[B7] GPU 閒置，照常量測：" + reason


def make_test_image(folder, megapixels=MEGAPIXELS):
    """24 MP JPEG in `folder`: the public test photo upscaled, or a synthetic image if it is missing."""
    import cv2
    import numpy as np
    src = None
    if os.path.exists(PHOTO):
        with open(PHOTO, "rb") as f:
            src = cv2.imdecode(np.frombuffer(f.read(), np.uint8), cv2.IMREAD_COLOR)
    if src is None:
        yy, xx = np.mgrid[0:1000, 0:1500].astype(np.float32)
        src = (np.stack([xx / 1500, yy / 1000, 0.5 + 0.4 * np.sin(xx / 40) * np.cos(yy / 30)], -1) * 255).astype(np.uint8)
    h, w = src.shape[:2]
    s = math.sqrt(megapixels * 1e6 / (w * h))
    big = cv2.resize(src, (round(w * s), round(h * s)), interpolation=cv2.INTER_CUBIC)
    path = os.path.join(folder, "bench-24mp.jpg")
    ok, buf = cv2.imencode(".jpg", big, [cv2.IMWRITE_JPEG_QUALITY, 92])
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return path, big.shape[1], big.shape[0]


def start_server(port):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.Popen([sys.executable, "-s", "-m", "darkroom_app", "--port", str(port)], cwd=REPO, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    box = []

    def reader():
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith("darkroom 已啟動"):
                box.append(line)
                break
        for _ in p.stdout:   # keep draining
            pass
    threading.Thread(target=reader, daemon=True).start()
    deadline = time.time() + 180
    while not box and time.time() < deadline and p.poll() is None:
        time.sleep(0.1)
    if not box:
        stop_server(p)
        raise RuntimeError("server did not start")
    return p


def stop_server(p):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()


def pct(a, q):
    b = sorted(a)
    return b[min(len(b) - 1, int(q * (len(b) - 1) + 0.5))]


async def pick_preset(session, base):
    async with session.get(base + "api/presets") as r:
        rows = await r.json()
    for row in rows:
        if not row["supported"]:
            continue
        async with session.get(base + "api/presets/" + row["id"]) as r:
            v = (await r.json())["values"]
        if v["Clarity2012"] and v["Texture"] and v["Highlights2012"]:
            return row
    return rows[0]


async def drag(session, base, image_id, preset_id, seconds, hz):
    import cv2
    import numpy as np
    latest = {"body": None, "t": 0.0, "sent": True}
    rtts, lags, render_ms, events = [], [], [], 0
    done = False

    async def producer():
        nonlocal events
        # Slider events on a fixed 60 Hz grid (Windows timers are ~15 ms coarse, so poll and catch up by tick).
        t0 = time.perf_counter()
        last_tick = -1
        while True:
            el = time.perf_counter() - t0
            if el >= seconds:
                break
            tick = int(el * hz)
            if tick > last_tick:
                events += tick - last_tick
                last_tick = tick
                ph = tick / hz * 2 * math.pi * 0.5
                latest.update(body={"image_id": image_id, "preset_id": preset_id,
                                    "strength": round(100 + 90 * math.sin(ph), 2),
                                    "overrides": {"Exposure2012": round(0.5 * math.sin(ph * 1.3), 3),
                                                  "Clarity2012": 15.0}},
                              t=t0 + tick / hz, sent=False)
            await asyncio.sleep(0)
            await asyncio.sleep(0.001)

    async def sender():
        while not done:
            if latest["sent"]:
                await asyncio.sleep(0.001)
                continue
            latest["sent"] = True
            body, t_change = latest["body"], latest["t"]
            t0 = time.perf_counter()
            async with session.post(base + "api/preview", json=body) as r:
                data = await r.read()
                ms = float(r.headers["X-Render-Ms"])
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            assert img is not None
            t1 = time.perf_counter()
            rtts.append((t1 - t0) * 1000)
            lags.append((t1 - t_change) * 1000)
            render_ms.append(ms)

    prod = asyncio.ensure_future(producer())
    send = asyncio.ensure_future(sender())
    await prod
    done = True
    await send
    return rtts, lags, render_ms, events


async def run(args):
    import aiohttp
    skip, msg = gpu_check()
    print(msg, flush=True)
    if skip and not args.force:
        return 0
    forced = skip
    tmp = tempfile.mkdtemp(prefix="darkroom-bench-")
    server = None
    try:
        path, w, h = make_test_image(tmp)
        print(f"[B7] 測試圖：{w}×{h}（{w * h / 1e6:.1f} MP）", flush=True)
        port = args.port or _free_port()
        server = start_server(port)
        skip2, msg2 = gpu_check()
        if skip2 and not args.force:
            print(msg2, flush=True)
            return 0
        forced = forced or skip2
        base = f"http://127.0.0.1:{port}/"
        async with aiohttp.ClientSession() as s:
            t0 = time.perf_counter()
            async with s.post(base + "api/open", json={"path": path}) as r:
                info = await r.json()
            print(f"[B7] 開啟 24MP：{(time.perf_counter() - t0) * 1000:.0f} ms，預覽 "
                  f"{info['preview_width']}×{info['preview_height']}", flush=True)
            preset = await pick_preset(s, base)
            for _ in range(5):   # warm up
                async with s.post(base + "api/preview", json={"image_id": info["image_id"], "preset_id": preset["id"],
                                                              "strength": 100, "overrides": {}}) as r:
                    await r.read()
            rtts, lags, render_ms, events = await drag(s, base, info["image_id"], preset["id"], args.seconds, HZ)
        med, p95 = statistics.median(rtts), pct(rtts, 0.95)
        ok = med < MEDIAN_LIMIT_MS and p95 < P95_LIMIT_MS
        tag = "（GPU 忙碌時以 --force 量測）" if forced else ""
        print(f"[B7] preset：{preset['name']}；滑桿事件 {events} 次 / 送出 {len(rtts)} 次", flush=True)
        print(f"[B7] 往返 中位數 {med:.1f} ms、p95 {pct(rtts, 0.95):.1f} ms、最大 {max(rtts):.1f} ms；"
              f"拖動到畫面 中位數 {statistics.median(lags):.1f} ms、p95 {pct(lags, 0.95):.1f} ms；"
              f"後端渲染 中位數 {statistics.median(render_ms):.1f} ms、p95 {pct(render_ms, 0.95):.1f} ms{tag}", flush=True)
        print(f"[B7] {'通過' if ok else '未通過'}（門檻：中位數 < {MEDIAN_LIMIT_MS:.0f} ms、p95 < {P95_LIMIT_MS:.0f} ms）",
              flush=True)
        return 0 if ok else 1
    finally:
        if server is not None:
            stop_server(server)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=SECONDS)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="measure even when other compute processes are present")
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
