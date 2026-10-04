"""Write synthetic HEIC files for tests (pillow-heif encoder, lossless: quality=-1, 4:4:4, RGB matrix 0)."""
import numpy as np

# Published D65 matrices (linear RGB -> XYZ). Used to make the expected values independently of darkroom._icc.
P3_TO_XYZ = np.array([[0.4865709, 0.2656677, 0.1982173],
                      [0.2289746, 0.6917385, 0.0792869],
                      [0.0000000, 0.0451134, 1.0439444]])
SRGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]])


def srgb_decode(v):
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def srgb_encode(v):
    v = np.clip(np.asarray(v, dtype=np.float64), 0, 1)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055)


def srgb_to_p3(img):
    """sRGB-encoded -> Display P3-encoded (same sRGB tone curve), via XYZ D65."""
    lin = srgb_decode(img)
    p3 = lin @ (np.linalg.inv(P3_TO_XYZ) @ SRGB_TO_XYZ).T
    return srgb_encode(p3)


def pattern(h=96, w=128, lo=0.05, hi=0.95, seed=1):
    """Smooth gradients plus a block of random colours, all inside lo..hi (inside the sRGB gamut)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    img = np.stack([xx / (w - 1), yy / (h - 1), 0.5 + 0.5 * np.sin(xx / 9.0) * np.cos(yy / 7.0)], -1)
    rng = np.random.default_rng(seed)
    img[h // 2:, : w // 2] = rng.random((h - h // 2, w // 2, 3))
    return lo + (hi - lo) * img


def ramp_10bit(w=1024, h=8):
    """Every 10-bit level once per row in R, as a float image."""
    r = np.tile(np.arange(w) / 1023.0, (h, 1))
    return np.stack([r, r[:, ::-1], np.full_like(r, 0.5)], -1)


def write_heic(path, img, bits=8, icc=None, orientation=None, thumbnail=False, second_image=None):
    """img: HxWx3 float 0..1 (already in the target colour space). bits 8 or 10."""
    import pillow_heif
    from PIL import Image
    h, w = img.shape[:2]
    if bits == 8:
        data = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
        hf = pillow_heif.from_bytes(mode="RGB", size=(w, h), data=data.tobytes())
    else:
        data = ((np.clip(img, 0, 1) * 1023 + 0.5).astype(np.uint16) << 6)   # 10-bit values in 16-bit container
        hf = pillow_heif.from_bytes(mode="RGB;16", size=(w, h), data=data.tobytes())
    if second_image is not None:
        s = (np.clip(second_image, 0, 1) * 255 + 0.5).astype(np.uint8)
        hf.add_frombytes(mode="RGB", size=(s.shape[1], s.shape[0]), data=s.tobytes())
    if thumbnail:
        hf.info["thumbnails"] = [32]
    kw = {"quality": -1, "chroma": 444, "matrix_coefficients": 0}
    if icc is not None:
        kw["icc_profile"] = icc
    if orientation is not None:
        ex = Image.Exif()
        ex[0x0112] = orientation
        kw["exif"] = ex.tobytes()
    hf.save(path, **kw)
    return path


def write_png16(path, img):
    import cv2
    data = (np.clip(img, 0, 1)[..., ::-1] * 65535 + 0.5).astype(np.uint16)
    ok, buf = cv2.imencode(".png", data)
    assert ok
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return path


def write_png8(path, img):
    import cv2
    data = (np.clip(img, 0, 1)[..., ::-1] * 255 + 0.5).astype(np.uint8)
    ok, buf = cv2.imencode(".png", data)
    assert ok
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return path


def write_heic_nclx(path, img, primaries=12, transfer=13, bits=8):
    """HEIC that describes its colours only with nclx (no ICC): e.g. Display P3 = primaries 12, transfer 13."""
    import pillow_heif
    h, w = img.shape[:2]
    if bits == 8:
        data = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
        hf = pillow_heif.from_bytes(mode="RGB", size=(w, h), data=data.tobytes())
    else:
        data = ((np.clip(img, 0, 1) * 1023 + 0.5).astype(np.uint16) << 6)
        hf = pillow_heif.from_bytes(mode="RGB;16", size=(w, h), data=data.tobytes())
    hf.save(path, quality=-1, chroma=444, matrix_coefficients=0, color_primaries=primaries,
            transfer_characteristics=transfer)
    return path
