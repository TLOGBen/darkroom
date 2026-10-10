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
MSG_STRENGTH = "強度要在 0～200 之間：{strength}"
MSG_PRESET = "preset 讀取失敗：{file_name}：{reason}"
MSG_PHOTO = "照片讀取失敗：{input_path}：{reason}"
MSG_FORMAT = "不支援的輸出格式：{ext}（可用 .png、.tif、.tiff 16-bit 或 .jpg 8-bit）"
MSG_NODIR = "找不到資料夾：{preset_dir}"
MSG_SCAN_FAIL = "解析失敗：{file_name}：{reason}"
MSG_STRENGTH_CLAMP = "{key}（強度後超出範圍，已夾值）"


def line_pattern(template, **kw):
    """Exact line from a contract template; {reason} (free text from the error) may be any non-empty text."""
    filled = template.format(reason="\x00", **kw)
    return "^" + re.escape(filled).replace("\x00", ".+") + "$"


def assert_line(tc, template, text, **kw):
    pat = line_pattern(template, **kw)
    tc.assertTrue(any(re.match(pat, ln) for ln in text.splitlines()), (pat, text))


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
        self.assertEqual(out.splitlines(), [MSG_SCAN.format(ok=_util.LIBRARY_SIZE, total=_util.LIBRARY_SIZE, unsupported=0, failed=0)])

    def test_scan_counts_failures(self):
        d = _util.tmpdir(self)
        _xmpgen.write(d, "a.xmp", _xmpgen.xmp_text({"Contrast2012": "+10"}))
        _xmpgen.write(d, "b.xmp", _xmpgen.xmp_text({"ProcessVersion": "5.7"}))
        _xmpgen.write(d, "c.xmp", _xmpgen.xmp_text({"Contrast2012": "oops"}))
        rc, out, err = _util.run_cli("scan", d)
        self.assertEqual(rc, 1)
        self.assertEqual(out.splitlines(), [MSG_SCAN.format(ok=1, total=3, unsupported=1, failed=1)])
        self.assertEqual(len(err.splitlines()), 1)
        assert_line(self, MSG_SCAN_FAIL, err, file_name="c.xmp")

    def test_scan_missing_folder(self):
        missing = os.path.join(_util.tmpdir(self), "沒有這個資料夾")
        rc, out, err = _util.run_cli("scan", missing)
        self.assertEqual(rc, 2)
        self.assertEqual(err.splitlines(), [MSG_NODIR.format(preset_dir=missing)])


