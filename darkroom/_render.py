"""GPU rendering of Params onto an sRGB image (torch, float32).

Pipeline (each stage is skipped when its settings sit at the default, so strength 0 is an exact identity):
  sRGB -> linear light: white balance (incremental), calibration, shadow tint, exposure (+shoulder), dehaze
  -> sRGB-encoded luma: highlights/shadows (guided-filter base layer), contrast, whites/blacks end-point
     curves, clarity (fast local Laplacian), texture (pyramid mid-band) -> local gradient corrections
  -> parametric + point tone curves -> vibrance/saturation, HSL, colour grading (each tone once)
  -> grayscale -> vignette, grain, sharpening.
Method choices follow research/03-proprietary-approximations.md; the numeric mappings are uncalibrated
first guesses (P3: closeness to Lightroom is left to the calibration set).

Layer: core library. Depends on torch, numpy, `_color` (transfer curves) and `_params` (Params); `_geometry` is
imported inside render() only. Nothing here reads or writes files. The App reaches it through `darkroom.render`
(its GPU engine adapter keeps the photo resident on the GPU and calls render for every preview / export).

Why this order (it mirrors Lightroom's develop pipeline as far as it is publicly understood):
- White balance, exposure and dehaze are physical operations on light, so they run on linear light, where
  "twice the light" is "twice the value". Doing exposure on encoded values would shift colours.
- Highlights / shadows / contrast / whites / blacks / clarity / texture are perceptual tone controls; Lightroom
  applies them on a gamma-like encoding of luminance. They are computed on the luma channel only and transferred
  back to RGB as a ratio, so they change brightness without shifting hue.
- Local (masked) corrections run after the global tone stage, then the curves, then colour, so a preset's curve
  and colour grade apply to the masked areas too.
- Vignette, grain and sharpening are output effects and come last (grain is not sharpened, the vignette is
  measured on the final crop).
Every stage tests whether its sliders are at their neutral value and returns its input untouched otherwise; this
is what makes strength 0 an exact identity (contract A8 = "at strength 0 the output equals the input within 1e-4")
and keeps a typical preset well under the real-time budget (contract A17 = "full global pipeline on a 1.5 MP
image, median <= 25 ms on CUDA").

Tensor convention: images are 1x3xHxW float32 tensors in 0..1 on one device; single-channel helpers use
1x1xHxW. `g` is always `Params.get` (a key -> value lookup with defaults), so every stage reads sliders by their
Lightroom name.
"""
import math

import numpy as np
import torch
import torch.nn.functional as F

from . import _color
from ._params import Params

# Lightroom's eight HSL / colour mixer bands and the hue (degrees on the HSV wheel) at which each band has full
# effect; between two centres the effect fades linearly, so every hue belongs to at most two bands.
HSL_COLORS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
HSL_CENTERS = (0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0)  # degrees


def pick_device(device=None):
    """torch.device for `device`, or CUDA when available, else CPU (the App warns when it falls back to CPU)."""
    if device is not None:
        return torch.device(device)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# --------------------------------------------------------------------------- small image ops


def _box(x, r):
    """Mean over a (2r+1) x (2r+1) window with replicated borders (same size out as in)."""
    return F.avg_pool2d(F.pad(x, (r, r, r, r), mode="replicate"), 2 * r + 1, stride=1)


def _guided(I, p, r, eps, s=1):
    """Fast guided filter (He et al.); I guide, p input, r radius at full resolution, s subsampling.

    An edge-preserving blur: inside each window the output is modelled as a*I + b, fitted by least squares, so
    flat regions are smoothed while strong edges of the guide survive. That is why it is used as the "base layer"
    for highlights / shadows (adjusting the base does not create halos around edges, the classic artefact of a
    plain Gaussian split) and to refine the dehaze transmission map. eps controls what counts as an edge
    (larger = smoother). With s > 1 the coefficients are computed on a downscaled copy and upsampled
    (He & Sun's "fast" variant), which is visually identical and several times faster at full resolution.
    """
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
    """Normalised 1D Gaussian kernel truncated at 3 sigma -> (kernel, radius)."""
    r = max(1, int(math.ceil(sigma * 3)))
    t = torch.arange(-r, r + 1, dtype=torch.float32, device=device)
    k = torch.exp(-t * t / (2 * sigma * sigma))
    return k / k.sum(), r


