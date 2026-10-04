"""GPU rendering of Params onto an sRGB image (torch, float32).

Pipeline (each stage is skipped when its settings sit at the default, so strength 0 is an exact identity):
  sRGB -> linear light: white balance (incremental), calibration, shadow tint, exposure (+shoulder), dehaze
  -> sRGB-encoded luma: highlights/shadows (guided-filter base layer), contrast, whites/blacks end-point
     curves, clarity (fast local Laplacian), texture (pyramid mid-band) -> local gradient corrections
  -> parametric + point tone curves -> vibrance/saturation, HSL, colour grading (each tone once)
  -> grayscale -> vignette, grain, sharpening.
Method choices follow research/03-proprietary-approximations.md; the numeric mappings are uncalibrated
first guesses (P3: closeness to Lightroom is left to the calibration set).
"""
import math

import numpy as np
import torch
import torch.nn.functional as F

from . import _color
from ._params import Params

HSL_COLORS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
HSL_CENTERS = (0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0)  # degrees


def pick_device(device=None):
    if device is not None:
        return torch.device(device)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# --------------------------------------------------------------------------- small image ops


def _box(x, r):
    return F.avg_pool2d(F.pad(x, (r, r, r, r), mode="replicate"), 2 * r + 1, stride=1)


def _guided(I, p, r, eps, s=1):
    """Fast guided filter (He et al.); I guide, p input, r radius at full resolution, s subsampling."""
    if s > 1 and min(I.shape[-2:]) >= 4 * s:
        Is = F.interpolate(I, scale_factor=1 / s, mode="area")
        ps = Is if p is I else F.interpolate(p, scale_factor=1 / s, mode="area")
        r = max(1, r // s)
    else:
        Is, ps, s = I, p, 1
    r = max(1, min(r, (min(Is.shape[-2:]) - 1) // 2))
    mI, mp = _box(Is, r), _box(ps, r)
    a = (_box(Is * ps, r) - mI * mp) / (_box(Is * Is, r) - mI * mI + eps)
    b = mp - a * mI
    ma, mb = _box(a, r), _box(b, r)
    if s > 1:
        ma = F.interpolate(ma, size=I.shape[-2:], mode="bilinear", align_corners=False)
        mb = F.interpolate(mb, size=I.shape[-2:], mode="bilinear", align_corners=False)
    return ma * I + mb


def _gauss1d(sigma, device):
    r = max(1, int(math.ceil(sigma * 3)))
    t = torch.arange(-r, r + 1, dtype=torch.float32, device=device)
    k = torch.exp(-t * t / (2 * sigma * sigma))
    return k / k.sum(), r


def _blur(x, sigma):
    k, r = _gauss1d(sigma, x.device)
    c = x.shape[1]
    x = F.conv2d(F.pad(x, (r, r, 0, 0), mode="replicate"), k.view(1, 1, 1, -1).expand(c, 1, 1, -1), groups=c)
    return F.conv2d(F.pad(x, (0, 0, r, r), mode="replicate"), k.view(1, 1, -1, 1).expand(c, 1, -1, 1), groups=c)


_G5 = None


def _down(x):
    global _G5
    if _G5 is None or _G5.device != x.device:
        g = torch.tensor([1, 4, 6, 4, 1], dtype=torch.float32, device=x.device) / 16
        _G5 = (g[:, None] * g[None, :])[None, None]
    c = x.shape[1]
    return F.conv2d(F.pad(x, (2, 2, 2, 2), mode="replicate"), _G5.expand(c, 1, 5, 5), stride=2, groups=c)


def _up(x, shape):
    return F.interpolate(x, size=tuple(shape[-2:]), mode="bilinear", align_corners=False)


def _levels(h, w):
    return max(2, int(math.log2(max(2, min(h, w)))) - 3)


def _fast_llf(I, alpha, sigma=0.2, K=8):
    """Fast local Laplacian filter (Aubry et al. 2014) on a 1x1xHxW image in 0..1; alpha<1 boosts detail."""
    n = _levels(*I.shape[-2:])
    G = [I]
    for _ in range(n - 1):
        G.append(_down(G[-1]))
    refs = torch.linspace(0, 1, K, device=I.device, dtype=I.dtype)
    step = 1.0 / (K - 1)
    acc = [torch.zeros_like(G[l]) for l in range(n - 1)]
    chunk = K if I.numel() <= 4_000_000 else max(1, int(16_000_000 // I.numel()))
    for c0 in range(0, K, chunk):
        g = refs[c0:c0 + chunk].view(-1, 1, 1, 1)
        d = I - g                                                   # (k,1,H,W)
        ad = d.abs()
        r = torch.where(ad < sigma, g + torch.sign(d) * sigma * (ad / sigma).clamp(min=1e-6) ** alpha, I.expand_as(d))
        cur = r
        for l in range(n - 1):
            nxt = _down(cur)
            lap = cur - _up(nxt, cur.shape)
            w = (1 - (G[l] - g).abs() / step).clamp(min=0)          # (k,1,h,w)
            acc[l] += (w * lap).sum(0, keepdim=True)
            cur = nxt
    res = G[-1]
    for l in range(n - 2, -1, -1):
        res = _up(res, acc[l].shape) + acc[l]
    return res


def _smoothstep(a, b, x):
    t = ((x - a) / (b - a)).clamp(0, 1)
    return t * t * (3 - 2 * t)


def _rgb2hsv(x):
    r, g, b = x[:, 0:1], x[:, 1:2], x[:, 2:3]
    mx = torch.maximum(torch.maximum(r, g), b)
    mn = torch.minimum(torch.minimum(r, g), b)
    d = mx - mn
    dd = d + 1e-8
    h = torch.where(mx == r, ((g - b) / dd) % 6, torch.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) / 6.0
    h = torch.where(d > 1e-6, h, torch.zeros_like(h))
    s = torch.where(mx > 1e-6, d / (mx + 1e-8), torch.zeros_like(mx))
    return h, s, mx


def _hsv2rgb(h, s, v):
    h6 = (h % 1.0) * 6
    k = lambda n: (n + h6) % 6
    f = lambda n: v - v * s * (torch.minimum(k(n), 4 - k(n)).clamp(0, 1))
    return torch.cat([f(5), f(3), f(1)], 1)


def _hue_interp(h, values):
    """Periodic piecewise-linear interpolation of 8 per-band values (Lightroom HSL centres) at hue h in 0..1."""
    deg = (h * 360.0) % 360.0
    c = torch.tensor(HSL_CENTERS + (360.0,), device=h.device, dtype=h.dtype)
    v = torch.tensor(list(values) + [values[0]], device=h.device, dtype=h.dtype)
    i = torch.bucketize(deg, c[1:-1], right=True)                   # 0..7
    c0, c1, v0, v1 = c[i], c[i + 1], v[i], v[i + 1]
    t = (deg - c0) / (c1 - c0)
    return v0 + (v1 - v0) * t


def _hue_rgb(hue_deg, device):
    h = torch.tensor([[[[hue_deg / 360.0]]]], device=device)
    return _hsv2rgb(h, torch.ones_like(h), torch.ones_like(h))      # 1x3x1x1


# --------------------------------------------------------------------------- linear-light stage


def _calibration_matrix(g):
    hue = [g("RedHue") / 100, g("GreenHue") / 100, g("BlueHue") / 100]
    sat = [g("RedSaturation") / 100, g("GreenSaturation") / 100, g("BlueSaturation") / 100]
    if not any(hue) and not any(sat):
        return None
    M = np.eye(3)
    plus, minus = (1, 2, 0), (2, 0, 1)   # R: + toward yellow/green, - toward magenta; G: + cyan; B: + purple
    w = np.array([0.2126, 0.7152, 0.0722])
    for i in range(3):
        col = M[:, i].copy()
        col[plus[i] if hue[i] > 0 else minus[i]] += 0.25 * abs(hue[i])
        grey = float(w @ col)
        col = grey + (1 + 0.5 * sat[i]) * (col - grey)
        M[:, i] = col
    M = M / M.sum(1, keepdims=True)       # rows sum to 1: neutrals stay neutral
    return M


def _linear_stage(lin, g):
    T, Ti = g("IncrementalTemperature") / 100, g("IncrementalTint") / 100
    if T or Ti:
        gains = torch.tensor([2 ** (0.45 * T), 2 ** (-0.30 * Ti), 2 ** (-0.55 * T)], device=lin.device)
        gains = gains / (0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2])
        lin = lin * gains.view(1, 3, 1, 1)
    M = _calibration_matrix(g)
    if M is not None:
        lin = torch.einsum("ij,bjhw->bihw", torch.tensor(M, dtype=lin.dtype, device=lin.device), lin)
    st = g("ShadowTint") / 100
    if st:
        w = (1 - _color.luma(lin).clamp(0, 1)) ** 3
        lin = torch.cat([lin[:, 0:1], lin[:, 1:2] * torch.exp2(-0.25 * st * w), lin[:, 2:3]], 1)
    ev = g("Exposure2012")
    if ev:
        lin = lin * (2.0 ** ev)
        if ev > 0:  # smooth shoulder on the largest channel (keeps hue), PV2012-like highlight roll-off
            m = lin.amax(1, keepdim=True)
            k = 0.8
            m2 = torch.where(m > k, k + (1 - k) * torch.tanh((m - k) / (1 - k)), m)
            lin = lin * (m2 / m.clamp(min=1e-8))
    dz = g("Dehaze") / 100
    if dz:
        lin = _dehaze(lin.clamp(0, 1), dz)
    return lin.clamp(0, 1)


def _dehaze(lin, amount):
    """Dark channel prior + guided-filter refined transmission, in linear light."""
    H, W = lin.shape[-2:]
    L = max(H, W)
    w = max(3, int(L * 0.01)) | 1
    pool = lambda t: -F.max_pool2d(-t, w, stride=1, padding=w // 2)
    dark = pool(lin.amin(1, keepdim=True))
    flat = dark.flatten()
    k = max(1, flat.numel() // 1000)
    thr = torch.topk(flat, k).values[-1]
    sel = (dark >= thr).to(lin.dtype)
    A = ((lin * sel).sum((2, 3), keepdim=True) / sel.sum().clamp(min=1)).clamp(min=0.05, max=1.0)
    omega = 0.9 * abs(amount)
    t = 1 - omega * pool((lin / A).amin(1, keepdim=True))
    guide = _color.luma(lin).clamp(0, 1) ** (1 / 2.2)
    t = _guided(guide, t, max(8, int(L * 0.04)), 1e-3, s=4).clamp(0.15, 1)
    if amount > 0:
        per = (lin - A) / t + A
        yl = _color.luma(lin).clamp(min=1e-4)
        yA = _color.luma(A)
        lum = lin * (((yl - yA) / t + yA).clamp(min=0) / yl)
        return (0.5 * per + 0.5 * lum).clamp(0, 1)
    return (lin * t + A * (1 - t)).clamp(0, 1)


# --------------------------------------------------------------------------- tone on luma

TONE_KEYS = ("Highlights2012", "Shadows2012", "Contrast2012", "Whites2012", "Blacks2012", "Clarity2012", "Texture")


def _tone(x, g):
    if not any(g(k) for k in TONE_KEYS):
        return x
    H, W = x.shape[-2:]
    L = max(H, W)
    Y = _color.luma(x).clamp(1e-4, 1)
    Y2 = Y
    hl, sh = g("Highlights2012") / 100, g("Shadows2012") / 100
    if hl or sh:
        base = _guided(Y, Y, max(8, L // 24), 1e-2, s=4).clamp(0, 1)
        detail = Y - base
        base = base + 0.30 * hl * _smoothstep(0.45, 1.0, base) * base \
                    + 0.35 * sh * (1 - _smoothstep(0.0, 0.55, base)) * (1 - base) * base.clamp(min=1e-4) ** 0.35
        Y2 = (base + detail).clamp(0, 1)
    c = g("Contrast2012") / 100
    if c:
        Y2 = Y2 + c * (0.9 if c > 0 else 0.8) * Y2 * (1 - Y2) * (2 * Y2 - 1)
    wh = g("Whites2012") / 100
    if wh:
        Y2 = Y2 + 0.18 * wh * Y2 ** 4
    bl = g("Blacks2012") / 100
    if bl:  # Lightroom: positive lifts the darkest tones (matte), negative crushes them
        Y2 = Y2 + (0.12 if bl > 0 else 0.10) * bl * (1 - Y2).clamp(0, 1) ** 4
    Y2 = Y2.clamp(0, 1)
    cl = g("Clarity2012") / 100
    if cl:
        alpha = 1 - 0.6 * cl if cl > 0 else 1 + 0.8 * abs(cl)
        Yl = _fast_llf(Y2, alpha)
        wmid = (4 * Y2 * (1 - Y2)).clamp(0, 1) ** 0.7
        Y2 = (Y2 + wmid * (Yl - Y2)).clamp(0, 1)
    tx = g("Texture") / 100
    if tx:
        Y2 = _texture(Y2, tx)
    ratio = (Y2 / Y).clamp(max=2.0)
    return (x * ratio + (Y2 - Y * ratio)).clamp(0, 1)


def _texture(Y, t):
    """Mid-frequency pyramid bands (about 2..8 px at preview size) with soft coring so noise is left alone."""
    big = max(Y.shape[-2:]) > 2500
    n = 5 if big else 4
    G = [Y]
    for _ in range(n - 1):
        G.append(_down(G[-1]))
    lap = [G[i] - _up(G[i + 1], G[i].shape) for i in range(n - 1)]
    gain = 1 + 1.0 * t if t > 0 else 1 - 0.8 * abs(t)
    for l in ((2, 3) if big else (1, 2)):
        d = lap[l]
        noise = d.abs().mean() * 1.2533
        core = torch.sign(d) * (d.abs() - noise).clamp(min=0)
        lap[l] = d + (gain - 1) * core
    res = G[-1]
    for l in range(n - 2, -1, -1):
        res = _up(res, lap[l].shape) + lap[l]
    return res.clamp(0, 1)


# --------------------------------------------------------------------------- local corrections


def _pixel_grid(H, W, device):
    ys = (torch.arange(H, device=device, dtype=torch.float32) + 0.5).view(1, 1, H, 1)
    xs = (torch.arange(W, device=device, dtype=torch.float32) + 0.5).view(1, 1, 1, W)
    return xs, ys


def _shape_mask(s, H, W, device):
    xs, ys = _pixel_grid(H, W, device)
    if s["type"] == "Mask/Gradient":
        zx, zy, fx, fy = s["ZeroX"] * W, s["ZeroY"] * H, s["FullX"] * W, s["FullY"] * H
        dx, dy = fx - zx, fy - zy
        n2 = dx * dx + dy * dy
        if n2 < 1e-9:
            return torch.zeros(1, 1, H, W, device=device)
        m = (((xs - zx) * dx + (ys - zy) * dy) / n2).clamp(0, 1)
    else:  # Mask/CircularGradient: ellipse in the Left/Top/Right/Bottom box, rotated by Angle
        cx, cy = (s["Left"] + s["Right"]) / 2 * W, (s["Top"] + s["Bottom"]) / 2 * H
        a, b = abs(s["Right"] - s["Left"]) / 2 * W, abs(s["Bottom"] - s["Top"]) / 2 * H
        if a < 1e-6 or b < 1e-6:
            return torch.zeros(1, 1, H, W, device=device)
        th = math.radians(s["Angle"])
        u = (xs - cx) * math.cos(th) + (ys - cy) * math.sin(th)
        v = -(xs - cx) * math.sin(th) + (ys - cy) * math.cos(th)
        d = torch.sqrt((u / a) ** 2 + (v / b) ** 2)
        inner = 1 - min(max(s["Feather"], 0.0), 100.0) / 100
        inside = torch.where(d <= inner, torch.ones_like(d), 1 - _smoothstep(inner, 1.0, d)) if inner < 1 \
            else (d <= 1).to(d.dtype)
        inside = torch.where(d >= 1, torch.zeros_like(d), inside)
        m = inside if s["Flipped"] else 1 - inside   # Flipped=true: effect inside the ellipse
    if s["inverted"]:
        m = 1 - m
    return m * s["opacity"]


_LOCAL_MAP = (("LocalExposure2012", "Exposure2012", 4.0), ("LocalContrast2012", "Contrast2012", 100.0),
              ("LocalHighlights2012", "Highlights2012", 100.0), ("LocalShadows2012", "Shadows2012", 100.0),
              ("LocalWhites2012", "Whites2012", 100.0), ("LocalBlacks2012", "Blacks2012", 100.0),
              ("LocalClarity2012", "Clarity2012", 100.0), ("LocalTexture", "Texture", 100.0),
              ("LocalDehaze", "Dehaze", 100.0), ("LocalTemperature", "IncrementalTemperature", 100.0),
              ("LocalTint", "IncrementalTint", 100.0), ("LocalSaturation", "Saturation", 100.0))


def _local(x, masks):
    H, W = x.shape[-2:]
    for m in masks:
        lv = {gk: m["values"].get(lk, 0.0) * sc for lk, gk, sc in _LOCAL_MAP}
        if not any(lv.values()) or not m["shapes"] or not m.get("amount", 1.0):
            continue
        M = None
        for s in m["shapes"]:
            sm = _shape_mask(s, H, W, x.device)
            M = sm if M is None else torch.maximum(M, sm)
        M = (M * m.get("amount", 1.0)).clamp(0, 1)
        g = lambda k: lv.get(k, 0.0)
        adj = x
        if any(g(k) for k in ("IncrementalTemperature", "IncrementalTint", "Exposure2012", "Dehaze")):
            adj = _color.linear_to_srgb(_linear_stage(_color.srgb_to_linear(adj), g))
        adj = _tone(adj, g)
        if g("Saturation"):
            Y = _color.luma(adj)
            adj = (Y + (1 + g("Saturation") / 100) * (adj - Y)).clamp(0, 1)
        x = x + M * (adj - x)
    return x


# --------------------------------------------------------------------------- curves


def _pchip(px, py, xs):
    """Monotone cubic (Fritsch-Carlson) through points (px ascending), evaluated at xs; numpy float64."""
    px, py = np.asarray(px, float), np.asarray(py, float)
    keep = np.concatenate([[True], np.diff(px) > 1e-9])
    px, py = px[keep], py[keep]
    if len(px) == 1:
        return np.full_like(xs, py[0])
    h = np.diff(px)
    dlt = np.diff(py) / h
    m = np.zeros_like(py)
    if len(px) == 2:
        m[:] = dlt[0]
    else:
        for i in range(1, len(px) - 1):
            if dlt[i - 1] * dlt[i] <= 0:
                m[i] = 0.0
            else:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                m[i] = (w1 + w2) / (w1 / dlt[i - 1] + w2 / dlt[i])
        m[0], m[-1] = dlt[0], dlt[-1]
    i = np.clip(np.searchsorted(px, xs, side="right") - 1, 0, len(px) - 2)
    t = (xs - px[i]) / h[i]
    t = np.clip(t, 0, 1)
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    y = h00 * py[i] + h10 * h[i] * m[i] + h01 * py[i + 1] + h11 * h[i] * m[i + 1]
    y = np.where(xs < px[0], py[0], np.where(xs > px[-1], py[-1], y))
    return y


def _parametric(g, xs):
    amts = [g("ParametricShadows"), g("ParametricDarks"), g("ParametricLights"), g("ParametricHighlights")]
    if not any(amts):
        return xs
    s1, s2, s3 = sorted([g("ParametricShadowSplit") / 100, g("ParametricMidtoneSplit") / 100,
                         g("ParametricHighlightSplit") / 100])
    c = [s1 / 2, (s1 + s2) / 2, (s2 + s3) / 2, (s3 + 1) / 2]
    spans = [(0.0, c[0], c[1]), (c[0], c[1], c[2]), (c[1], c[2], c[3]), (c[2], c[3], 1.0)]
    y = xs.copy()
    for a, (lo, mid, hi) in zip(amts, spans):
        if not a:
            continue
        b = np.where(xs < mid, (xs - lo) / max(mid - lo, 1e-6), (hi - xs) / max(hi - mid, 1e-6))
        b = np.clip(b, 0, 1)
        y += 0.15 * a / 100 * np.sin(b * np.pi / 2) ** 2
    y = np.maximum.accumulate(np.clip(y, 0, 1))
    return y


def _is_identity(pts):
    return all(abs(x - y) < 1e-9 for x, y in pts)


def _curve_luts(p, N=1024):
    g = p.get
    xs = np.linspace(0, 1, N)
    has_par = any(g(k) for k in ("ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights"))
    active = {k: v for k, v in p.curves.items() if not _is_identity(v)}
    if not has_par and not active:
        return None
    base = _parametric(g, xs)
    master = active.get("ToneCurvePV2012")
    if master:
        base = np.clip(_pchip([a / 255 for a, _ in master], [b / 255 for _, b in master], base), 0, 1)
    luts = []
    for ch in ("Red", "Green", "Blue"):
        c = active.get("ToneCurvePV2012" + ch)
        luts.append(np.clip(_pchip([a / 255 for a, _ in c], [b / 255 for _, b in c], base), 0, 1) if c else base)
    return np.stack(luts).astype(np.float32)


def _apply_luts(x, luts):
    N = luts.shape[1]
    lut = torch.from_numpy(luts).to(x.device).flatten()
    f = x.clamp(0, 1) * (N - 1)
    i0 = f.floor().clamp(0, N - 2)
    w = f - i0
    off = (torch.arange(3, device=x.device) * N).view(1, 3, 1, 1)
    i0 = i0.long() + off
    return lut[i0] * (1 - w) + lut[i0 + 1] * w


# --------------------------------------------------------------------------- colour


def _zone_weights(Y, g):
    c = 0.5 - 0.2 * (g("SplitToningBalance") / 100)        # balance > 0 favours highlights
    bw = 0.1 + 0.4 * (g("ColorGradeBlending") / 100)
    w_s = 1 - _smoothstep(c - bw, c + bw, Y)
    w_h = _smoothstep(c - bw, c + bw, Y)
    w_m = (1 - ((Y - c) / 0.5) ** 2).clamp(0, 1)
    return {"shadow": w_s, "midtone": w_m, "highlight": w_h, "global": None}


# Which keys drive each colour-grading zone. Shadow/highlight tones live only in SplitToning*
# (Lightroom writes its Color Grading shadow/highlight wheels there), so each tone is applied once.
TINT_ZONES = (("shadow", "SplitToningShadowHue", "SplitToningShadowSaturation", "ColorGradeShadowLum"),
              ("highlight", "SplitToningHighlightHue", "SplitToningHighlightSaturation", "ColorGradeHighlightLum"),
              ("midtone", "ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeMidtoneLum"),
              ("global", "ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum"))


def _apply_tint(x, Y, zone, hue, sat, weight):
    rgb = _hue_rgb(hue, x.device)
    chroma = rgb - _color.luma(rgb)
    amt = 0.35 * sat / 100
    return x + (chroma * amt if weight is None else weight * chroma * amt)


def _color_grade(x, g):
    zones = [(z, g(hk), g(sk), g(lk)) for z, hk, sk, lk in TINT_ZONES]
    if not any(s or l for _, _, s, l in zones):
        return x
    Y = _color.luma(x).clamp(0, 1)
    w = _zone_weights(Y, g)
    for zone, hue, sat, lum in zones:
        if sat:
            x = _apply_tint(x, Y, zone, hue, sat, w[zone])
        if lum:
            d = 0.2 * lum / 100
            x = x + (d if w[zone] is None else w[zone] * d)
    return x.clamp(0, 1)


def _color_ops(x, g):
    vib, sat = g("Vibrance") / 100, g("Saturation") / 100
    if vib or sat:
        Y = _color.luma(x)
        lvl = (x.amax(1, keepdim=True) - x.amin(1, keepdim=True)).clamp(0, 1)
        f = (1 + sat) * (1 + vib * (1 - lvl))
        x = (Y + f * (x - Y)).clamp(0, 1)
    ha = [g(f"HueAdjustment{c}") / 100 for c in HSL_COLORS]
    sa = [g(f"SaturationAdjustment{c}") / 100 for c in HSL_COLORS]
    la = [g(f"LuminanceAdjustment{c}") / 100 for c in HSL_COLORS]
    if any(ha) or any(sa) or any(la):
        h, s, v = _rgb2hsv(x)
        if any(ha):
            h = (h + _hue_interp(h, ha) * (30.0 / 360.0)) % 1.0
        if any(sa):
            s = (s * (1 + _hue_interp(h, sa))).clamp(0, 1)
        if any(la):
            v = (v * (1 + 0.35 * _hue_interp(h, la) * s)).clamp(0, 1)
        x = _hsv2rgb(h, s, v)
    return _color_grade(x, g)


def _grayscale(x, g):
    Y = _color.luma(x)
    mix = [g(f"GrayMixer{c}") / 100 for c in HSL_COLORS]
    if any(mix):
        h, s, _ = _rgb2hsv(x)
        Y = Y * (1 + 0.6 * _hue_interp(h, mix) * s)
    return Y.clamp(0, 1).repeat(1, 3, 1, 1)


# --------------------------------------------------------------------------- effects


def _vignette(x, g):
    a = g("PostCropVignetteAmount") / 100
    if not a:
        return x
    H, W = x.shape[-2:]
    xs, ys = _pixel_grid(H, W, x.device)
    u, v = (xs / W - 0.5) * 2, (ys / H - 0.5) * 2
    r = g("PostCropVignetteRoundness") / 100
    if r > 0:   # toward a circle
        Lm = max(H, W)
        u, v = u * (W / Lm) ** r, v * (H / Lm) ** r
    d = torch.sqrt(u * u + v * v)
    mid, fe = g("PostCropVignetteMidpoint") / 100, g("PostCropVignetteFeather") / 100
    d0, fw = 0.4 + 0.8 * mid, 0.05 + 0.6 * fe
    t = _smoothstep(d0 - fw, d0 + fw, d)
    if a < 0:
        return x * (1 + 0.9 * a * t)
    return x + (1 - x) * (0.9 * a * t)


_NOISE = {}


def _grain_noise(H, W, sigma, device):
    key = (H, W, round(sigma, 4), str(device))
    n = _NOISE.get(key)
    if n is None:
        gen = torch.Generator().manual_seed(20261004)
        n = torch.randn(1, 1, H, W, generator=gen).to(device)
        n = _blur(n, sigma)
        n = n / n.std().clamp(min=1e-6)
        if len(_NOISE) > 8:
            _NOISE.clear()
        _NOISE[key] = n
    return n


def _grain(x, g):
    a = g("GrainAmount") / 100
    if not a:
        return x
    H, W = x.shape[-2:]
    sigma = (0.3 + 1.5 * g("GrainSize") / 100) * max(1.0, max(H, W) / 2000)
    n = _grain_noise(H, W, sigma, x.device)
    Y = _color.luma(x).clamp(0, 1)
    wt = 0.3 + 0.7 * (4 * Y * (1 - Y))
    return x + 0.12 * a * wt * n


def _sharpen(x, g):
    a = g("Sharpness") / 150
    if not a:
        return x
    Y = _color.luma(x)
    return x + a * (Y - _blur(Y, max(0.3, g("SharpenRadius"))))


# --------------------------------------------------------------------------- driver


def _pipeline(x, p):
    g = p.get
    x = x.clamp(0, 1)
    if any(g(k) for k in ("IncrementalTemperature", "IncrementalTint", "Exposure2012", "Dehaze", "ShadowTint",
                          "RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation")):
        x = _color.linear_to_srgb(_linear_stage(_color.srgb_to_linear(x), g))
    x = _tone(x, g)
    if p.masks:
        x = _local(x, p.masks)
    luts = _curve_luts(p)
    if luts is not None:
        x = _apply_luts(x, luts)
    x = _color_ops(x, g)
    if g("ConvertToGrayscale"):
        x = _grayscale(x, g)
    x = _vignette(x, g)
    x = _grain(x, g)
    x = _sharpen(x, g)
    return x.clamp(0, 1)


def _to_tensor(image, device):
    if isinstance(image, torch.Tensor):
        t = image
        dev = pick_device(device) if device is not None else t.device
        squeeze = t.dim() == 3
        if squeeze:
            t = t.unsqueeze(0)
        if t.dim() != 4 or t.shape[1] != 3:
            raise ValueError(f"expected a 3xHxW or 1x3xHxW tensor, got {tuple(image.shape)}")
        src_dev, src_dtype = image.device, image.dtype
        t = t.to(dev, torch.float32)

        def restore(out):
            out = out.to(src_dev, src_dtype if src_dtype.is_floating_point else torch.float32)
            return out[0] if squeeze else out
        return t, restore
    a = np.asarray(image)
    if a.ndim != 3 or a.shape[2] != 3:
        raise ValueError(f"expected an HxWx3 array, got {a.shape}")
    if a.dtype == np.uint8:
        a = a.astype(np.float32) / 255
    elif a.dtype == np.uint16:
        a = a.astype(np.float32) / 65535
    t = torch.from_numpy(np.ascontiguousarray(a, dtype=np.float32)).permute(2, 0, 1)[None].to(pick_device(device))

    def restore(out):
        return out[0].permute(1, 2, 0).contiguous().cpu().numpy()
    return t, restore


@torch.no_grad()
def render(image, params, strength=1.0, device=None):
    """Apply `params` at `strength` (0..2) to an sRGB image with values in 0..1.

    image: HxWx3 numpy array (float 0..1, or uint8/uint16) -> HxWx3 float32 array; or a 3xHxW / 1x3xHxW
    torch tensor -> tensor of the same shape on the same device. device: None = the tensor's device, or
    CUDA when available (CPU otherwise) for arrays.
    """
    if not isinstance(params, Params):
        raise TypeError("params must be a darkroom.Params")
    p = params.at_strength(strength)
    x, restore = _to_tensor(image, device)
    return restore(_pipeline(x, p))
