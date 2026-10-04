"""Rough program-side approximation of Lightroom basic + HSL sliders (prototype, NOT the final engine).

apply(rgb_uint8, adj) -> rgb_uint8, adj uses Lightroom xmp keys (Exposure2012, Contrast2012, ...).
Order: WB + exposure in linear light -> tone (highlights/shadows on a guided-filter base layer,
contrast S-curve, whites/blacks end-point curves) -> dehaze (simplified) -> clarity (large-radius
local contrast, midtone weighted) -> texture (small-radius detail) -> vibrance/saturation -> HSL.
None of the strengths are calibrated against Adobe; they only make the direction and rough size visible.
Runs on CPU (torch) so it can be used while the GPU is busy. Set RENDER_DEV=cuda to use the GPU.
"""
import os

import numpy as np
import torch
import torch.nn.functional as F

DEV = os.environ.get("RENDER_DEV", "cpu")


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


def blur(x, sigma):
    r = max(1, int(sigma * 2.5))
    t = torch.arange(-r, r + 1, dtype=x.dtype, device=x.device)
    k = torch.exp(-t ** 2 / (2 * sigma ** 2))
    k = k / k.sum()
    x = F.conv2d(F.pad(x, (r, r, 0, 0), mode="reflect"), k.view(1, 1, 1, -1))
    return F.conv2d(F.pad(x, (0, 0, r, r), mode="reflect"), k.view(1, 1, -1, 1))


def s2l(x):
    return torch.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def l2s(x):
    x = x.clamp(0, 1)
    return torch.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def luma(x):
    return (0.2126 * x[:, 0:1] + 0.7152 * x[:, 1:2] + 0.0722 * x[:, 2:3])


def smoothstep(a, b, x):
    t = ((x - a) / (b - a)).clamp(0, 1)
    return t * t * (3 - 2 * t)


def rgb2hsv(x):
    r, g, b = x[:, 0], x[:, 1], x[:, 2]
    mx, _ = x.max(1)
    mn, _ = x.min(1)
    d = mx - mn
    hr = ((g - b) / (d + 1e-8)) % 6
    hg = (b - r) / (d + 1e-8) + 2
    hb = (r - g) / (d + 1e-8) + 4
    h = torch.where(mx == r, hr, torch.where(mx == g, hg, hb)) / 6.0
    h = torch.where(d > 1e-6, h, torch.zeros_like(h))
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


# Lightroom HSL band centres (degrees); Purple/Magenta are not asked of the model -> fixed 0
BANDS = [("Red", 0), ("Orange", 30), ("Yellow", 60), ("Green", 120), ("Aqua", 180), ("Blue", 240),
         ("Purple", 270), ("Magenta", 300)]


def band_weights(h):
    """h in 0..1 -> (N, 8) piecewise-linear weights between neighbouring band centres (sum 1)."""
    deg = h * 360.0
    c = torch.tensor([b[1] for b in BANDS] + [360.0], dtype=h.dtype, device=h.device)
    w = torch.zeros(*h.shape, len(BANDS), dtype=h.dtype, device=h.device)
    for i in range(len(BANDS)):
        lo, hi = c[i], c[i + 1]
        inside = (deg >= lo) & (deg < hi)
        t = ((deg - lo) / (hi - lo)).clamp(0, 1)
        j = (i + 1) % len(BANDS)
        w[..., i] += torch.where(inside, 1 - t, torch.zeros_like(t))
        w[..., j] += torch.where(inside, t, torch.zeros_like(t))
    return w


def g(adj, k):
    v = adj.get(k, 0) or 0
    try:
        return float(v)
    except Exception:
        return 0.0