def _blur(x, sigma):
    """Separable Gaussian blur (horizontal pass then vertical pass), per channel, replicated borders."""
    k, r = _gauss1d(sigma, x.device)
    c = x.shape[1]
    x = F.conv2d(F.pad(x, (r, r, 0, 0), mode="replicate"), k.view(1, 1, 1, -1).expand(c, 1, 1, -1), groups=c)
    return F.conv2d(F.pad(x, (0, 0, r, r), mode="replicate"), k.view(1, 1, -1, 1).expand(c, 1, -1, 1), groups=c)


_G5 = None   # the 5x5 binomial kernel, cached per device


def _down(x):
    """One Gaussian-pyramid step: 5x5 binomial blur (1 4 6 4 1)/16 then keep every other pixel (half size)."""
    global _G5
    if _G5 is None or _G5.device != x.device:
        g = torch.tensor([1, 4, 6, 4, 1], dtype=torch.float32, device=x.device) / 16
        _G5 = (g[:, None] * g[None, :])[None, None]
    c = x.shape[1]
    return F.conv2d(F.pad(x, (2, 2, 2, 2), mode="replicate"), _G5.expand(c, 1, 5, 5), stride=2, groups=c)


def _up(x, shape):
    """Bilinear upsample of x to the spatial size of `shape` (inverse step of _down)."""
    return F.interpolate(x, size=tuple(shape[-2:]), mode="bilinear", align_corners=False)


def _levels(h, w):
    """Pyramid depth for an h x w image: down to roughly 8-16 px on the short side, at least 2 levels."""
    return max(2, int(math.log2(max(2, min(h, w)))) - 3)


def _fast_llf(I, alpha, sigma=0.2, K=8):
    """Fast local Laplacian filter (Aubry et al. 2014) on a 1x1xHxW image in 0..1; alpha<1 boosts detail.

    Why this filter for Clarity: Lightroom's Clarity raises local contrast in the midtones without the halos an
    unsharp mask with a big radius would produce. Local Laplacian filters (Paris et al. 2011) do exactly that: for
    each pixel, small differences around its own grey level (|d| < sigma) are remapped with the power `alpha`
    (alpha < 1 amplifies them = more clarity, alpha > 1 compresses them = negative clarity), while large
    differences (real edges) are left alone, so edges do not get halos.
    The "fast" variant samples K reference grey levels g, remaps the whole image once per level, builds the
    Laplacian pyramid of each remapped image, and for every pixel interpolates linearly between the two
    references nearest to its own value (weights `w`). The references are processed in chunks so a large image
    does not need K full-size copies at once. Returns the filtered 1x1xHxW image.
    """
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
    """0 below a, 1 above b, a smooth S (3t^2 - 2t^3) in between: used for every soft zone boundary."""
    t = ((x - a) / (b - a)).clamp(0, 1)
    return t * t * (3 - 2 * t)


def _rgb2hsv(x):
    """1x3xHxW RGB -> (hue in 0..1, saturation 0..1, value = max channel), each 1x1xHxW.

    Grey pixels (no chroma) get hue 0 and saturation 0 instead of a noisy hue, so HSL adjustments leave them
    alone."""
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
    """Inverse of _rgb2hsv (the branch-free formula f(n) = v - v*s*clamp(min(k, 4 - k), 0, 1), k = (n + 6h) mod 6)."""
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
    """The fully saturated, full-value colour of a hue angle (as on Lightroom's colour wheels), 1x3x1x1."""
    h = torch.tensor([[[[hue_deg / 360.0]]]], device=device)
    return _hsv2rgb(h, torch.ones_like(h), torch.ones_like(h))      # 1x3x1x1


# --------------------------------------------------------------------------- linear-light stage


