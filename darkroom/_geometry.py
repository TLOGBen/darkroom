"""Geometry of a photo: rotate, flip, straighten and crop (CONTRACT-s3-crop C1-C5, C9).

One rule, shared with the page (tests/cases/s3_geometry_cases.json): the object and its checks (`from_dict`), the
crop box resolved inside the picture (`resolve`), the inverse map from an output pixel to the source (`matrix`) and
the CPU application (`apply`, numpy + cv2). Only numpy and math are imported here; cv2 is imported lazily by
`apply`, and torch never (the GPU sampling lives in darkroom._render), so the edit and thumbnail commands stay light.

Order (C2): source (upright W x H) -> rotate (clockwise) -> flip (horizontal) -> angle (about the frame centre,
the canvas W' x H' keeps its size) -> crop. Coordinates use the pixel-centre convention: pixel (i, j) covers
[i, i + 1) x [j, j + 1) and its centre is (i + 0.5, j + 0.5).
"""
import math

import numpy as np

KEYS = ("rotate", "flip", "angle", "aspect", "crop")            # verbatim order (C1 geometry schema)
CROP_KEYS = ("left", "top", "right", "bottom")
ROTATIONS = (0, 90, 180, 270)
ANGLE_MAX = 45.0
ASPECT_MAX = 65535
RATIO_TOL = 0.001                                                 # verbatim (C3 step 2)

