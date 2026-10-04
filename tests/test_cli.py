"""CLI and IO: A3, A4, A13, A16 plus message formats."""
import os
import re
import shutil
import unittest

import numpy as np

import _util
import _xmpgen
from darkroom import load_preset

# Verbatim from the contract.
MSG_OK = "已套用：{preset_name}（強度 {strength}%）→ {output_path}"
MSG_SKIP = "略過：{skipped_items_joined_by_、}"
MSG_SCAN = "已解析 {ok}／{total}，不支援 {unsupported}，失敗 {failed}"
MSG_PV = "不支援的 preset 版本：ProcessVersion {pv}（{file_name}）"
MSG_EXISTS = "輸出檔已存在或與輸入相同：{output_path}（要覆寫請加 --overwrite）"


def preset_name(path):
    m = re.search(r"<crs:Name>.*?<rdf:li[^>]*>([^<]*)</rdf:li>", _util.read_text(path), re.S)
    return m.group(1).strip()


def small_photo(d, name="in.png"):
    src = os.path.join(_util.PHOTOS, "food_breakfast.jpg")
    from PIL import Image
    im = Image.open(src).convert("RGB")
    im.thumbnail((256, 256))
    p = os.path.join(d, name)
    im.save(p)
    return p


class TestScan(unittest.TestCase):
    def test_scan_exact_line(self):  # A3
        rc, out, err = _util.run_cli("scan", _util.preset_dir())
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines(), [MSG_SCAN.format(ok=1466, total=1466, unsupported=0, failed=0)])

    def test_scan_counts_failures(self):
        d = _util.tmpdir(self)
        _xmpgen.write(d, "a.xmp", _xmpgen.xmp_text({"Contrast2012": "+10"}))
        _xmpgen.write(d, "b.xmp", _xmpgen.xmp_text({"ProcessVersion": "5.7"}))
        _xmpgen.write(d, "c.xmp", _xmpgen.xmp_text({"Contrast2012": "oops"}))
        rc, out, err = _util.run_cli("scan", d)
        self.assertEqual(out.splitlines(), [MSG_SCAN.format(ok=1, total=3, unsupported=1, failed=1)])


class TestAnyDirectory(unittest.TestCase):  # A21
    def test_module_runs_from_other_directories(self):
        for cwd in (os.path.abspath(os.sep), _util.tmpdir(self)):
            rc, out, err = _util.run_cli("scan", _util.preset_dir(), cwd=cwd)
            self.assertEqual(rc, 0, (cwd, err))
            self.assertEqual(out.splitlines(), [MSG_SCAN.format(ok=1466, total=1466, unsupported=0, failed=0)])