def _calibration_matrix(g):
    """3x3 matrix for Lightroom's Calibration panel (Red/Green/Blue Primary hue and saturation), or None.

    Lightroom's calibration edits where the camera's red, green and blue primaries sit; on an already rendered
    sRGB photo the closest equivalent is a 3x3 mix in linear light. Each column is one primary: its hue slider
    pushes it toward a neighbouring primary (e.g. red +hue toward yellow), its saturation slider scales its
    distance from its own luminance. Finally each row is normalised to sum 1 so that greys (R = G = B) map to
    themselves: calibration changes colours, never the white balance.
    """
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
    """Linear-light stage: white balance, calibration, shadow tint, exposure, dehaze. Input / output linear 0..1.

    - IncrementalTemperature / IncrementalTint: per-channel gains (warmer = more red, less blue; tint + = less
      green, i.e. magenta), renormalised so the luminance of white is unchanged and only the colour shifts.
      Lightroom uses these relative sliders for JPEG/TIFF input (absolute Kelvin needs RAW data, see _coverage).
    - Calibration: _calibration_matrix.
    - ShadowTint (calibration panel): green / magenta shift weighted toward the shadows ((1 - luma)^3).
    - Exposure2012: multiply by 2^EV, as one photographic stop doubles the light. For positive exposure a soft
      shoulder compresses the brightest channel above 0.8 with tanh instead of hard clipping, which is how
      Lightroom's PV2012 rolls highlights off; scaling all three channels by the same factor keeps the hue.
    - Dehaze: _dehaze.
    """
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
    """Dark channel prior + guided-filter refined transmission, in linear light.

    The haze model (Koschmieder): observed = scene * t + A * (1 - t), where A is the airlight (the colour of the
    haze) and t the transmission (how much scene light gets through). He et al.'s dark channel prior says that in
    a haze-free photo almost every patch has some channel close to 0, so a bright local minimum means haze:
    - the airlight A is the mean colour of the 0.1% pixels with the brightest dark channel;
    - t = 1 - omega * darkchannel(I / A), refined with the guided filter so it follows object edges, and kept
      >= 0.15 so dense haze is not amplified into noise;
    - positive amount solves the model for the scene (half per channel, half luminance-only, which avoids strong
      colour shifts); negative amount adds haze instead (blends toward A).
    Window sizes are fractions of the long edge so the effect looks the same at preview and export resolution.
    """
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
    """Basic-panel tone controls on the encoded luma, transferred back to RGB. Input / output encoded sRGB 0..1.

    Work happens on Y = luma(x) only, then RGB is rebuilt as x * (Y2 / Y) (+ a small additive term when the ratio
    is capped at 2 so near-black pixels do not explode). Scaling RGB by a common ratio keeps the hue and roughly
    the saturation, which is how Lightroom's tone sliders behave.
    - Highlights / Shadows: split Y into an edge-preserving base (guided filter, radius ~ L/24) and detail; only
      the base is brightened / darkened, inside soft zones (smoothstep above ~0.45 for highlights, below ~0.55 for
      shadows), then the detail is added back. Local contrast survives, which is the point of these sliders.
    - Contrast: a cubic S-curve around mid-grey, y + c*k*y(1-y)(2y-1): fixed at 0, 0.5 and 1, steeper midtones.
    - Whites / Blacks: move the end points (y^4 near white, (1-y)^4 near black). Positive Blacks lifts the darkest
      tones (contract A9 = "positive Blacks2012 brightens the darkest greys, negative darkens; never reversed").
    - Clarity: _fast_llf, weighted to the midtones (4y(1-y)), like Lightroom's clarity which spares deep shadows
      and bright highlights.
    - Texture: _texture.
    """
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


REF_LONG_EDGE = 3000.0   # verbatim (CONTRACT-s1-experience S6 / core patch K4): detail effects scale with L / 3000


def _texture_bands(L):
    """Pyramid levels carrying the texture band at long edge L: (2, 3) at the reference size, one level up or
    down per doubling / halving, never below (1, 2) (K4)."""
    s = int(round(math.log2(max(1.0, L) / REF_LONG_EDGE)))
    lo = max(1, 2 + s)
    return lo, lo + 1


def _texture(Y, t):
    """Mid-frequency pyramid bands (the same fraction of the image at every size, K4) with soft coring.

    Lightroom's Texture targets medium-size detail (skin pores, foliage) and leaves both fine noise and large
    shapes alone, unlike Clarity. Here: build a Laplacian pyramid, scale only the bands chosen by
    _texture_bands, and before scaling subtract a noise floor from every coefficient ("coring", estimated as the
    band's mean absolute value times sqrt(pi/2), i.e. the standard deviation of a zero-mean Gaussian) so that flat
    areas are not turned into amplified noise. Negative texture smooths the same bands.
    """
    bands = _texture_bands(max(Y.shape[-2:]))
    n = bands[1] + 2
    G = [Y]
    for _ in range(n - 1):
        G.append(_down(G[-1]))
    lap = [G[i] - _up(G[i + 1], G[i].shape) for i in range(n - 1)]
    gain = 1 + 1.0 * t if t > 0 else 1 - 0.8 * abs(t)
    for l in bands:
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
    """Pixel-centre coordinates (x + 0.5, y + 0.5) as broadcastable 1x1x1xW and 1x1xHx1 tensors."""
    ys = (torch.arange(H, device=device, dtype=torch.float32) + 0.5).view(1, 1, H, 1)
    xs = (torch.arange(W, device=device, dtype=torch.float32) + 0.5).view(1, 1, 1, W)
    return xs, ys