# verbatim (C1 / constants "invalid")
NOT_OBJECT = "幾何要是物件或 null：{geometry}"
UNKNOWN_KEY = "幾何設定不認得的鍵：{key}（可用 rotate、flip、angle、aspect、crop）"
BAD_ROTATE = "rotate 要是 0、90、180、270 其中之一：{rotate}"
BAD_FLIP = "flip 必須是 true 或 false"
BAD_ANGLE = "拉直角度要在 -45～45 度之間：{angle}"
BAD_ASPECT = "不支援的裁切比例：{aspect}（可用 original、free，或「寬:高」兩個 1～65535 的整數）"
BAD_CROP = ('裁切框要是 {{"left","top","right","bottom"}}，而且 0 ≤ left < right ≤ 1、0 ≤ top < bottom ≤ 1：'
            '{crop}')


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _tidy(v):
    """A number as JSON writes it on both sides: an integral float becomes an int (1.0 -> 1)."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def show(v):
    """The value inside an error sentence, the same for every interface: text as it is, the rest as JSON with
    integral numbers written without '.0' (the CLI's 46.0 and the page's 46 read the same)."""
    import json
    if isinstance(v, str):
        return v

    def tidy(x):
        if isinstance(x, dict):
            return {str(k): tidy(y) for k, y in x.items()}
        if isinstance(x, (list, tuple)):
            return [tidy(y) for y in x]
        if isinstance(x, float) and math.isfinite(x):
            return _tidy(x)
        return x
    try:
        return json.dumps(tidy(v), ensure_ascii=False, separators=(", ", ": "))
    except (TypeError, ValueError):
        return str(v)


def _aspect(v):
    if not isinstance(v, str):
        raise ValueError(BAD_ASPECT.format(aspect=show(v)))
    if v in ("original", "free"):
        return v
    w, sep, h = v.partition(":")
    if not sep or not w.isdecimal() or not h.isdecimal() or not w.isascii() or not h.isascii():
        raise ValueError(BAD_ASPECT.format(aspect=v))
    a, b = int(w), int(h)
    if not (1 <= a <= ASPECT_MAX and 1 <= b <= ASPECT_MAX):
        raise ValueError(BAD_ASPECT.format(aspect=v))
    g = math.gcd(a, b)
    return f"{a // g}:{b // g}"


def _crop(v):
    if v is None:
        return None
    ok = isinstance(v, dict) and set(v) == set(CROP_KEYS) and all(_num(v[k]) for k in CROP_KEYS)
    if ok:
        l, t, r, b = (float(v[k]) for k in CROP_KEYS)
        ok = 0.0 <= l < r <= 1.0 and 0.0 <= t < b <= 1.0
    if not ok:
        raise ValueError(BAD_CROP.format(crop=show(v)))
    return (l, t, r, b)


def _rot(phi, v):
    """Rot(phi) v with y pointing down (positive phi = clockwise on screen)."""
    c, s = math.cos(phi), math.sin(phi)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


class Geometry:
    """rotate (0/90/180/270, clockwise), flip (horizontal, after rotate), angle (-45..45 degrees, positive turns the
    picture clockwise), aspect ("original" | "free" | "w:h", reduced), crop (None = automatic, or the normalised box
    (left, top, right, bottom) of the frame W' x H'). Build it with from_dict; identity -> to_dict() is None."""

    __slots__ = ("rotate", "flip", "angle", "aspect", "crop", "_bind")

    def __init__(self, rotate=0, flip=False, angle=0.0, aspect="original", crop=None):
        self.rotate, self.flip, self.angle, self.aspect = int(rotate), bool(flip), float(angle), aspect
        self.crop = None if crop is None else tuple(float(x) for x in crop)
        self._bind = None

    # ------------------------------------------------------------------ the object (C1)
    @classmethod
    def from_dict(cls, obj):
        """None -> None; a geometry object -> Geometry; anything else -> ValueError with the constant sentence.
        A key that is missing takes its identity value (rotate 0, flip false, angle 0, aspect original, crop null)."""
        if obj is None:
            return None
        if not isinstance(obj, dict):
            raise ValueError(NOT_OBJECT.format(geometry=show(obj)))
        for k in obj:
            if k not in KEYS:
                raise ValueError(UNKNOWN_KEY.format(key=k))
        rotate = obj.get("rotate", 0)
        if not _num(rotate) or rotate not in ROTATIONS:
            raise ValueError(BAD_ROTATE.format(rotate=show(rotate)))
        flip = obj.get("flip", False)
        if not isinstance(flip, bool):
            raise ValueError(BAD_FLIP)
        angle = obj.get("angle", 0)
        if not _num(angle) or not -ANGLE_MAX <= angle <= ANGLE_MAX:
            raise ValueError(BAD_ANGLE.format(angle=show(angle)))
        aspect = _aspect(obj.get("aspect", "original"))
        crop = _crop(obj.get("crop"))
        return cls(int(rotate), flip, float(angle), aspect, crop)

    @property
    def identity(self):
        return self.rotate == 0 and not self.flip and self.angle == 0 and self.crop is None

    def to_dict(self):
        """The normalised object (keys in the schema's order), or None for the identity (aspect alone is nothing)."""
        if self.identity:
            return None
        crop = None if self.crop is None else {k: _tidy(v) for k, v in zip(CROP_KEYS, self.crop)}
        return {"rotate": self.rotate, "flip": self.flip, "angle": _tidy(self.angle), "aspect": self.aspect,
                "crop": crop}

    def __eq__(self, other):
        return isinstance(other, Geometry) and self.to_dict() == other.to_dict()

    def __hash__(self):
        return hash(repr(self.to_dict()))

    def __repr__(self):
        return f"Geometry({self.to_dict()!r})"

    def bound(self, width, height, out_width, out_height, frame=False):
        """This geometry resolved on a width x height source, sampled into out_width x out_height pixels from an
        image of any size with the source's aspect ratio (a preview's base image); frame=True keeps the whole
        straightened frame W' x H' (the crop mode, C9) and fills what lies outside the picture with black."""
        g = Geometry(self.rotate, self.flip, self.angle, self.aspect, self.crop)
        g._bind = (int(width), int(height), int(out_width), int(out_height), bool(frame))
        return g

    # ------------------------------------------------------------------ the crop box (C3)
    def frame_size(self, width, height):
        return (height, width) if self.rotate in (90, 270) else (width, height)

    def ratio(self, width, height):
        fw, fh = self.frame_size(width, height)
        if self.aspect in ("original", "free"):
            return fw / fh
        a, b = self.aspect.split(":")
        return int(a) / int(b)

    def _limits(self, m, e, fw, fh):
        """Largest s >= 0 with the box m +- s*e inside the canvas and inside the straightened picture."""
        th = math.radians(self.angle)
        cx, cy = fw / 2.0, fh / 2.0
        d = (m[0] - cx, m[1] - cy)
        a = _rot(-th, d)
        best = math.inf
        for sx in (1.0, -1.0):
            for sy in (1.0, -1.0):
                ek = (sx * e[0], sy * e[1])
                bk = _rot(-th, ek)
                for val, half, pos in ((bk[0], cx, a[0]), (bk[1], cy, a[1]), (ek[0], cx, d[0]), (ek[1], cy, d[1])):
                    if val != 0:
                        best = min(best, (half - math.copysign(1.0, val) * pos) / abs(val))
        return max(0.0, best)

    def _inside(self, m, fw, fh):
        a = _rot(-math.radians(self.angle), (m[0] - fw / 2.0, m[1] - fh / 2.0))
        return abs(a[0]) <= fw / 2.0 and abs(a[1]) <= fh / 2.0

    def resolve(self, width, height):
        """C3: {"left", "top", "right", "bottom" (frame pixels, int), "width", "height" (output size), "box" (the
        normalised box after step 4, before rounding)}."""
        fw, fh = self.frame_size(width, height)
        rho = self.ratio(width, height)
        if self.crop is None:                                                    # (1) the largest centred box
            m = (fw / 2.0, fh / 2.0)
            e = (rho / 2.0, 0.5)
            s = self._limits(m, e, fw, fh)
            hw, hh = s * e[0], s * e[1]
        else:
            l, t, r, b = self.crop
            m = ((l + r) / 2.0 * fw, (t + b) / 2.0 * fh)
            w, h = (r - l) * fw, (b - t) * fh
            if self.aspect != "free" and abs(w / h - rho) / rho > RATIO_TOL:      # (2) same centre and area, ratio rho
                area = w * h
                w, h = math.sqrt(area * rho), math.sqrt(area / rho)
            if not self._inside(m, fw, fh):                                      # (3) back to the centre
                m = (fw / 2.0, fh / 2.0)
            s = min(1.0, self._limits(m, (w / 2.0, h / 2.0), fw, fh))            # (4) shrink only, never enlarge
            hw, hh = s * w / 2.0, s * h / 2.0
        x0, y0, x1, y1 = m[0] - hw, m[1] - hh, m[0] + hw, m[1] + hh
        box = (x0 / fw, y0 / fh, x1 / fw, y1 / fh)
        L, T = math.floor(x0 + 0.5), math.floor(y0 + 0.5)                       # (5) whole pixels, at least 1 x 1
        R, B = math.floor(x1 + 0.5), math.floor(y1 + 0.5)
        L, T = min(max(L, 0), fw - 1), min(max(T, 0), fh - 1)
        R, B = min(max(R, L + 1), fw), min(max(B, T + 1), fh)
        return {"left": L, "top": T, "right": R, "bottom": B, "width": R - L, "height": B - T, "box": box}

    def output_size(self, width, height):
        r = self.resolve(width, height)
        return r["width"], r["height"]

    # ------------------------------------------------------------------ the inverse map (C2)
    def sampling(self, img_width, img_height):
        """(source width, source height, out width, out height, frame, rect, exact): how render samples this
        geometry from an img_width x img_height image. rect = (L, T, R, B) in frame pixels of the source."""
        if self._bind is None:
            W, H, frame = img_width, img_height, False
        else:
            W, H, ow, oh, frame = self._bind
        fw, fh = self.frame_size(W, H)
        if frame:
            rect = (0, 0, fw, fh)
        else:
            r = self.resolve(W, H)
            rect = (r["left"], r["top"], r["right"], r["bottom"])
        if self._bind is None:
            ow, oh = rect[2] - rect[0], rect[3] - rect[1]
        exact = (self.angle == 0 and (img_width, img_height) == (W, H)
                 and (ow, oh) == (rect[2] - rect[0], rect[3] - rect[1]))
        return W, H, ow, oh, frame, rect, exact

    def matrix(self, img_width, img_height):
        """2x3 float64 map from an output point (X, Y) (pixel centres at i + 0.5) to the image point (x, y) in the
        same convention (C2 constant "inverse map"), for an img_width x img_height image of the source."""
        W, H, ow, oh, frame, (L, T, R, B), _ = self.sampling(img_width, img_height)
        fw, fh = self.frame_size(W, H)
        M = np.array([[(R - L) / ow, 0.0, L], [0.0, (B - T) / oh, T], [0.0, 0.0, 1.0]])   # output -> frame point p
        th = math.radians(self.angle)
        c, s = math.cos(th), math.sin(th)
        cx, cy = fw / 2.0, fh / 2.0
        rot = np.array([[c, s, cx - c * cx - s * cy], [-s, c, cy + s * cx - c * cy], [0.0, 0.0, 1.0]])   # Rot(-angle)
        M = rot @ M
        if self.flip:
            M = np.array([[-1.0, 0.0, fw], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]) @ M
        if self.rotate == 90:
            un = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, H], [0.0, 0.0, 1.0]])
        elif self.rotate == 180:
            un = np.array([[-1.0, 0.0, W], [0.0, -1.0, H], [0.0, 0.0, 1.0]])
        elif self.rotate == 270:
            un = np.array([[0.0, -1.0, W], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        else:
            un = np.eye(3)
        M = un @ M
        M = np.array([[img_width / W, 0.0, 0.0], [0.0, img_height / H, 0.0], [0.0, 0.0, 1.0]]) @ M
        return M[:2]

    # ------------------------------------------------------------------ CPU (C9): thumbnails
    def apply(self, array):
        """This geometry applied to an HxW(xC) numpy array resolved at its own size (or as bound): angle 0 ->
        rot90 / flip / slice only (byte for byte), else cv2.warpAffine (INTER_CUBIC, BORDER_REPLICATE; frame mode:
        black outside the picture). Never enlarges."""
        a = np.asarray(array)
        h, w = a.shape[:2]
        W, H, ow, oh, frame, (L, T, R, B), exact = self.sampling(w, h)
        if exact:
            out = np.rot90(a, k=-(self.rotate // 90)) if self.rotate else a
            if self.flip:
                out = out[:, ::-1]
            return np.ascontiguousarray(out[T:B, L:R])
        import cv2
        M = self.matrix(w, h)
        Mcv = M.copy()                                                    # pixel centres -> pixel indices
        Mcv[:, 2] = M[:, 2] + 0.5 * (M[:, 0] + M[:, 1]) - 0.5
        border = cv2.BORDER_CONSTANT if frame else cv2.BORDER_REPLICATE
        out = cv2.warpAffine(np.ascontiguousarray(a), Mcv, (ow, oh), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                             borderMode=border, borderValue=0)
        if out.ndim == 2 and a.ndim == 3:
            out = out[..., None]
        if np.issubdtype(a.dtype, np.floating):
            out = np.clip(out, 0.0, 1.0)
        return out
