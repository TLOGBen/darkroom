"""Throwaway latency prototype: slider -> ComfyUI route -> torch grading on GPU -> JPEG -> browser.

Copy this folder to ComfyUI/custom_nodes/ for a test, delete the copy afterwards.
Routes (all on the ComfyUI server):
  GET  /lr_preview/page      test page (page.html)
  POST /lr_preview           JSON params -> image/jpeg (timings in X-* headers)
  GET  /lr_preview/ws        WebSocket: text JSON params -> text JSON timings + binary JPEG
  GET  /lr_preview/bench     server-side encoder micro-benchmark (?n=50)
  GET  /lr_preview/stats     server-side timing log since last reset (?reset=1)
"""
import asyncio
import io
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import torch.nn.functional as F
from aiohttp import web
from PIL import Image

from server import PromptServer

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = "cuda"
PREVIEW_MP = float(os.environ.get("LR_PREVIEW_MP", "1.5"))
_exec = ThreadPoolExecutor(max_workers=1)  # one GPU worker, keeps aiohttp loop free
_lock = threading.Lock()
_state = {}
_log = []

# ---------------------------------------------------------------- image ops


def box(x, r):
    k = 2 * r + 1
    return F.avg_pool2d(F.pad(x, (r, r, r, r), mode="reflect"), k, stride=1)