def _shape_mask(s, H, W, device, grid=None):
    """grid: None = the image's own pixel centres; else (xs, ys, Hs, Ws) - every output pixel's point in an
    Hs x Ws source (CONTRACT-s3-crop C8: a mask covers the same content after rotate / flip / straighten / crop).

    Returns the 0..1 weight of one mask shape at every output pixel (contract A14 = "linear and radial gradients
    follow the xmp geometry: 0..1 relative coordinates, MaskInverted, Flipped").
    - Linear gradient: project each pixel onto the segment Zero -> Full; 0 at the Zero point, 1 at the Full
      point, clamped beyond (Lightroom's three-line graduated filter).
    - Radial gradient: an ellipse inscribed in the Left/Top/Right/Bottom box, rotated by Angle. d is the
      normalised elliptical distance (1 on the outline); Feather is the share of the radius used for the soft
      edge. A radial filter acts outside the ellipse unless Flipped is set (then inside), hence the
      `1 - inside` default.
    The result is multiplied by the shape's opacity (MaskValue). A degenerate shape gives an all-zero mask of the
    rendered size.
    """
    if grid is None:
        xs, ys = _pixel_grid(H, W, device)
    else:
        xs, ys, H, W = grid
    if s["type"] == "Mask/Gradient":
        zx, zy, fx, fy = s["ZeroX"] * W, s["ZeroY"] * H, s["FullX"] * W, s["FullY"] * H
        dx, dy = fx - zx, fy - zy
        n2 = dx * dx + dy * dy
        if n2 < 1e-9:
            return torch.zeros_like(xs + ys)       # the size of what is rendered (S3 seal F1: with a grid too)
        m = (((xs - zx) * dx + (ys - zy) * dy) / n2).clamp(0, 1)
    else:  # Mask/CircularGradient: ellipse in the Left/Top/Right/Bottom box, rotated by Angle
        cx, cy = (s["Left"] + s["Right"]) / 2 * W, (s["Top"] + s["Bottom"]) / 2 * H
        a, b = abs(s["Right"] - s["Left"]) / 2 * W, abs(s["Bottom"] - s["Top"]) / 2 * H
        if a < 1e-6 or b < 1e-6:
            return torch.zeros_like(xs + ys)       # the size of what is rendered (S3 seal F1: with a grid too)
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


# Local slider -> the global slider whose code renders it, and the factor between their units. Lightroom stores
# local values as fractions (-1..1 standing for -100..100; for exposure 1.0 stands for 4 stops) while the global
# sliders use -100..100 (exposure in stops), so reusing the global stages needs this scaling.
_LOCAL_MAP = (("LocalExposure2012", "Exposure2012", 4.0), ("LocalContrast2012", "Contrast2012", 100.0),
              ("LocalHighlights2012", "Highlights2012", 100.0), ("LocalShadows2012", "Shadows2012", 100.0),
              ("LocalWhites2012", "Whites2012", 100.0), ("LocalBlacks2012", "Blacks2012", 100.0),
              ("LocalClarity2012", "Clarity2012", 100.0), ("LocalTexture", "Texture", 100.0),
              ("LocalDehaze", "Dehaze", 100.0), ("LocalTemperature", "IncrementalTemperature", 100.0),
              ("LocalTint", "IncrementalTint", 100.0), ("LocalSaturation", "Saturation", 100.0))