@torch.no_grad()
def apply(rgb_u8, adj):
    x = torch.from_numpy(np.array(rgb_u8, copy=True)).permute(2, 0, 1)[None].float().to(DEV) / 255
    H, W = x.shape[-2:]
    L = max(H, W)
    lin = s2l(x)
    # --- white balance (multiplicative gains in linear light) + exposure
    T, Ti = g(adj, "IncrementalTemperature") / 100, g(adj, "IncrementalTint") / 100
    gains = torch.tensor([2 ** (0.45 * T), 2 ** (-0.35 * Ti), 2 ** (-0.55 * T)], device=DEV).view(1, 3, 1, 1)
    gains = gains / luma(gains.view(1, 3, 1, 1)).clamp(min=1e-3)  # keep luminance roughly constant
    lin = lin * gains * (2 ** g(adj, "Exposure2012"))
    # soft shoulder instead of hard clip for exposure pushes
    lin = torch.where(lin > 0.8, 0.8 + 0.2 * torch.tanh((lin - 0.8) / 0.2), lin)
    x = l2s(lin)
    # --- tone on perceptual luma
    Y = luma(x).clamp(1e-4, 1)
    base = guided(Y, Y, max(8, L // 24), 1e-2, s=4).clamp(0, 1)
    detail = Y - base
    hl, sh = g(adj, "Highlights2012") / 100, g(adj, "Shadows2012") / 100
    base = base + 0.30 * hl * smoothstep(0.45, 1.0, base) * base \
                + 0.35 * sh * (1 - smoothstep(0.0, 0.55, base)) * (1 - base) * base ** 0.35
    Y2 = (base + detail).clamp(0, 1)
    c = g(adj, "Contrast2012") / 100
    Y2 = Y2 + c * 0.9 * Y2 * (1 - Y2) * (2 * Y2 - 1) * (1 if c > 0 else 0.8)
    wh, bl = g(adj, "Whites2012") / 100, g(adj, "Blacks2012") / 100
    Y2 = Y2 + 0.18 * wh * Y2 ** 3
    Y2 = Y2 + 0.15 * bl * (1 - Y2) ** 4   # + lifts blacks (matte), - deepens
    # --- dehaze (simplified: black-point pull + midtone contrast + saturation)
    dz = g(adj, "Dehaze") / 100
    if dz:
        Y2 = (Y2 - 0.06 * dz * (1 - Y2) ** 2) / (1 - 0.03 * dz)
        Y2 = Y2 + 0.4 * dz * Y2 * (1 - Y2) * (2 * Y2 - 1)
    Y2 = Y2.clamp(0, 1)
    # --- clarity: large-radius local contrast, midtone weighted
    cl = g(adj, "Clarity2012") / 100
    if cl:
        bb = guided(Y2, Y2, max(8, L // 40), 4e-3, s=2)
        wmid = (4 * Y2 * (1 - Y2)).clamp(0, 1) ** 0.7
        Y2 = Y2 + (0.9 if cl > 0 else 0.7) * cl * wmid * (Y2 - bb)
    tx = g(adj, "Texture") / 100
    if tx:
        Y2 = Y2 + (1.0 if tx > 0 else 0.7) * tx * (Y2 - blur(Y2, max(1.0, L / 900)))
    Y2 = Y2.clamp(0, 1)
    # multiplicative (keeps saturation) but ratio capped, remainder added as grey (lifting near-black
    # pixels by a huge ratio would blow up their colour noise / cast)
    ratio = (Y2 / Y).clamp(max=2.0)
    x = (x * ratio + (Y2 - Y * ratio)).clamp(0, 1)
    # --- vibrance / saturation / HSL in HSV
    h, s, v = rgb2hsv(x)
    w = band_weights(h)
    def bandvec(prefix):
        return torch.tensor([g(adj, f"{prefix}Adjustment{b[0]}") / 100 for b in BANDS], device=DEV)
    ha = (w * bandvec("Hue")).sum(-1)
    sa = (w * bandvec("Saturation")).sum(-1)
    la = (w * bandvec("Luminance")).sum(-1)
    vib, sat = g(adj, "Vibrance") / 100, g(adj, "Saturation") / 100
    skin = w[..., 1] + 0.5 * w[..., 0]  # protect orange/red a bit for vibrance
    s = s * (1 + sat) * (1 + vib * (1 - s) * (1 - 0.5 * skin)) * (1 + 0.25 * dz)
    s = s * (1 + sa)
    h = (h + ha * (20 / 360)) % 1.0
    v = v * (1 + 0.35 * la * s.clamp(0, 1))
    x = hsv2rgb(h, s.clamp(0, 1), v.clamp(0, 1))
    return (x[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy() * 255 + 0.5).astype(np.uint8)


if __name__ == "__main__":  # quick self-test on one photo
    import sys
    import time
    from PIL import Image
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "llm-pick-experiment", "photos", sys.argv[1] if len(sys.argv) > 1 else "food_bluecast_dark.jpg")
    im = Image.open(p).convert("RGB")
    im.thumbnail((900, 900))
    a = np.asarray(im)
    tests = {
        "fix": dict(Exposure2012=1.2, IncrementalTemperature=35, Contrast2012=15, Shadows2012=30, Blacks2012=-10,
                    Vibrance=20, Clarity2012=10),
        "matte": dict(Blacks2012=60, Contrast2012=-20),
        "hsl": dict(SaturationAdjustmentOrange=-60, HueAdjustmentGreen=60, LuminanceAdjustmentBlue=-60, Dehaze=40),
    }
    outs = [a]
    for n, adj in tests.items():
        t0 = time.time()
        outs.append(apply(a, adj))
        print(n, round(time.time() - t0, 2), "s")
    Image.fromarray(np.concatenate(outs, 1)).save(os.path.join(os.environ.get("TEMP", here), "render_test.jpg"))
