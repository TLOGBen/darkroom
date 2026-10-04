"""Shared helpers: photo regions, loading, alignment / similarity metrics, panel drawing."""
import json, os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.metrics import structural_similarity

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
QW = os.path.join(ROOT, "outputs", "comfyui", "qw")

# boxes in original-photo pixels (x0, y0, x1, y1). "face" = face (portraits) or main subject (others).
REGIONS = {
    "portrait_laughing": {"face": (330, 380, 1010, 1260), "eyes": (380, 700, 920, 880), "hair": (180, 250, 560, 630), "teeth": (520, 1040, 840, 1220)},
    "portrait_oldman": {"face": (420, 120, 940, 800), "eyes": (520, 260, 900, 420), "hair": (250, 0, 650, 350), "mouth": (560, 560, 900, 760)},
    "portrait_studio": {"face": (60, 130, 390, 470), "eye": (90, 220, 260, 420), "hair": (0, 0, 300, 240), "zip": (330, 380, 560, 560)},
    "landscape_lighthouse": {"face": (640, 180, 820, 380), "tower": (660, 190, 800, 380), "waves": (0, 520, 300, 768), "rock": (900, 450, 1200, 650)},
    "fog_karst": {"face": (480, 290, 830, 680), "crag": (600, 300, 830, 550), "fog": (950, 120, 1280, 360), "fields": (850, 430, 1150, 560)},
}


def photos():
    return json.load(open(os.path.join(HERE, "photos.json"), encoding="utf-8"))


def load(path):
    return np.asarray(Image.open(path).convert("RGB"))


def resize_to(img, w, h):
    return np.asarray(Image.fromarray(img).resize((w, h), Image.LANCZOS))


def gray(x):
    return cv2.cvtColor(x, cv2.COLOR_RGB2GRAY)


def crop(x, b):
    return x[b[1]:b[3], b[0]:b[2]]


def ssim(a, b):
    return float(structural_similarity(a, b, channel_axis=2, data_range=255))


def mae(a, b):
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean())


def phase_shift(a, b):
    ga, gb = gray(a).astype(np.float32), gray(b).astype(np.float32)
    win = cv2.createHanningWindow(ga.shape[::-1], cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(ga, gb, win)
    return float(dx), float(dy), float(resp)


def flow(a, b):
    """Dense Farneback flow a->b (px). Returns HxWx2."""
    return cv2.calcOpticalFlowFarneback(gray(a), gray(b), None, 0.5, 5, 21, 5, 7, 1.5, 0)


def flow_stats(fl, box=None):
    m = np.linalg.norm(fl, axis=2)
    if box is not None:
        m = crop(m, box)
    return {"p50": float(np.percentile(m, 50)), "p95": float(np.percentile(m, 95)), "p99": float(np.percentile(m, 99))}


def warp(img, fl):
    h, w = fl.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(img, gx + fl[..., 0], gy + fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def edges(x):
    return cv2.Canny(cv2.GaussianBlur(gray(x), (3, 3), 0), 60, 150) > 0


def edge_match(ref, test, tol=1.5):
    """Share of test edges within tol px of ref edges, and vice versa (symmetric -> F1)."""
    er, et = edges(ref), edges(test)
    dr = cv2.distanceTransform((~er).astype(np.uint8), cv2.DIST_L2, 3)
    dt = cv2.distanceTransform((~et).astype(np.uint8), cv2.DIST_L2, 3)
    prec = float((dr[et] <= tol).mean()) if et.any() else 0.0
    rec = float((dt[er] <= tol).mean()) if er.any() else 0.0
    return 2 * prec * rec / (prec + rec + 1e-9)


try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 22)
except OSError:
    FONT = ImageFont.load_default()


def panel(images, labels, height=480, pad=6):
    ims = []
    for im in images:
        h, w = im.shape[:2]
        ims.append(Image.fromarray(im).resize((max(1, round(w * height / h)), height), Image.LANCZOS))
    W = sum(i.width for i in ims) + pad * (len(ims) + 1)
    out = Image.new("RGB", (W, height + 34 + pad), (24, 24, 24))
    d = ImageDraw.Draw(out)
    x = pad
    for i, lab in zip(ims, labels):
        out.paste(i, (x, 34))
        d.text((x + 4, 6), lab, fill=(240, 240, 240), font=FONT)
        x += i.width + pad
    return out


def stack(panels, pad=0, width=None):
    W = width or max(p.width for p in panels)
    panels = [p.resize((W, round(p.height * W / p.width)), Image.LANCZOS) if p.width != W else p for p in panels]
    out = Image.new("RGB", (W, sum(p.height for p in panels) + pad * len(panels)), (24, 24, 24))
    y = 0
    for p in panels:
        out.paste(p, (0, y))
        y += p.height + pad
    return out


def tile_shifts(ref, test):
    """Template-match a 4x4 grid of tiles (each 1/6 of the image) from ref inside test.
    Returns median dx, dy (px, + = content moved right/down in test), the per-tile list, and horizontal / vertical
    scale estimates from the slope of dx vs x and dy vs y (1.0 = no scaling)."""
    gr, gt = gray(ref).astype(np.float32), gray(test).astype(np.float32)
    H, W = gr.shape
    th, tw = H // 6, W // 6
    out = []
    for fy in (0.1, 0.35, 0.55, 0.75):
        for fx in (0.1, 0.35, 0.55, 0.75):
            y, x = int(H * fy), int(W * fx)
            t = gr[y:y + th, x:x + tw]
            if t.std() < 4:
                continue  # flat tile, unreliable
            m = 40
            y0, x0 = max(0, y - m), max(0, x - m)
            win = gt[y0:min(H, y + th + m), x0:min(W, x + tw + m)]
            r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if mx > 0.6:
                out.append((x + tw / 2, y + th / 2, x0 + loc[0] - x, y0 + loc[1] - y, mx))
    if len(out) < 3:
        return dict(dx=None, dy=None, sx=None, sy=None, n=len(out))
    a = np.array(out)
    sx = np.polyfit(a[:, 0], a[:, 2], 1)[0] + 1 if np.ptp(a[:, 0]) > 0 else 1.0
    sy = np.polyfit(a[:, 1], a[:, 3], 1)[0] + 1 if np.ptp(a[:, 1]) > 0 else 1.0
    return dict(dx=float(np.median(a[:, 2])), dy=float(np.median(a[:, 3])), sx=float(sx), sy=float(sy), n=len(out),
                dx_range=(float(a[:, 2].min()), float(a[:, 2].max())))


def ecc_align(ref, test):
    """Affine ECC alignment of test onto ref (on a half-size copy). Returns aligned test and the 2x3 matrix (full res)."""
    s = 0.5
    gr = cv2.resize(gray(ref), None, fx=s, fy=s).astype(np.float32) / 255
    gt = cv2.resize(gray(test), None, fx=s, fy=s).astype(np.float32) / 255
    M = np.eye(2, 3, dtype=np.float32)
    try:
        _, M = cv2.findTransformECC(gr, gt, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    except cv2.error:
        pass
    M[:, 2] /= s
    H, W = ref.shape[:2]
    out = cv2.warpAffine(test, M, (W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    return out, M