def _local(x, masks, grid=None):
    """Apply the local corrections (Params.masks) to the encoded image x.

    For each correction: combine its shapes with max() (Lightroom adds shapes of one mask as a union), scale by
    the correction amount (this is where preset strength acts on local adjustments), render the same global
    stages with the local values, and blend: x + M * (adjusted - x). Corrections are applied one after another
    in file order. `grid` maps output pixels to source points when a geometry is active (see _shape_mask).
    """
    H, W = x.shape[-2:]
    for m in masks:
        lv = {gk: m["values"].get(lk, 0.0) * sc for lk, gk, sc in _LOCAL_MAP}
        if not any(lv.values()) or not m["shapes"] or not m.get("amount", 1.0):
            continue
        M = None
        for s in m["shapes"]:
            sm = _shape_mask(s, H, W, x.device, grid)
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
    """Monotone cubic (Fritsch-Carlson) through points (px ascending), evaluated at xs; numpy float64.

    Why monotone: a tone curve must never fold back (a brighter input must not come out darker), and an ordinary
    cubic spline overshoots between close points. Fritsch-Carlson picks the tangent at each point as a weighted
    harmonic mean of the neighbouring slopes (0 at a local extremum), which guarantees monotonic segments and is
    visually very close to Lightroom's point curve. Duplicate x positions are dropped; outside the first / last
    point the curve is flat (Lightroom extends the end points horizontally)."""
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
    """Lightroom's parametric tone curve (Shadows / Darks / Lights / Highlights + three split points) at xs.

    The three split sliders divide 0..1 into four regions; each slider adds a smooth bump (sin^2 window) centred
    in its region and reaching into the neighbouring ones, scaled by amount / 100 * 0.15. The running maximum
    at the end keeps the curve monotone even for extreme settings. Returns xs unchanged when all four are 0.
    """
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
    """A point curve lying on the diagonal y = x (Lightroom writes these for "Linear"), i.e. no effect."""
    return all(abs(x - y) < 1e-9 for x, y in pts)


def _curve_luts(p, N=1024):
    """All tone curves composed into three N-entry lookup tables (R, G, B), or None when no curve is active.

    Composition order as in Lightroom: parametric curve -> master point curve (ToneCurvePV2012) -> per-channel
    point curve. Evaluating once on the CPU into a 1024-entry table and then doing a single interpolated lookup
    per pixel on the GPU is much cheaper than evaluating splines per pixel. Returns float32 array 3 x N.
    """
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
    """Per-channel lookup with linear interpolation between the two nearest table entries (a 1D texture fetch)."""
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
    """Soft tonal-zone weights for colour grading from luma Y: shadow, midtone, highlight (and global = None).

    The shadow / highlight boundary sits at mid-grey shifted by Balance; Blending widens the transition (Lightroom's
    Blending slider: 0 = hard split, 100 = wide overlap). The midtone weight is a parabola peaking at that same
    centre. "global" has no weight (applies everywhere)."""
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
    """Add the chroma of `hue` (its colour minus its own luma, so brightness is unchanged) scaled by saturation
    and the zone weight. Adding chroma rather than blending toward a colour is what keeps neutral tones' brightness
    and lets a toned black & white image keep its tonal range."""
    rgb = _hue_rgb(hue, x.device)
    chroma = rgb - _color.luma(rgb)
    amt = 0.35 * sat / 100
    return x + (chroma * amt if weight is None else weight * chroma * amt)


def _color_grade(x, g):
    """Colour grading / split toning: one tint and one luminance offset per zone, each tone exactly once.

    Contract A10 = "shadow / highlight tones read only SplitToning*, midtone / global only ColorGrade*Midtone* /
    *Global*; no tone applied twice" (see TINT_ZONES)."""
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
    """Presence and colour panels: vibrance / saturation -> HSL mixer -> optional grayscale -> colour grading.

    - Saturation scales every pixel's distance from its luma; Vibrance does the same but weighted by
      (1 - current saturation), so already vivid colours (and, in Lightroom, skin tones) change less.
    - HSL: per-band hue shift (up to +-30 degrees at +-100), saturation and luminance, interpolated between the
      eight band centres by the pixel's hue. Luminance changes are weighted by saturation so greys are unaffected.
    - Grayscale before grading (contract A11 = "convert to B&W first, then tint; without any tint the output is
      exactly R = G = B").
    """
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
    if g("ConvertToGrayscale"):  # toned B&W: convert first, then colour grading / split toning tints it
        x = _grayscale(x, g)
    return _color_grade(x, g)


