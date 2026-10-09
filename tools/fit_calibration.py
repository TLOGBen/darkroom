"""Fit the Highlights / Shadows / Whites / Blacks constants of darkroom/_render.py to Lightroom renders.

Reads the Lightroom exports of the calibration set (prototypes/calibration, single-slider sweeps A02..A05),
renders the same standard image with the same preset through the public API (darkroom.load_preset / render),
and reports per slider the mean CIEDE2000 and the luminance-curve difference before fitting; then a 1-D
least-squares search (minimise the mean of dE00^2) over each constant, and the same numbers after fitting.
The result is a Markdown report with suggested constants. It never edits darkroom/_render.py.

The search needs renders at constants other than the hard-coded ones, so the four tone terms of _render._tone
are mirrored here (formulas below, built from darkroom's own guided filter); before fitting, the mirror at the
current constants is checked against the public render() for every job and the run stops if they disagree.

  python -s tools/fit_calibration.py fit [--lr-dir DIR] [--base-dir DIR] [--input original|lr-baseline] [--stride N]
                                        [--report F]
  python -s tools/fit_calibration.py selftest [--noise S] [--keep] [--report F]

fit       LR exports default to <LocalLLMs>/outputs/lr-calibration (file names <date>-<code>_<label>__<image>.tif or
          plan B <date>-<code>__<image>.tif; the newest date wins); the standard images to
          <LocalLLMs>/scratch/lr-calibration/planB_base, falling back to the repo's charts/ for syn-*.
selftest  "fake Lightroom": renders the sweeps with known, different constants (TRUE_CONSTS) plus a little noise as
          16-bit TIFFs with Lightroom-style names into a temp folder, runs the same fit on them and checks it recovers
          the constants within SELFTEST_TOL (exit code 1 otherwise).
Reports go to outputs/calibration/<YYYY-MM-DD>-{fit,selftest}-report.md (outputs/ is not in git).
"""
import argparse
import csv
import datetime
import json
import math
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np  # noqa: E402
import torch  # noqa: E402

import darkroom  # noqa: E402
from darkroom import _color  # noqa: E402  (luma: the same weights the renderer uses)
from darkroom._render import _guided, _smoothstep, pick_device  # noqa: E402

CAL = os.path.join(REPO, ".claude", "wayfinder", "darkroom", "prototypes", "calibration")
MANIFEST = os.path.join(CAL, "manifest.csv")
PRESETS = os.path.join(CAL, "presets")
CHARTS = os.path.join(CAL, "charts")

# slider -> (manifest group code, constants it uses); constant names map 1:1 onto the literals in _render._tone
SLIDERS = {
    "Highlights2012": ("A02", ("hl",)),
    "Shadows2012": ("A03", ("sh",)),
    "Whites2012": ("A04", ("wh",)),
    "Blacks2012": ("A05", ("bl_pos", "bl_neg")),
}
CURRENT_CONSTS = {"hl": 0.30, "sh": 0.35, "wh": 0.18, "bl_pos": 0.12, "bl_neg": 0.10}
CONST_DOC = {
    "hl": "Highlights2012：base + K·hl·smoothstep(0.45,1,base)·base",
    "sh": "Shadows2012：base + K·sh·(1−smoothstep(0,0.55,base))·(1−base)·base^0.35",
    "wh": "Whites2012：Y + K·wh·Y⁴",
    "bl_pos": "Blacks2012 正值（抬黑）：Y + K·bl·(1−Y)⁴",
    "bl_neg": "Blacks2012 負值（壓黑）：Y + K·bl·(1−Y)⁴",
}
TRUE_CONSTS = {"hl": 0.42, "sh": 0.26, "wh": 0.27, "bl_pos": 0.19, "bl_neg": 0.07}  # selftest only
SELFTEST_TOL = 0.03          # recovered constant within 3 % of the true one
SELFTEST_NOISE = 0.004       # Gaussian noise (sigma, 0..1 scale, about 1 code value of 8-bit) on the fake references
MIRROR_TOL = 2e-3            # mirror vs public render(), max abs difference in 0..1
SEARCH_HI = 4.0              # search K in [0, 4 x current]
STRIDE = 2                   # dE on every 2nd pixel in each direction (the ops after the base are pointwise);
                             # about 25 MB of GPU memory per (setting, image) at 2048 px, 192 of them for a full set
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
IMG_EXT = (".tif", ".tiff", ".jpg", ".jpeg", ".png")


