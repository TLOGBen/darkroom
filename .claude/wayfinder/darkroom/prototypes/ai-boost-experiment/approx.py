"""Program-side approximation of Lightroom Clarity / Dehaze / Texture (prototype, not Adobe-calibrated).

Methods follow research/03-proprietary-approximations.md:
  Dehaze  : dark channel prior + fast guided filter, in linear light; 50/50 mix of luminance-ratio and per-channel recovery.
  Clarity : fast local Laplacian filter (Aubry 2014) on perceptual luma, weighted to midtones.
  Texture : Laplacian-pyramid mid-band gain with soft coring (levels 1..2 at ~1 MP).
Luma changes are applied back to RGB additively in sRGB space (keeps hue).

usage (ComfyUI embedded python):
  python -s approx.py --clarity 40 --dehaze 30 --texture 40 --suffix pos
  python -s approx.py --clarity -40 --suffix neg
Reads photos.json, writes prog/<id>_<suffix>.png and prints per-image timings.
"""
import argparse, json, os, time
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
dev = "cuda" if torch.cuda.is_available() and os.environ.get("APPROX_CPU") != "1" else "cpu"


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


_g5 = torch.tensor([1, 4, 6, 4, 1], dtype=torch.float32) / 16
K2 = (_g5[:, None] * _g5[None, :])[None, None]


def down(x):
    return F.conv2d(F.pad(x, (2, 2, 2, 2), mode="replicate"), K2.to(x.device))[..., ::2, ::2]


def up(x, shape):
    # normalized convolution: zero-stuff, blur, divide by blurred mask (no dark borders from padding zeros)
    y = torch.zeros(x.shape[0], x.shape[1], shape[-2], shape[-1], device=x.device, dtype=x.dtype)
    m = torch.zeros(1, 1, shape[-2], shape[-1], device=x.device, dtype=x.dtype)
    y[..., ::2, ::2] = x
    m[..., ::2, ::2] = 1
    k = K2.to(x.device)
    return F.conv2d(F.pad(y, (2, 2, 2, 2)), k) / F.conv2d(F.pad(m, (2, 2, 2, 2)), k)


def gauss_pyr(x, n):
    p = [x]
    for _ in range(n - 1):
        p.append(down(p[-1]))
    return p


def lap_pyr(x, n):
    g = gauss_pyr(x, n)
    return [g[i] - up(g[i + 1], g[i].shape) for i in range(n - 1)] + [g[-1]]


def collapse(L):
    res = L[-1]
    for l in range(len(L) - 2, -1, -1):
        res = up(res, L[l].shape) + L[l]
    return res


def fast_llf(I, sigma=0.2, alpha=0.5, K=12, n=None):
    n = n or int(np.log2(min(I.shape[-2:]))) - 3
    G = gauss_pyr(I, n)
    refs = torch.linspace(0, 1, K, device=I.device)
    step = float(refs[1] - refs[0])
    acc = [torch.zeros_like(G[l]) for l in range(n - 1)]
    for g in refs:
        d = I - g
        ad = d.abs()
        r = torch.where(ad < sigma, g + torch.sign(d) * sigma * (ad / sigma).clamp(min=1e-6) ** alpha, I)
        L = lap_pyr(r, n)
        for l in range(n - 1):
            w = (1 - (G[l] - g).abs() / step).clamp(min=0)
            acc[l] += w * L[l]
    return collapse(acc + [G[-1]])


def srgb_to_lin(x):
    return torch.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = x.clamp(0, 1)
    return torch.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def luma(rgb):  # Rec.709 weights on sRGB-encoded values (perceptual luma)
    w = torch.tensor([0.2126, 0.7152, 0.0722], device=rgb.device).view(1, 3, 1, 1)
    return (rgb * w).sum(1, keepdim=True)