def _grayscale(x, g):
    """Black & white conversion with Lightroom's B&W mix (GrayMixer*): luma brightened / darkened per hue band.

    The per-band offset is weighted by the pixel's saturation: a colourful red responds to the Red slider, a grey
    pixel stays as it is. Returns the grey value copied to all three channels."""
    Y = _color.luma(x)
    mix = [g(f"GrayMixer{c}") / 100 for c in HSL_COLORS]
    if any(mix):
        h, s, _ = _rgb2hsv(x)
        Y = Y * (1 + 0.6 * _hue_interp(h, mix) * s)
    return Y.clamp(0, 1).repeat(1, 3, 1, 1)


# --------------------------------------------------------------------------- effects


def _vignette(x, g):
    """Post-crop vignette: darken (amount < 0) or lighten (amount > 0) toward the corners of the final picture.

    u, v are -1..1 across the image. Roundness > 0 pulls the shape from the image's own aspect toward a circle;
    Midpoint moves where the falloff starts, Feather how soft it is. Runs on the cropped output, so the vignette
    follows the crop as in Lightroom's "post-crop" vignette."""
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


_NOISE = {}   # small cache of grain fields keyed by (size, blur, device); cleared when it grows past 8 entries


def _grain_noise(H, W, sigma, device):
    """Unit-variance Gaussian noise blurred to grain size `sigma`, H x W, deterministic.

    The fixed seed makes the grain identical between the preview and the export of the same picture and between
    repeated previews (no "crawling" grain while dragging a slider); caching avoids regenerating it on every
    preview."""
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
    """Film grain: add blurred noise, strongest in the midtones (weight 0.3 + 0.7 * 4Y(1-Y)) like real film."""
    a = g("GrainAmount") / 100
    if not a:
        return x
    H, W = x.shape[-2:]
    scale = max(H, W) / REF_LONG_EDGE        # K4: grain size follows the image size; a smaller image also gets a
    sigma = max(0.3, (0.3 + 1.5 * g("GrainSize") / 100) * scale)   # weaker noise, like the big one scaled down
    n = _grain_noise(H, W, sigma, x.device)
    Y = _color.luma(x).clamp(0, 1)
    wt = 0.3 + 0.7 * (4 * Y * (1 - Y))
    return x + 0.12 * a * min(1.0, scale) ** 0.5 * wt * n


def _sharpen(x, g):
    """Unsharp mask on luma: x + amount * (Y - blur(Y)). Luma only, so sharpening does not create colour fringes."""
    a = g("Sharpness") / 150
    if not a:
        return x
    Y = _color.luma(x)
    scale = max(x.shape[-2:]) / REF_LONG_EDGE   # K4: the radius is in pixels of a 3000 px image
    return x + a * (Y - _blur(Y, max(0.3, g("SharpenRadius") * scale)))


# --------------------------------------------------------------------------- driver


def _pipeline(x, p, grid=None):
    """The whole develop pipeline on a 1x3xHxW encoded sRGB tensor (see the module docstring for the order).

    p must already be at strength and clamped; grid is passed to the local masks when a geometry moved pixels.
    The linear stage is skipped entirely (no encode / decode round trip) when none of its sliders is set."""
    g = p.get
    x = x.clamp(0, 1)
    if any(g(k) for k in ("IncrementalTemperature", "IncrementalTint", "Exposure2012", "Dehaze", "ShadowTint",
                          "RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation")):
        x = _color.linear_to_srgb(_linear_stage(_color.srgb_to_linear(x), g))
    x = _tone(x, g)
    if p.masks:
        x = _local(x, p.masks, grid)
    luts = _curve_luts(p)
    if luts is not None:
        x = _apply_luts(x, luts)
    x = _color_ops(x, g)
    x = _vignette(x, g)
    x = _grain(x, g)
    x = _sharpen(x, g)
    return x.clamp(0, 1)


def _to_tensor(image, device):
    """Normalise the caller's image to a 1x3xHxW float32 tensor on the target device -> (tensor, restore).

    `restore(out)` converts the result back to the caller's form: a tensor goes back to its own device / dtype
    and rank (contract B1 = "a tensor already on the GPU is returned on the same device, with no host copy"),
    a numpy array becomes an HxWx3 float32 numpy array. uint8 / uint16 arrays are scaled to 0..1.
    Raises ValueError for a wrong shape."""
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


# --------------------------------------------------------------------------- geometry (CONTRACT-s3-crop C2, C7-C9)