# ----------------------------------------------------------------------------------------------- paths


def localllms_root():
    root = os.environ.get("LOCALLLMS_ROOT")
    cfg = os.path.join(REPO, "config.local.json")
    if not root and os.path.exists(cfg):
        with open(cfg, "rb") as f:
            root = json.loads(f.read().decode("utf-8-sig")).get("localllms_root")
    return root


def today():
    return datetime.datetime.now().strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------------------------- colour


def srgb_to_lab(x):
    """1x3xHxW sRGB (0..1) -> 3xN CIELAB (D65)."""
    lin = _color.srgb_to_linear(x)[0].reshape(3, -1)
    m = torch.tensor([[0.4124564, 0.3575761, 0.1804375],
                      [0.2126729, 0.7151522, 0.0721750],
                      [0.0193339, 0.1191920, 0.9503041]], device=x.device, dtype=lin.dtype)
    xyz = m @ lin
    wp = torch.tensor([0.95047, 1.0, 1.08883], device=x.device, dtype=lin.dtype)[:, None]
    t = xyz / wp
    d = 6 / 29
    f = torch.where(t > d ** 3, t.clamp(min=1e-12) ** (1 / 3), t / (3 * d * d) + 4 / 29)
    return torch.stack([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def de2000(lab1, lab2):
    """CIEDE2000 (kL = kC = kH = 1) between two 3xN Lab tensors -> N."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = torch.hypot(a1, b1), torch.hypot(a2, b2)
    Cb7 = ((C1 + C2) / 2) ** 7
    G = 0.5 * (1 - torch.sqrt(Cb7 / (Cb7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = torch.hypot(a1p, b1), torch.hypot(a2p, b2)
    h1p = torch.rad2deg(torch.atan2(b1, a1p)) % 360
    h2p = torch.rad2deg(torch.atan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = torch.where(dh > 180, dh - 360, torch.where(dh < -180, dh + 360, dh))
    dh = torch.where(C1p * C2p == 0, torch.zeros_like(dh), dh)
    dHp = 2 * torch.sqrt(C1p * C2p) * torch.sin(torch.deg2rad(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hbp = torch.where((h1p - h2p).abs() > 180, torch.where(hs < 360, hs + 360, hs - 360), hs) / 2
    hbp = torch.where(C1p * C2p == 0, hs, hbp)
    T = (1 - 0.17 * torch.cos(torch.deg2rad(hbp - 30)) + 0.24 * torch.cos(torch.deg2rad(2 * hbp))
         + 0.32 * torch.cos(torch.deg2rad(3 * hbp + 6)) - 0.20 * torch.cos(torch.deg2rad(4 * hbp - 63)))
    dtheta = 30 * torch.exp(-(((hbp - 275) / 25) ** 2))
    Cbp7 = Cbp ** 7
    Rc = 2 * torch.sqrt(Cbp7 / (Cbp7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / torch.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -torch.sin(torch.deg2rad(2 * dtheta)) * Rc
    tl, tc, th = dLp / Sl, dCp / Sc, dHp / Sh
    return torch.sqrt((tl * tl + tc * tc + th * th + Rt * tc * th).clamp(min=0))


def curve_diff(L_in, L_ref, L_out, bins=20, min_px=200):
    """Luminance-curve difference: input L* in `bins` bins; per bin |mean L*_out - mean L*_ref|; (mean, max)."""
    idx = (L_in / 100 * bins).long().clamp(0, bins - 1)
    n = torch.bincount(idx, minlength=bins).float()
    sr = torch.bincount(idx, weights=L_ref, minlength=bins)
    so = torch.bincount(idx, weights=L_out, minlength=bins)
    ok = n >= min_px
    if not ok.any():
        return float("nan"), float("nan")
    d = ((so - sr) / n.clamp(min=1))[ok].abs()
    return float(d.mean()), float(d.max())


# ----------------------------------------------------------------------------------------------- tone mirror


class Job:
    """One (slider, value, image): the K-independent parts of _render._tone, subsampled after the base layer."""

    def __init__(self, slider, value, image, code, stem, x_full, ref_full, device):
        self.slider, self.value, self.image, self.code, self.stem = slider, value, image, code, stem
        self.consts = SLIDERS[slider][1]
        self.const = self.consts[0] if len(self.consts) == 1 else ("bl_pos" if value > 0 else "bl_neg")
        x = torch.from_numpy(x_full).permute(2, 0, 1)[None].to(device).clamp(0, 1)
        self.x_full = x
        Y = _color.luma(x).clamp(1e-4, 1)
        v = value / 100
        if slider in ("Highlights2012", "Shadows2012"):
            L = max(x.shape[-2:])
            base = _guided(Y, Y, max(8, L // 24), 1e-2, s=4).clamp(0, 1)
            if slider == "Highlights2012":
                f = _smoothstep(0.45, 1.0, base) * base
            else:
                f = (1 - _smoothstep(0.0, 0.55, base)) * (1 - base) * base.clamp(min=1e-4) ** 0.35
            start = base + (Y - base)        # (base + detail); the K term is added before the clamp
        elif slider == "Whites2012":
            start, f = Y, Y ** 4
        else:
            start, f = Y, (1 - Y).clamp(0, 1) ** 4
        s = STRIDE
        self.x = x[..., ::s, ::s].contiguous()
        self.Y = Y[..., ::s, ::s].contiguous()
        self.start = start[..., ::s, ::s].contiguous()
        self.vf = (v * f)[..., ::s, ::s].contiguous()
        self.L_in = srgb_to_lab(self.x)[0].contiguous()      # only L* is needed (luminance-curve bins)
        ref = torch.from_numpy(ref_full).permute(2, 0, 1)[None].to(device)[..., ::s, ::s]
        self.lab_ref = srgb_to_lab(ref.contiguous())

    def out(self, K):
        """sRGB output (subsampled) of the mirrored tone stage at constant K."""
        Y2 = (self.start + K * self.vf).clamp(0, 1)
        ratio = (Y2 / self.Y).clamp(max=2.0)
        return (self.x * ratio + (Y2 - self.Y * ratio)).clamp(0, 1)

    def de(self, K):
        lab = srgb_to_lab(self.out(K))
        return de2000(self.lab_ref, lab), lab


def _mirror_full(x, slider, value, K):
    Y = _color.luma(x).clamp(1e-4, 1)
    v = value / 100
    if slider in ("Highlights2012", "Shadows2012"):
        L = max(x.shape[-2:])
        base = _guided(Y, Y, max(8, L // 24), 1e-2, s=4).clamp(0, 1)
        if slider == "Highlights2012":
            f = _smoothstep(0.45, 1.0, base) * base
        else:
            f = (1 - _smoothstep(0.0, 0.55, base)) * (1 - base) * base.clamp(min=1e-4) ** 0.35
        Y2 = (base + K * v * f + (Y - base)).clamp(0, 1)
    elif slider == "Whites2012":
        Y2 = (Y + K * v * Y ** 4).clamp(0, 1)
    else:
        Y2 = (Y + K * v * (1 - Y).clamp(0, 1) ** 4).clamp(0, 1)
    ratio = (Y2 / Y).clamp(max=2.0)
    return (x * ratio + (Y2 - Y * ratio)).clamp(0, 1)


def to_np(t):
    return t[0].permute(1, 2, 0).contiguous().cpu().numpy()


# ----------------------------------------------------------------------------------------------- inputs


def read_manifest():
    """[(code, slider, value, stem, [images])] for A02..A05 single-slider sweeps."""
    groups = {g: s for s, (g, _) in SLIDERS.items()}
    rows = []
    with open(MANIFEST, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            g = r["code"].split("-")[0]
            if g not in groups:
                continue
            ch = json.loads(r["changes"])
            slider = groups[g]
            if list(ch) != [slider]:
                continue
            rows.append((r["code"], slider, float(ch[slider]), f"{r['code']}_{r['label']}", r["images"].split()))
    return rows


def preset_path(stem, tier="must"):
    return os.path.join(PRESETS, tier, stem + ".xmp")


def index_lr_dir(d):
    """{(code, image): path}; the newest date prefix wins when the same render is there twice."""
    found = {}
    for name in os.listdir(d):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in (".tif", ".tiff"):
            continue
        m = DATE_PREFIX.match(stem)
        date = m.group(1) if m else ""
        stem = DATE_PREFIX.sub("", stem)
        if "__" not in stem:
            continue
        code, img = stem.split("_", 1)[0], stem.rsplit("__", 1)[-1]
        prev = found.get((code, img))
        if prev is None or date >= prev[0]:
            found[(code, img)] = (date, os.path.join(d, name))
    return {k: v[1] for k, v in found.items()}


def find_base(image, base_dir):
    for d in [base_dir, CHARTS] if base_dir else [CHARTS]:
        if not d:
            continue
        for ext in IMG_EXT:
            p = os.path.join(d, image + ext)
            if os.path.exists(p):
                return p
    return None


# ----------------------------------------------------------------------------------------------- fitting


def objective(jobs, K):
    """Mean over jobs of mean(dE00^2) at constant K."""
    tot = 0.0
    for j in jobs:
        d, _ = j.de(K)
        tot += float((d * d).mean())
    return tot / len(jobs)


def search(jobs, k0):
    """Least-squares 1-D search: coarse grid on [0, SEARCH_HI*k0], then golden section around the best point."""
    hi = SEARCH_HI * k0
    grid = [hi * i / 40 for i in range(41)]
    vals = [objective(jobs, k) for k in grid]
    i = int(np.argmin(vals))
    a, b = grid[max(0, i - 1)], grid[min(40, i + 1)]
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = objective(jobs, c), objective(jobs, d)
    for _ in range(30):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = objective(jobs, c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = objective(jobs, d)
    k = (a + b) / 2
    edge = i == 40 or (i == 0 and k < 1e-6)
    return k, edge


def stats(jobs, K_of):
    """Mean dE00 and mean/max luminance-curve difference over jobs, each job at its own constant K_of(job)."""
    des, cds, cmx = [], [], []
    for j in jobs:
        d, lab = j.de(K_of(j))
        des.append(float(d.mean()))
        cm, cx = curve_diff(j.L_in, j.lab_ref[0], lab[0])
        cds.append(cm)
        cmx.append(cx)
    return float(np.mean(des)), float(np.nanmean(cds)), float(np.nanmax(cmx))


def load_jobs(lr_dir, base_dir, input_mode, device):
    rows = read_manifest()
    lr = index_lr_dir(lr_dir)
    bases, missing, jobs, mirror_err = {}, [], [], 0.0
    baseline = {}
    for (code, img), p in lr.items():
        if code == "A00-01":
            baseline[img] = p

    def base_img(img):
        if img not in bases:
            if input_mode == "lr-baseline" and img in baseline:
                bases[img] = darkroom.read_image(baseline[img])
            else:
                p = find_base(img, base_dir)
                bases[img] = darkroom.read_image(p) if p else None
        return bases[img]

    params_cache = {}
    for code, slider, value, stem, images in rows:
        for img in images:
            ref_p = lr.get((code, img))
            if ref_p is None:
                missing.append(f"{stem}__{img}")
                continue
            x = base_img(img)
            if x is None:
                missing.append(f"{stem}__{img}（缺標準圖 {img}）")
                continue
            ref = darkroom.read_image(ref_p)
            if ref.shape != x.shape:
                missing.append(f"{stem}__{img}（尺寸 {ref.shape[:2]} ≠ 標準圖 {x.shape[:2]}）")
                continue
            j = Job(slider, value, img, code, stem, x, ref, device)
            # the mirror at the current constants must equal the public render of the same preset
            if stem not in params_cache:
                params_cache[stem] = darkroom.load_preset(preset_path(stem))
            pub = darkroom.render(j.x_full, params_cache[stem])
            mine = _mirror_full(j.x_full, slider, value, CURRENT_CONSTS[j.const])
            err = float((pub - mine).abs().max())
            mirror_err = max(mirror_err, err)
            if err > MIRROR_TOL:
                sys.exit(f"tone mirror differs from darkroom.render on {stem}__{img}: max |diff| {err:.2e} > "
                         f"{MIRROR_TOL} — _render._tone changed; update the mirror in tools/fit_calibration.py")
            j.x_full = None          # only the subsampled tensors are kept for the search
            jobs.append(j)
    floor = {}
    for img, p in sorted(baseline.items()):
        x = None
        q = find_base(img, base_dir)
        if q:
            x = darkroom.read_image(q)
        if x is None:
            continue
        r = darkroom.read_image(p)
        if r.shape != x.shape:
            continue
        a = torch.from_numpy(x).permute(2, 0, 1)[None].to(device)[..., ::STRIDE, ::STRIDE].contiguous()
        b = torch.from_numpy(r).permute(2, 0, 1)[None].to(device)[..., ::STRIDE, ::STRIDE].contiguous()
        floor[img] = float(de2000(srgb_to_lab(a), srgb_to_lab(b)).mean())
    return jobs, missing, mirror_err, floor, len(lr)


def fit(jobs):
    """{const: {"shared"/"neg"/"pos": (K, edge)}} and the per-slider before/after numbers."""
    res = {}
    for slider, (_, consts) in SLIDERS.items():
        sj = [j for j in jobs if j.slider == slider]
        if not sj:
            continue
        for c in consts:
            cj = [j for j in sj if j.const == c]
            if not cj:
                continue
            r = {"shared": search(cj, CURRENT_CONSTS[c])}
            if len(consts) == 1:
                for sign, sub in (("neg", [j for j in cj if j.value < 0]), ("pos", [j for j in cj if j.value > 0])):
                    if sub:
                        r[sign] = search(sub, CURRENT_CONSTS[c])
            res[c] = r
    return res


def suggestion(fits, jobs):
    """Suggested constants: the shared fit, except per-sign when that lowers the slider's mean dE by >= 20 %."""
    out, notes = {}, []
    for c, r in fits.items():
        out[c] = r["shared"][0]
        if "neg" in r and "pos" in r:
            cj = [j for j in jobs if j.const == c]
            shared = stats(cj, lambda j: r["shared"][0])[0]
            split = stats(cj, lambda j: r["neg" if j.value < 0 else "pos"][0])[0]
            if split <= 0.8 * shared:
                notes.append(f"`{c}`：正負分開擬合（負 {r['neg'][0]:.4f}／正 {r['pos'][0]:.4f}）平均 ΔE "
                             f"{shared:.2f} → {split:.2f}，建議在 `_render.py` 分成正負兩個常數")
    return out, notes


# ----------------------------------------------------------------------------------------------- report


def report(path, title, meta, jobs, fits, sugg, notes, missing, floor, extra=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    L = [f"# {title}", ""]
    L += [f"- {k}：{v}" for k, v in meta.items()]
    L += ["", "> 只出建議，不改 `darkroom/_render.py`；改常數另開切片。", ""]
    if extra:
        L += extra + [""]
    if floor:
        L += ["## 基準（A00 全歸零：Lightroom 輸出 vs 原圖）", "",
              "這是誤差的下限：滑桿全 0 時 Lightroom 就和原圖差這麼多，擬合後的 ΔE 不會低於它太多。", "",
              "| 標準圖 | 平均 ΔE2000 |", "|---|---|"]
        L += [f"| {k} | {v:.2f} |" for k, v in floor.items()] + [""]
    L += ["## 各滑桿：擬合前後", "",
          "ΔE＝平均 CIEDE2000；亮度曲線差＝依輸入 L* 分 20 格，每格平均 L* 的差（平均／最大，單位 L*）。", "",
          "| 滑桿 | 常數 | 目前 | 建議 | 張數 | ΔE 前 | ΔE 後 | 曲線差 前（最大） | 曲線差 後（最大） |",
          "|---|---|---|---|---|---|---|---|---|"]
    for slider, (_, consts) in SLIDERS.items():
        for c in consts:
            cj = [j for j in jobs if j.const == c]
            if not cj:
                L.append(f"| {slider} | `{c}` | {CURRENT_CONSTS[c]} | — | 0 | — | — | — | — |")
                continue
            b = stats(cj, lambda j: CURRENT_CONSTS[j.const])
            a = stats(cj, lambda j: sugg[j.const])
            L.append(f"| {slider} | `{c}` | {CURRENT_CONSTS[c]} | **{sugg[c]:.4f}** | {len(cj)} | {b[0]:.2f} | "
                     f"{a[0]:.2f} | {b[1]:.2f}（{b[2]:.1f}） | {a[1]:.2f}（{a[2]:.1f}） |")
    L += ["", "## 擬合細節（共用／只用負值／只用正值）", "",
          "| 常數 | 共用 | 負值 | 正值 |", "|---|---|---|---|"]
    for c, r in fits.items():
        def fmt(key):
            if key not in r:
                return "—"
            k, edge = r[key]
            return f"{k:.4f}" + ("（撞到搜尋邊界）" if edge else "")
        L.append(f"| `{c}` | {fmt('shared')} | {fmt('neg')} | {fmt('pos')} |")
    L += ["", "## 每個取值的 ΔE（擬合前 → 後）", "", "| 設定 | 取值 | 張數 | ΔE 前 | ΔE 後 |", "|---|---|---|---|---|"]
    by = {}
    for j in jobs:
        by.setdefault((j.code, j.slider, j.value), []).append(j)
    for (code, slider, value), js in sorted(by.items()):
        b = stats(js, lambda j: CURRENT_CONSTS[j.const])[0]
        a = stats(js, lambda j: sugg[j.const])[0]
        L.append(f"| {code} {slider} | {value:+.0f} | {len(js)} | {b:.2f} | {a:.2f} |")
    L += ["", "## 建議常數", "", "```", *[f"{c} = {sugg[c]:.4f}    # 目前 {CURRENT_CONSTS[c]}；{CONST_DOC[c]}"
                                            for c in sugg], "```", ""]
    if notes:
        L += ["## 提醒", ""] + [f"- {n}" for n in notes] + [""]
    hi = [c for c, r in fits.items() if any(r[k][1] for k in r)]
    if hi:
        L += [f"- 撞到搜尋邊界（0 或 {SEARCH_HI}× 目前值）：{', '.join(hi)}——公式形狀可能不對，不只是常數大小。", ""]
    worst = [c for c in sugg if stats([j for j in jobs if j.const == c], lambda j: sugg[j.const])[0] > 3.0]
    if worst:
        L += [f"- 擬合後平均 ΔE 仍 > 3：{', '.join(worst)}——光調常數不夠，要換曲線形狀（例如影像自適應的區界）。", ""]
    if missing:
        L += [f"## 缺的檔案（{len(missing)}）", ""] + [f"- {m}" for m in missing[:80]]
        if len(missing) > 80:
            L.append(f"- …另有 {len(missing) - 80} 個")
        L.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ----------------------------------------------------------------------------------------------- commands


def run_fit(lr_dir, base_dir, input_mode, report_path, title, device, extra_meta=None, extra=None):
    jobs, missing, mirror_err, floor, n_files = load_jobs(lr_dir, base_dir, input_mode, device)
    if not jobs:
        sys.exit(f"沒有可用的 Lightroom 圖（{lr_dir}）：A02～A05 一張都對不到")
    fits = fit(jobs)
    sugg, notes = suggestion(fits, jobs)
    meta = {"日期": today(), "Lightroom 圖資料夾": lr_dir, "標準圖資料夾": base_dir or "（只用 charts/）",
            "darkroom 的輸入": "原圖" if input_mode == "original" else "Lightroom 的 A00 基準輸出",
            "資料夾裡的 TIFF": n_files, "用到的 (設定, 圖)": len(jobs),
            "鏡像 vs darkroom.render 最大差": f"{mirror_err:.1e}（上限 {MIRROR_TOL}）",
            "取樣": f"每 {STRIDE} 像素取 1（長寬各）", "裝置": str(device)}
    meta.update(extra_meta or {})
    report(report_path, title, meta, jobs, fits, sugg, notes, missing, floor, extra)
    return fits, sugg, jobs


def cmd_fit(a):
    root = localllms_root()
    lr_dir = a.lr_dir or (os.path.join(root, "outputs", "lr-calibration") if root else None)
    base_dir = a.base_dir or (os.path.join(root, "scratch", "lr-calibration", "planB_base") if root else None)
    if not lr_dir or not os.path.isdir(lr_dir):
        sys.exit(f"找不到 Lightroom 匯出資料夾：{lr_dir}（用 --lr-dir 指定，或設 LOCALLLMS_ROOT）")
    rp = a.report or os.path.join(REPO, "outputs", "calibration", f"{today()}-fit-report.md")
    dev = pick_device(a.device)
    fits, sugg, jobs = run_fit(lr_dir, base_dir if base_dir and os.path.isdir(base_dir) else None, a.input, rp,
                               "亮部／陰影／白／黑 常數擬合報告", dev)
    print(f"{len(jobs)} 組 (設定, 圖) 擬合完成")
    for c, k in sugg.items():
        print(f"  {c}: 目前 {CURRENT_CONSTS[c]} -> 建議 {k:.4f}")
    print(f"報告：{rp}")


def cmd_selftest(a):
    dev = pick_device(a.device)
    root = localllms_root()
    base_dir = a.base_dir or (os.path.join(root, "scratch", "lr-calibration", "planB_base") if root else None)
    base_dir = base_dir if base_dir and os.path.isdir(base_dir) else None
    tmp = tempfile.mkdtemp(prefix="fake-lr-")
    date = today()
    rows = read_manifest()
    used, n = set(), 0
    try:
        for code, slider, value, stem, images in rows:
            const = SLIDERS[slider][1][0] if slider != "Blacks2012" else ("bl_pos" if value > 0 else "bl_neg")
            for img in images:
                p = find_base(img, base_dir)
                if p is None:
                    continue
                x = torch.from_numpy(darkroom.read_image(p)).permute(2, 0, 1)[None].to(dev)
                ref = _mirror_full(x, slider, value, TRUE_CONSTS[const])
                if a.noise > 0:          # stand-in for Lightroom's own differences: the fit must not need a perfect match
                    gen = torch.Generator(device=dev).manual_seed(n)
                    ref = (ref + a.noise * torch.randn(ref.shape, generator=gen, device=dev)).clamp(0, 1)
                darkroom.write_image(os.path.join(tmp, f"{date}-{stem}__{img}.tif"), to_np(ref))
                used.add(img)
                n += 1
        if not n:
            sys.exit("selftest 找不到任何標準圖（charts/ 也沒有）")
        rp = a.report or os.path.join(REPO, "outputs", "calibration", f"{date}-selftest-report.md")
        fits, sugg, jobs = run_fit(tmp, base_dir, "original", rp, "擬合流程自我測試（假 Lightroom）", dev,
                                   extra_meta={"假 Lightroom 圖": f"{n} 張，標準圖 {sorted(used)}，加雜訊 σ={a.noise}",
                                               "真常數": json.dumps(TRUE_CONSTS)})
        lines = ["| 常數 | 真常數 | 擬合（共用） | 相對誤差 | 目前值 |", "|---|---|---|---|---|"]
        ok = True
        for c, t in TRUE_CONSTS.items():
            k = sugg.get(c)
            if k is None:
                ok = False
                lines.append(f"| `{c}` | {t} | — | — | {CURRENT_CONSTS[c]} |")
                continue
            e = abs(k - t) / t
            ok &= e <= SELFTEST_TOL
            lines.append(f"| `{c}` | {t} | {k:.4f} | {e * 100:.2f}% | {CURRENT_CONSTS[c]} |")
        with open(rp, "a", encoding="utf-8") as f:
            f.write("\n## 自我測試結果：真常數 vs 擬合常數\n\n" + "\n".join(lines)
                    + f"\n\n判定：{'PASS' if ok else 'FAIL'}（容許相對誤差 {SELFTEST_TOL * 100:.0f}%）\n")
        print("\n".join(lines))
        print(f"selftest {'PASS' if ok else 'FAIL'}；報告：{rp}")
        if a.keep:
            print(f"假 Lightroom 圖留在：{tmp}")
        return 0 if ok else 1
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    global STRIDE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit", help="擬合 Lightroom 匯出的校正集")
    f.add_argument("--lr-dir", help="Lightroom 匯出資料夾（預設 <LocalLLMs>/outputs/lr-calibration）")
    f.add_argument("--base-dir", help="標準圖資料夾（預設 <LocalLLMs>/scratch/lr-calibration/planB_base）")
    f.add_argument("--input", choices=("original", "lr-baseline"), default="original",
                   help="darkroom 的輸入：原圖（預設），或 Lightroom 的 A00 全歸零輸出（抵消 Lightroom 的預設處理）")
    f.add_argument("--report", help="報告路徑（預設 outputs/calibration/<日期>-fit-report.md）")
    f.add_argument("--stride", type=int, default=STRIDE, help=f"取樣間隔（預設 {STRIDE}；GPU 記憶體不夠就用 3 或 4）")
    f.add_argument("--device", default=None)
    s = sub.add_parser("selftest", help="假 Lightroom：用已知常數渲染，確認擬合找得回來")
    s.add_argument("--base-dir", help="標準圖資料夾；沒有就只用 charts/ 的合成圖")
    s.add_argument("--report", help="報告路徑（預設 outputs/calibration/<日期>-selftest-report.md）")
    s.add_argument("--noise", type=float, default=SELFTEST_NOISE,
                   help=f"假 Lightroom 圖加的高斯雜訊標準差（0..1 尺度，預設 {SELFTEST_NOISE}；0＝不加）")
    s.add_argument("--keep", action="store_true", help="保留假 Lightroom 圖")
    s.add_argument("--device", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "fit":
        STRIDE = max(1, a.stride)
        cmd_fit(a)
        return 0
    return cmd_selftest(a)


if __name__ == "__main__":
    sys.exit(main())