class TestAnyDirectory(unittest.TestCase):  # A21
    def test_module_runs_from_other_directories(self):
        for cwd in (os.path.abspath(os.sep), _util.tmpdir(self)):
            rc, out, err = _util.run_cli("scan", _util.preset_dir(), cwd=cwd)
            self.assertEqual(rc, 0, (cwd, err))
            self.assertEqual(out.splitlines(), [MSG_SCAN.format(ok=_util.LIBRARY_SIZE, total=_util.LIBRARY_SIZE, unsupported=0, failed=0)])


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

    def test_apply_refuses_same_file_spellings(self):  # A16 / F2: same file written differently
        d = _util.tmpdir(self)
        src = small_photo(d)
        with open(src, "rb") as f:
            original = f.read()
        preset = _xmpgen.write(d, "p.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}))
        os.makedirs(os.path.join(d, "sub"))
        spellings = [  # (output as typed, cwd)
            ("in.png", d),                                                      # relative vs absolute
            (os.path.join("sub", "..", "in.png"), d),
            (os.path.join(d, "sub", "..", "in.png"), None),
            (src.replace("\\", "/"), None),                                     # slash direction
        ]
        if os.name == "nt":     # Windows only: names without case and "\\" are the same file there, not on POSIX
            spellings += [
                (os.path.join(d, "IN.PNG"), None),                              # different case
                (os.path.join(os.path.dirname(d), os.path.basename(d).upper(), "In.Png"), None),
                (src.replace("/", "\\"), None),
            ]
        hard = os.path.join(d, "hard.png")
        os.link(src, hard)                                                      # hard link = same file
        spellings.append((hard, None))
        import subprocess
        junction = os.path.join(d, "jx")
        made_junction = False
        if os.name == "nt":                                                     # junctions are Windows only
            r = subprocess.run(["cmd", "/c", "mklink", "/J", junction, d], capture_output=True)
            made_junction = r.returncode == 0
        if made_junction:
            spellings.append((os.path.join(junction, "in.png"), None))
        try:
            link = os.path.join(d, "link.png")
            os.symlink(src, link)
            spellings.append((link, None))
        except OSError:
            pass  # symlinks need developer mode / privilege on Windows; junction and hard link still cover it
        for out_path, cwd in spellings:
            rc, out, err = _util.run_cli("apply", "--preset", preset, "--overwrite", src, out_path, cwd=cwd)
            self.assertEqual(rc, 2, (out_path, out, err))
            self.assertIn(MSG_EXISTS.format(output_path=out_path), err.splitlines())
            with open(src, "rb") as f:
                self.assertEqual(f.read(), original, out_path)
        if os.name == "nt":
            self.assertTrue(made_junction, r.stderr)
        if made_junction:
            os.rmdir(junction)  # removes only the junction, not its target

    def test_apply_bad_strength(self):
        d = _util.tmpdir(self)
        src = small_photo(d)
        preset = _xmpgen.write(d, "p.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}))
        out_path = os.path.join(d, "o.png")
        for bad in ("250", "-1"):
            rc, out, err = _util.run_cli("apply", "--preset", preset, "--strength", bad, src, out_path)
            self.assertEqual(rc, 2)
            self.assertEqual(err.splitlines(), [MSG_STRENGTH.format(strength=bad)])
            self.assertFalse(os.path.exists(out_path))

    def test_skip_line_exact_for_known_skipped(self):  # B14 (2): expected items written out, not read back
        d = _util.tmpdir(self)
        src = small_photo(d)
        look = '   <crs:Look>\n    <rdf:Description crs:Name="Adobe Color"/>\n   </crs:Look>\n'
        preset = _xmpgen.write(d, "skip.xmp", _xmpgen.xmp_text(
            {"HDREditMode": "1", "Temperature": "5500", "Tint": "+10", "GrainAmount": "+20", "GrainFrequency": "70",
             "Exposure2012": "+0.20"}, name="略過測試", extra=look))
        out_path = os.path.join(d, "o.png")
        rc, out, err = _util.run_cli("apply", "--preset", preset, src, out_path)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines(), [
            MSG_OK.format(preset_name="略過測試", strength="100", output_path=out_path),
            "略過：HDREditMode、Temperature、Tint、GrainFrequency、Look（Adobe Color）"])

    def test_format_error_without_extension(self):  # B14 (3)
        d = _util.tmpdir(self)
        src = small_photo(d)
        good = _xmpgen.write(d, "good.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}))
        out_path = os.path.join(d, "noext")
        rc, out, err = _util.run_cli("apply", "--preset", good, src, out_path)
        self.assertEqual(rc, 2)
        self.assertEqual(err.splitlines(), [MSG_FORMAT.format(ext="（無副檔名）")])
        self.assertFalse(os.path.exists(out_path))

    def test_apply_error_lines(self):  # F8
        d = _util.tmpdir(self)
        src = small_photo(d)
        good = _xmpgen.write(d, "good.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}))
        bad = _xmpgen.write(d, "bad.xmp", _xmpgen.xmp_text({"Contrast2012": "oops"}))
        out_path = os.path.join(d, "o.png")
        rc, out, err = _util.run_cli("apply", "--preset", bad, src, out_path)
        self.assertEqual(rc, 2)
        self.assertEqual(len(err.splitlines()), 1)
        assert_line(self, MSG_PRESET, err, file_name="bad.xmp")
        broken = os.path.join(d, "broken.png")
        with open(broken, "wb") as f:
            f.write(b"not an image")
        rc, out, err = _util.run_cli("apply", "--preset", good, broken, out_path)
        self.assertEqual(rc, 2)
        assert_line(self, MSG_PHOTO, err, input_path=broken)
        bmp = os.path.join(d, "o.bmp")
        rc, out, err = _util.run_cli("apply", "--preset", good, src, bmp)
        self.assertEqual(rc, 2)
        self.assertEqual(err.splitlines(), [MSG_FORMAT.format(ext=".bmp")])
        self.assertFalse(os.path.exists(bmp))
        self.assertFalse(os.path.exists(out_path))

    def test_strength_clamp_reported(self):  # A19 / F7
        d = _util.tmpdir(self)
        src = small_photo(d)
        preset = _xmpgen.write(d, "strong.xmp", _xmpgen.xmp_text(
            {"Exposure2012": "+4.00", "SaturationAdjustmentRed": "+60", "Contrast2012": "+20"}, name="強"))
        out_path = os.path.join(d, "o.png")
        rc, out, err = _util.run_cli("apply", "--preset", preset, "--strength", "200", src, out_path)
        self.assertEqual(rc, 0, err)
        items = "、".join(MSG_STRENGTH_CLAMP.format(key=k) for k in ("Exposure2012", "SaturationAdjustmentRed"))
        self.assertEqual(out.splitlines(), [
            MSG_OK.format(preset_name="強", strength="200", output_path=out_path),
            MSG_SKIP.replace("{skipped_items_joined_by_、}", items)])
        rc, out, err = _util.run_cli("apply", "--preset", preset, "--overwrite", src, out_path)
        self.assertEqual(out.splitlines(), [MSG_OK.format(preset_name="強", strength="100", output_path=out_path)])


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