RESAMPLE_MODE = "bicubic"     # verbatim (C9 / D12, kept after M2): grid_sample mode when angle != 0 or scaled
PREFILTER = 1.5               # more than 1.5 image pixels per output pixel: the image is area-shrunk first


def _warp(x, geometry, need_grid):
    """The output picture of `geometry` sampled from the 1x3xHxW image x, plus every output pixel's point in x
    (for the masks, C8) when need_grid: (out, (xs, ys, H, W) | None). angle 0 at the source's own scale is
    rot90 / flip / slicing only (byte for byte, C2); anything else is grid_sample (C9)."""
    H, W = x.shape[-2:]
    _, _, ow, oh, frame, (L, T, R, B), exact = geometry.sampling(W, H)
    k = geometry.rotate // 90
    if exact:
        def op(t):
            if k:
                t = torch.rot90(t, k=-k, dims=(2, 3))
            if geometry.flip:
                t = torch.flip(t, dims=(3,))
            return t[..., T:B, L:R]
        out = op(x).contiguous()
        grid = None
        if need_grid:
            xs, ys = _pixel_grid(H, W, x.device)
            grid = (op(xs.expand(1, 1, H, W)).contiguous(), op(ys.expand(1, 1, H, W)).contiguous(), H, W)
        return out, grid
    M = torch.tensor(geometry.matrix(W, H), dtype=torch.float64)
    X = (torch.arange(ow, dtype=torch.float64) + 0.5).view(1, -1)
    Y = (torch.arange(oh, dtype=torch.float64) + 0.5).view(-1, 1)
    gx = (M[0, 0] * X + M[0, 1] * Y + M[0, 2]).to(torch.float32).to(x.device).view(1, 1, oh, ow)
    gy = (M[1, 0] * X + M[1, 1] * Y + M[1, 2]).to(torch.float32).to(x.device).view(1, 1, oh, ow)
    grid = (gx, gy, H, W) if need_grid else None
    src = x
    f = math.sqrt(abs(float(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])))      # image pixels per output pixel
    if f > PREFILTER:                                                      # shrink first: no aliasing
        src = F.interpolate(x, size=(max(1, round(H / f)), max(1, round(W / f))), mode="area")
    g = torch.stack([gx[0, 0] * (2.0 / W) - 1.0, gy[0, 0] * (2.0 / H) - 1.0], dim=-1)[None]
    out = F.grid_sample(src, g, mode=RESAMPLE_MODE, padding_mode="zeros" if frame else "border",
                        align_corners=False)
    del g
    return out.clamp(0, 1), grid


@torch.no_grad()   # inference only: no autograd graph, which would double memory use
def render(image, params, strength=1.0, device=None, *, geometry=None):
    """Apply `params` at `strength` (0..2) to an sRGB image with values in 0..1.

    image: HxWx3 numpy array (float 0..1, or uint8/uint16) -> HxWx3 float32 array; or a 3xHxW / 1x3xHxW
    torch tensor -> tensor of the same shape on the same device. device: None = the tensor's device, or
    CUDA when available (CPU otherwise) for arrays.
    geometry: None (the picture as it is), or a darkroom.Geometry: the output picture is decided first (rotate,
    flip, straighten, crop), then the whole pipeline runs on it - the vignette and the detail effects belong to the
    cropped picture, the gradient masks stay on the same content (CONTRACT-s3-crop C7, C8).

    Steps: scale the parameters to `strength` (Params.at_strength) and clamp them to Lightroom's ranges (contract
    A19) -> move the image to the device -> apply the geometry (if any) -> run the pipeline -> convert back.
    Raises TypeError for a wrong params / geometry type, ValueError for a strength outside 0..2 or a wrong image
    shape. No side effects (pure function of its inputs; grain uses a fixed seed).
    """
    if not isinstance(params, Params):
        raise TypeError("params must be a darkroom.Params")
    from ._geometry import Geometry
    if geometry is not None and not isinstance(geometry, Geometry):
        raise TypeError("geometry must be a darkroom.Geometry or None")
    p = params.at_strength(strength).clamped()
    x, restore = _to_tensor(image, device)
    if geometry is None or (geometry.identity and geometry._bind is None):
        return restore(_pipeline(x, p))
    x, grid = _warp(x, geometry, bool(p.masks))
    return restore(_pipeline(x, p, grid))