def dehaze(rgb_srgb, amount):
    if amount == 0:
        return rgb_srgb
    lin = srgb_to_lin(rgb_srgb)
    H, W = lin.shape[-2:]
    w = max(5, int(max(H, W) * 0.01) | 1)
    dark = -F.max_pool2d(-lin.min(1, keepdim=True)[0], w, stride=1, padding=w // 2)
    flat = dark.flatten()
    idx = flat.topk(max(1, flat.numel() // 1000)).indices        # brightest 0.1% of dark channel
    A = lin.flatten(2)[:, :, idx].mean(2)[..., None, None].clamp(min=0.05)
    omega = 0.9 * abs(amount) / 100
    t = 1 - omega * (-F.max_pool2d(-(lin / A).min(1, keepdim=True)[0], w, stride=1, padding=w // 2))
    Y = luma(rgb_srgb)
    t = guided(Y, t, max(8, int(max(H, W) * 0.04)), 1e-3, s=4).clamp(0.1, 1)
    if amount > 0:
        per = (lin - A) / t + A
        yl = luma(lin).clamp(min=1e-4)
        ylr = (yl - luma(A)) / t + luma(A)
        lum = lin * (ylr.clamp(min=0) / yl)
        out = 0.5 * per + 0.5 * lum
    else:
        out = lin * t + A * (1 - t)   # add haze
    return lin_to_srgb(out)


def clarity(Y, c):
    if c == 0:
        return Y
    alpha = 1 - 0.6 * c / 100 if c > 0 else 1 + 0.8 * abs(c) / 100
    Yl = fast_llf(Y, sigma=0.2, alpha=alpha)
    wmid = (4 * Y * (1 - Y)).clamp(0, 1) ** 0.7       # midtone weight; extremes untouched
    return Y + wmid * (Yl - Y)


def texture(Y, t):
    if t == 0:
        return Y
    n = 5
    L = lap_pyr(Y, n)
    gain = 1 + 1.0 * t / 100 if t > 0 else 1 - 0.8 * abs(t) / 100
    long_side = max(Y.shape[-2:])
    bands = [1, 2] if long_side <= 2000 else [2, 3]    # ~2..8 px detail at ~1 MP
    for l in bands:
        d = L[l]
        noise = d.abs().median() * 1.4826
        thr = 1.0 * noise
        core = torch.sign(d) * (d.abs() - thr).clamp(min=0)   # soft-threshold part gets the gain
        L[l] = d + (gain - 1) * core
    return collapse(L)


def process(rgb_np, c=0, d=0, t=0):
    x = torch.from_numpy(np.array(rgb_np)).permute(2, 0, 1)[None].float().to(dev) / 255
    x = dehaze(x, d)
    Y = luma(x)
    Y2 = texture(clarity(Y, c), t)
    out = (x + (Y2 - Y)).clamp(0, 1)
    return (out[0].permute(1, 2, 0).cpu().numpy() * 255 + 0.5).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clarity", type=float, default=0)
    ap.add_argument("--dehaze", type=float, default=0)
    ap.add_argument("--texture", type=float, default=0)
    ap.add_argument("--suffix", required=True)
    ap.add_argument("--only")
    a = ap.parse_args()
    photos = json.load(open(os.path.join(HERE, "photos.json"), encoding="utf-8"))
    os.makedirs(os.path.join(HERE, "prog"), exist_ok=True)
    print("device", dev, torch.__version__)
    for r in photos:
        if a.only and r["id"] != a.only:
            continue
        im = np.asarray(Image.open(os.path.join(HERE, "photos", r["file"])).convert("RGB"))
        process(im[:64, :64], a.clarity, a.dehaze, a.texture)  # warm-up
        t0 = time.perf_counter()
        out = process(im, a.clarity, a.dehaze, a.texture)
        if dev == "cuda":
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t0) * 1000
        Image.fromarray(out).save(os.path.join(HERE, "prog", f"{r['id']}_{a.suffix}.png"))
        print(f"{r['id']}\t{im.shape[1]}x{im.shape[0]}\t{ms:.0f} ms ({dev})")


if __name__ == "__main__":
    main()
