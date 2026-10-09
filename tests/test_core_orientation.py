"""Core patch K2 (CONTRACT-export X6 / XP9): read_image turns JPEG / TIFF upright by EXIF Orientation, exactly once.

The oriented test files hold the very same encoded pixels as their Orientation-1 twin (only the EXIF tag differs),
so the expected result is PIL ImageOps.exif_transpose applied to the twin's pixels - an exact comparison.
"""
import io
import os
import struct
import unittest

import cv2
import numpy as np

import _util
from darkroom import read_image


def exif_segment(orientation, endian=">"):
    """APP1 Exif segment (marker included) holding only Orientation; endian ">" (MM) or "<" (II)."""
    from PIL import Image
    ex = Image.Exif()
    ex.endian = endian
    ex[0x0112] = orientation
    body = ex.tobytes()                      # b"Exif\0\0" + TIFF structure
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def with_exif(jpeg, orientation, endian=">"):
    return jpeg[:2] + exif_segment(orientation, endian) + jpeg[2:]


def asymmetric(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.stack([xx * 255 // max(1, w - 1), yy * 255 // max(1, h - 1), (xx * 7 + yy * 3) % 256], -1)
    img[: h // 4, : w // 3] = (250, 10, 10)          # a red block in the top-left corner
    return img.astype(np.uint8)


def exif_transposed(arr, orientation):
    from PIL import Image, ImageOps
    im = Image.fromarray(arr)
    im.getexif()[0x0112] = orientation               # getexif() is cached on the image
    return np.asarray(ImageOps.exif_transpose(im))


class TestReadImageOrientation(unittest.TestCase):  # K2
    def setUp(self):
        self.tmp = _util.tmpdir(self)

    def write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_read_image_orientation_jpeg_tiff(self):
        import tifffile
        rgb = asymmetric(48, 80)
        ok, enc = cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 95])
        self.assertTrue(ok)
        jpeg = enc.tobytes()
        base = read_image(self.write("o1.jpg", with_exif(jpeg, 1)))       # the decoded pixels, unturned
        np.testing.assert_array_equal(base, read_image(self.write("plain.jpg", jpeg)))
        base8 = np.round(base * 255).astype(np.uint8)
        rgb16 = (rgb.astype(np.uint16) * 257)
        for tag in range(1, 9):
            with self.subTest(fmt="jpeg", orientation=tag):
                out = read_image(self.write(f"o{tag}.jpg", with_exif(jpeg, tag)))
                want = exif_transposed(base8, tag)
                self.assertEqual(out.shape, want.shape)
                np.testing.assert_array_equal(np.round(out * 255).astype(np.uint8), want)
            with self.subTest(fmt="tiff", orientation=tag):
                buf = io.BytesIO()
                tifffile.imwrite(buf, rgb16, photometric="rgb", extratags=[(274, "H", 1, tag, True)])
                out = read_image(self.write(f"o{tag}.tif", buf.getvalue()))
                want = exif_transposed(rgb, tag)
                self.assertEqual(out.shape, want.shape)
                np.testing.assert_array_equal(np.round(out * 65535).astype(np.uint16), want.astype(np.uint16) * 257)
        for tag in range(1, 9):              # seal F6: little-endian (II) EXIF, as most cameras write it
            with self.subTest(fmt="jpeg II", orientation=tag):
                out = read_image(self.write(f"ii{tag}.jpg", with_exif(jpeg, tag, "<")))
                np.testing.assert_array_equal(np.round(out * 255).astype(np.uint8), exif_transposed(base8, tag))
        portrait = read_image(self.write("o6b.jpg", with_exif(jpeg, 6)))
        self.assertEqual(portrait.shape[:2], (80, 48))                   # 6 -> upright portrait
        self.assertTrue(portrait.flags.c_contiguous)
        self.assertEqual(portrait.dtype, np.float32)

    def test_png_is_never_turned(self):  # K2: PNG behaviour unchanged
        rgb = asymmetric(30, 50)
        ok, enc = cv2.imencode(".png", rgb[..., ::-1])
        self.assertTrue(ok)
        out = read_image(self.write("a.png", enc.tobytes()))
        np.testing.assert_array_equal(np.round(out * 255).astype(np.uint8), rgb)

    def test_damaged_exif_reads_unturned(self):
        rgb = asymmetric(20, 30)
        ok, enc = cv2.imencode(".jpg", rgb[..., ::-1])
        jpeg = enc.tobytes()
        broken = jpeg[:2] + b"\xff\xe1\x00\x0cExif\x00\x00II*\x00" + jpeg[2:]   # IFD offset cut off
        out = read_image(self.write("b.jpg", broken))
        self.assertEqual(out.shape, (20, 30, 3))


if __name__ == "__main__":
    unittest.main()