class TestApply(unittest.TestCase):
    def test_cli_messages_exact(self):
        d = _util.tmpdir(self)
        src = small_photo(d)
        preset = _util.find_preset(r"<crs:Look>", exclude=r'ProcessVersion="6\.7"')
        out_path = os.path.join(d, "out.png")
        rc, out, err = _util.run_cli("apply", "--preset", preset, "--strength", "50", src, out_path)
        self.assertEqual(rc, 0, err)
        skipped = load_preset(preset).skipped
        self.assertTrue(skipped)
        self.assertEqual(out.splitlines(), [
            MSG_OK.format(preset_name=preset_name(preset), strength="50", output_path=out_path),
            MSG_SKIP.replace("{skipped_items_joined_by_、}", "、".join(skipped))])
        self.assertTrue(os.path.exists(out_path))
        # default strength is 100 and a preset without skipped items prints only the success line
        clean = _xmpgen.write(d, "clean.xmp", _xmpgen.xmp_text({"Exposure2012": "+0.30"}, name="乾淨"))
        out2 = os.path.join(d, "out2.jpg")
        rc, out, err = _util.run_cli("apply", "--preset", clean, src, out2)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines(), [MSG_OK.format(preset_name="乾淨", strength="100", output_path=out2)])

    def test_apply_unsupported_version(self):  # A4
        d = _util.tmpdir(self)
        src = small_photo(d)
        preset = _xmpgen.write(d, "pv2010.xmp", _xmpgen.xmp_text({"ProcessVersion": "5.7", "FillLight": "20"}))
        out_path = os.path.join(d, "out.png")
        rc, out, err = _util.run_cli("apply", "--preset", preset, src, out_path)
        self.assertEqual(rc, 2)
        self.assertIn(MSG_PV.format(pv="5.7", file_name=os.path.basename(preset)), err.splitlines())
        self.assertFalse(os.path.exists(out_path))

    def test_apply_refuses_overwrite(self):  # A16
        d = _util.tmpdir(self)
        src = small_photo(d)
        with open(src, "rb") as f:
            original = f.read()
        preset = _xmpgen.write(d, "p.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}))
        # same path as input -> refused even with --overwrite
        for extra in ([], ["--overwrite"]):
            rc, out, err = _util.run_cli("apply", "--preset", preset, *extra, src, src)
            self.assertEqual(rc, 2)
            self.assertIn(MSG_EXISTS.format(output_path=src), err.splitlines())
            with open(src, "rb") as f:
                self.assertEqual(f.read(), original)
        # existing output without --overwrite -> refused, untouched
        existing = os.path.join(d, "exists.png")
        shutil.copy(src, existing)
        rc, out, err = _util.run_cli("apply", "--preset", preset, src, existing)
        self.assertEqual(rc, 2)
        self.assertIn(MSG_EXISTS.format(output_path=existing), err.splitlines())
        with open(existing, "rb") as f:
            self.assertEqual(f.read(), original)
        # with --overwrite -> written
        rc, out, err = _util.run_cli("apply", "--preset", preset, "--overwrite", src, existing)
        self.assertEqual(rc, 0, err)
        with open(existing, "rb") as f:
            self.assertNotEqual(f.read(), original)

    def test_apply_bad_strength(self):
        d = _util.tmpdir(self)
        src = small_photo(d)
        preset = _xmpgen.write(d, "p.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}))
        out_path = os.path.join(d, "o.png")
        rc, out, err = _util.run_cli("apply", "--preset", preset, "--strength", "250", src, out_path)
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(out_path))


class TestIO(unittest.TestCase):
    def test_roundtrip_formats(self):
        from darkroom import _io
        d = _util.tmpdir(self)
        rng = np.random.default_rng(0)
        img = rng.random((40, 60, 3), dtype=np.float32)
        for ext, tol in ((".png", 1 / 65535), (".tif", 1 / 65535), (".jpg", 0.2)):
            p = os.path.join(d, "x" + ext)
            _io.write_image(p, img)
            back = _io.read_image(p)
            self.assertEqual(back.shape, img.shape)
            self.assertEqual(back.dtype, np.float32)
            err = np.abs(back - img)
            self.assertLessEqual(float(err.max() if ext != ".jpg" else err.mean()), tol, ext)

    def test_reads_8_and_16_bit(self):
        import cv2
        from darkroom import _io
        d = _util.tmpdir(self)
        a8 = np.zeros((4, 4, 3), np.uint8); a8[..., 2] = 255          # BGR: red
        a16 = np.zeros((4, 4, 3), np.uint16); a16[..., 0] = 65535     # BGR: blue
        for name, arr in (("r8.png", a8), ("b16.png", a16), ("r8.tif", a8), ("b16.tif", a16), ("g.jpg", a8)):
            p = os.path.join(d, name)
            cv2.imwrite(p, arr)
            x = _io.read_image(p)
            ch = 0 if name.startswith("r") or name.startswith("g") else 2
            self.assertGreater(x[..., ch].mean(), 0.9, name)
            self.assertLess(x[..., (ch + 1) % 3].mean(), 0.1, name)

    def test_unicode_path(self):
        from darkroom import _io
        d = os.path.join(_util.tmpdir(self), "照片")
        os.makedirs(d)
        p = os.path.join(d, "測試.png")
        _io.write_image(p, np.full((8, 8, 3), 0.5, np.float32))
        self.assertAlmostEqual(float(_io.read_image(p).mean()), 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