def guided(I, p, r, eps, s=1):
    if s > 1:
        Is, ps = F.interpolate(I, scale_factor=1 / s, mode="area"), F.interpolate(p, scale_factor=1 / s, mode="area")
        r = max(1, r // s)
    else:
        Is, ps = I, p
    mI, mp = box(Is, r), box(ps, r)
    a = (box(Is * ps, r) - mI * mp) / (box(Is * Is, r) - mI * mI + eps)
    b = mp - a * mI
    ma, mb = box(a, r), box(b, r)
    if s > 1:
        ma = F.interpolate(ma, size=I.shape[-2:], mode="bilinear", align_corners=False)
        mb = F.interpolate(mb, size=I.shape[-2:], mode="bilinear", align_corners=False)
    return ma * I + mb


_K2 = None


def _k2():
    global _K2
    if _K2 is None:
        g5 = torch.tensor([1, 4, 6, 4, 1], dtype=torch.float32, device=DEV) / 16
        _K2 = (g5[:, None] * g5[None, :])[None, None]
    return _K2


def down(x):
    return F.conv2d(F.pad(x, (2, 2, 2, 2), mode="replicate"), _k2())[..., ::2, ::2]


def up(x, shape):
    y = torch.zeros(x.shape[0], x.shape[1], shape[-2], shape[-1], device=x.device, dtype=x.dtype)
    y[..., ::2, ::2] = x
    return F.conv2d(F.pad(y, (2, 2, 2, 2), mode="replicate"), _k2() * 4)


def gauss_pyr(x, n):
    p = [x]
    for _ in range(n - 1):
        p.append(down(p[-1]))
    return p


def lap_pyr(x, n):
    g = gauss_pyr(x, n)
    return [g[i] - up(g[i + 1], g[i].shape) for i in range(n - 1)] + [g[-1]]


def fast_llf(I, sigma=0.2, alpha=0.5, K=8):
    """Fast local Laplacian filter (Aubry 2014), alpha<1 boosts detail (clarity)."""
    n = int(math.log2(min(I.shape[-2:]))) - 3
    G = gauss_pyr(I, n)
    refs = torch.linspace(0, 1, K, device=I.device)
    step = 1.0 / (K - 1)
    acc = [torch.zeros_like(G[l]) for l in range(n - 1)]
    for gi in range(K):
        g = refs[gi]
        d = I - g
        ad = torch.abs(d)
        r = torch.where(ad < sigma, g + torch.sign(d) * sigma * (ad / sigma).clamp(min=1e-6) ** alpha, I)
        L = lap_pyr(r, n)
        for l in range(n - 1):
            w = (1 - torch.abs(G[l] - g) / step).clamp(min=0)
            acc[l] += w * L[l]
    res = G[-1]
    for l in range(n - 2, -1, -1):
        res = up(res, acc[l].shape) + acc[l]
    return res


def curve_lut(points):
    """points: [[x,y],...] in 0..1 -> 256-entry LUT tensor (piecewise linear)."""
    pts = sorted(points)
    xs = torch.tensor([p[0] for p in pts], device=DEV)
    ys = torch.tensor([p[1] for p in pts], device=DEV)
    t = torch.linspace(0, 1, 256, device=DEV)
    idx = torch.searchsorted(xs, t).clamp(1, len(pts) - 1)
    x0, x1, y0, y1 = xs[idx - 1], xs[idx], ys[idx - 1], ys[idx]
    return (y0 + (y1 - y0) * ((t - x0) / (x1 - x0 + 1e-8)).clamp(0, 1)).clamp(0, 1)


def apply_lut(x, lut):
    f = x.clamp(0, 1) * 255
    i0 = f.floor().long().clamp(0, 254)
    w = f - i0
    return lut[i0] * (1 - w) + lut[i0 + 1] * w


def rgb2hsv(x):
    r, g, b = x[:, 0], x[:, 1], x[:, 2]
    mx, _ = x.max(1)
    mn, _ = x.min(1)
    d = mx - mn
    h = torch.zeros_like(mx)
    m = d > 1e-6
    hr = ((g - b) / (d + 1e-8)) % 6
    hg = (b - r) / (d + 1e-8) + 2
    hb = (r - g) / (d + 1e-8) + 4
    h = torch.where(mx == r, hr, torch.where(mx == g, hg, hb))
    h = torch.where(m, h / 6.0, torch.zeros_like(h))
    s = torch.where(mx > 1e-6, d / (mx + 1e-8), torch.zeros_like(mx))
    return h, s, mx


def hsv2rgb(h, s, v):
    i = (h * 6).floor()
    f = h * 6 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    i = i.long() % 6
    r = torch.stack([v, q, p, p, t, v], 1).gather(1, i[:, None])
    g = torch.stack([t, v, v, q, p, p], 1).gather(1, i[:, None])
    b = torch.stack([p, p, t, v, v, q], 1).gather(1, i[:, None])
    return torch.cat([r, g, b], 1)


def grade(img, p):
    """img: 1x3xHxW float 0..1 on GPU. Representative Lightroom-ish chain."""
    x = img * (2.0 ** float(p.get("exposure", 0.0)))
    t, tint = float(p.get("temp", 0.0)), float(p.get("tint", 0.0))
    x = x * torch.tensor([1 + 0.2 * t, 1 - 0.1 * tint, 1 - 0.2 * t], device=DEV).view(1, 3, 1, 1)
    x = x.clamp(0, 1)
    Y = (0.2126 * x[:, 0:1] + 0.7152 * x[:, 1:2] + 0.0722 * x[:, 2:3]).clamp(1e-4, 1)
    # highlights / shadows on an edge-aware base layer (guided filter, r=64 at 1/4 scale)
    base = guided(Y, Y, 64, 1e-2, s=4).clamp(0, 1)
    detail = Y - base
    sh, hl = float(p.get("shadows", 0.0)), float(p.get("highlights", 0.0))
    base = base + 0.6 * sh * (1 - base) ** 3 * base ** 0.5 + 0.6 * hl * base ** 3
    Y2 = (base + detail).clamp(0, 1)
    # clarity via fast local Laplacian on luma
    cl = float(p.get("clarity", 0.0))
    if p.get("llf", True):
        Y2 = fast_llf(Y2, sigma=0.2, alpha=max(0.25, 1.0 - 0.75 * cl)).clamp(0, 1)
    x = (x * (Y2 / Y)).clamp(0, 1)
    # tone curve
    x = apply_lut(x, curve_lut(p.get("curve", [[0, 0], [0.25, 0.22], [0.75, 0.8], [1, 1]])))
    # HSL: 8 hue bands, per-band hue shift / sat / lum
    h, s, v = rgb2hsv(x)
    hue_adj = p.get("hsl_h", [0.0] * 8)
    sat_adj = p.get("hsl_s", [0.0] * 8)
    lum_adj = p.get("hsl_l", [0.0] * 8)
    centers = torch.arange(8, device=DEV, dtype=torch.float32) / 8
    dist = torch.abs(h[..., None] - centers)
    dist = torch.minimum(dist, 1 - dist)
    w = (1 - dist * 8).clamp(min=0)  # triangular weights, sum 1
    ha = (w * torch.tensor(hue_adj, device=DEV)).sum(-1)
    sa = (w * torch.tensor(sat_adj, device=DEV)).sum(-1)
    la = (w * torch.tensor(lum_adj, device=DEV)).sum(-1)
    vib, sat = float(p.get("vibrance", 0.0)), float(p.get("saturation", 0.0))
    s = s * (1 + sa) * (1 + sat) * (1 + vib * (1 - s))
    h = (h + ha * 0.1) % 1.0
    v = v * (1 + 0.5 * la * s)
    x = hsv2rgb(h, s.clamp(0, 1), v.clamp(0, 1))
    return (x.clamp(0, 1) * 255 + 0.5).to(torch.uint8)[0]  # 3xHxW uint8 on GPU


# ---------------------------------------------------------------- encoders


def enc_gpu(u8, q):
    from torchvision.io import encode_jpeg
    out = encode_jpeg(u8, quality=q)  # CUDA tensor in -> nvjpeg
    return out.cpu().numpy().tobytes()


def enc_pil(u8, q):
    a = u8.permute(1, 2, 0).contiguous().cpu().numpy()
    b = io.BytesIO()
    Image.fromarray(a).save(b, format="JPEG", quality=q)
    return b.getvalue()


def enc_cv2(u8, q):
    import cv2
    a = u8.flip(0).permute(1, 2, 0).contiguous().cpu().numpy()  # RGB->BGR
    ok, buf = cv2.imencode(".jpg", a, [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes()


def enc_tvcpu(u8, q):
    from torchvision.io import encode_jpeg
    return encode_jpeg(u8.cpu(), quality=q).numpy().tobytes()


ENCODERS = {"gpu": enc_gpu, "pil": enc_pil, "cv2": enc_cv2, "tvcpu": enc_tvcpu}

# ---------------------------------------------------------------- state


def ensure_loaded(mp=None):
    mp = mp or PREVIEW_MP
    if _state.get("mp") == mp:
        return
    src = os.environ.get("LR_PREVIEW_IMG") or os.path.join(HERE, "test.png")
    if not os.path.exists(src):  # a natural photo that ships with an installed node pack
        src = os.path.join(HERE, "..", "ComfyUI-AusBoss", "example_workflows", "inputs", "ausboss_pier_sunrise.png")
    im = np.asarray(Image.open(src).convert("RGB"))
    t = torch.from_numpy(im).to(DEV).permute(2, 0, 1)[None].float() / 255
    H, W = t.shape[-2:]
    s24 = math.sqrt(24e6 / (H * W))
    full = F.interpolate(t, size=(round(H * s24), round(W * s24)), mode="bicubic", align_corners=False).clamp(0, 1)
    sp = math.sqrt(mp * 1e6 / (full.shape[-2] * full.shape[-1]))
    prev = F.interpolate(full, size=(round(full.shape[-2] * sp), round(full.shape[-1] * sp)), mode="area")
    _state.update(full_shape=list(full.shape[-2:]), img=prev.contiguous(), mp=mp)
    del full
    torch.cuda.empty_cache()
    # warm up every path
    u8 = grade(_state["img"], {})
    for e in ENCODERS.values():
        e(u8, 85)
    torch.cuda.synchronize()


_streams = {}


def _stream(kind):
    """'default' = legacy default stream + device-wide sync (waits for ComfyUI's own kernels too);
    'hi' / 'lo' = own stream (high / low priority), synchronizing only that stream."""
    if kind not in _streams:
        _streams[kind] = torch.cuda.Stream(priority=-1 if kind == "hi" else 0)
    return _streams[kind]


def render(params):
    with _lock:
        ensure_loaded(params.get("mp"))
        kind = params.get("stream", "default")
        if kind == "default":
            t0 = time.perf_counter()
            torch.cuda.synchronize()
            tq = time.perf_counter()
            u8 = grade(_state["img"], params)
            torch.cuda.synchronize()
            t1 = time.perf_counter()
            data = ENCODERS[params.get("enc", "gpu")](u8, int(params.get("q", 85)))
            t2 = time.perf_counter()
        else:
            s = _stream(kind)
            with torch.cuda.stream(s):
                t0 = tq = time.perf_counter()
                u8 = grade(_state["img"], params)
                s.synchronize()
                t1 = time.perf_counter()
                data = ENCODERS[params.get("enc", "gpu")](u8, int(params.get("q", 85)))
                s.synchronize()
                t2 = time.perf_counter()
        rec = dict(seq=params.get("seq"), compute_ms=(t1 - tq) * 1000, encode_ms=(t2 - t1) * 1000,
                   bytes=len(data), w=int(u8.shape[-1]), h=int(u8.shape[-2]), enc=params.get("enc", "gpu"),
                   wait_ms=(tq - t0) * 1000)
        _log.append(rec)
        return data, rec


# ---------------------------------------------------------------- routes
routes = PromptServer.instance.routes


@routes.get("/lr_preview/page")
async def page(request):
    with open(os.path.join(HERE, "page.html"), encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")


@routes.post("/lr_preview")
async def preview(request):
    t_in = time.perf_counter()
    params = await request.json()
    loop = asyncio.get_running_loop()
    data, rec = await loop.run_in_executor(_exec, render, params)
    rec["server_ms"] = (time.perf_counter() - t_in) * 1000
    return web.Response(body=data, content_type="image/jpeg", headers={
        "X-Timing": json.dumps(rec), "Cache-Control": "no-store",
        "Access-Control-Expose-Headers": "X-Timing"})


@routes.get("/lr_preview/ws")
async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    loop = asyncio.get_running_loop()
    async for msg in ws:
        if msg.type != web.WSMsgType.TEXT:
            continue
        t_in = time.perf_counter()
        params = json.loads(msg.data)
        data, rec = await loop.run_in_executor(_exec, render, params)
        rec["server_ms"] = (time.perf_counter() - t_in) * 1000
        await ws.send_str(json.dumps(rec))
        await ws.send_bytes(data)
    return ws


def _bench(n, mp):
    with _lock:
        ensure_loaded(mp)
        out = {"preview_hw": list(_state["img"].shape[-2:]), "full_hw": _state["full_shape"]}
        for name, p in [("grade_all", {"clarity": 0.5, "shadows": 0.3, "highlights": -0.3}),
                        ("grade_no_llf", {"llf": False})]:
            ts = []
            for _ in range(n):
                torch.cuda.synchronize(); t = time.perf_counter()
                u8 = grade(_state["img"], p)
                torch.cuda.synchronize(); ts.append((time.perf_counter() - t) * 1000)
            out[name] = _pct(ts)
        for name, e in ENCODERS.items():
            ts = []
            for _ in range(n):
                t = time.perf_counter(); b = e(u8, 85); ts.append((time.perf_counter() - t) * 1000)
            out["enc_" + name] = _pct(ts) | {"bytes": len(b)}
        out["vram_alloc_gib"] = torch.cuda.memory_allocated() / 2**30
        return out


def _pct(ts):
    a = np.array(ts)
    return {"p50": round(float(np.percentile(a, 50)), 2), "p95": round(float(np.percentile(a, 95)), 2),
            "min": round(float(a.min()), 2)}


@routes.get("/lr_preview/bench")
async def bench(request):
    n = int(request.query.get("n", "50"))
    mp = float(request.query.get("mp", PREVIEW_MP))
    loop = asyncio.get_running_loop()
    return web.json_response(await loop.run_in_executor(_exec, _bench, n, mp))


@routes.get("/lr_preview/stats")
async def stats(request):
    out = list(_log)
    if request.query.get("reset"):
        _log.clear()
    return web.json_response(out)
