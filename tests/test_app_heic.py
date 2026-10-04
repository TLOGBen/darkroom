"""HEIC in the App (CONTRACT-heic H6, H7): folder listing, open, broken files, read-only."""
import os
import unittest
from unittest import mock

import numpy as np

import _heicgen
import _iccgen
import _util
from test_app_server import AppCase, decode, snapshot, write_photo

APP_OPEN_ERROR = "照片讀取失敗：{file_name}：{reason}"   # verbatim (CONTRACT-heic)


class TestHeicInApp(AppCase):
    async def test_folder_lists_heic(self):  # H7
        for n in ("a.jpg", "B.png", "c.tif"):
            write_photo(os.path.join(self.photos, n), 64, 48)
        for n in ("d.HEIC", "e.heif", "f.heic"):
            _heicgen.write_heic(os.path.join(self.photos, n), _heicgen.pattern(48, 64))
        with open(os.path.join(self.photos, "g.heic.txt"), "w") as f:
            f.write("x")
        r = await self.client.post("/api/open", json={"path": os.path.join(self.photos, "e.heif")})
        self.assertEqual(r.status, 200, await r.text())
        info = await r.json()
        data = await (await self.client.get("/api/folder", params={"image_id": info["image_id"]})).json()
        self.assertEqual([f["name"] for f in data["files"]], ["a.jpg", "B.png", "c.tif", "d.HEIC", "e.heif", "f.heic"])
        self.assertEqual(data["index"], 4)

    async def test_open_heic_upright_p3_10bit(self):  # H7: sizes after orientation, preview renders
        img = _heicgen.pattern(1200, 1600)          # 1.92 MP, wider than tall
        path = _heicgen.write_heic(os.path.join(self.photos, "IMG_0001.HEIC"), _heicgen.srgb_to_p3(img), bits=10,
                                   icc=_iccgen.display_p3(), orientation=6)
        r = await self.client.post("/api/open", json={"path": path})
        self.assertEqual(r.status, 200, await r.text())
        info = await r.json()
        self.assertEqual((info["width"], info["height"]), (1200, 1600))     # portrait after orientation 6
        self.assertLessEqual(info["preview_width"] * info["preview_height"], 1500000)
        self.assertLess(info["preview_width"], info["preview_height"])
        r, data = await self.preview(image_id=info["image_id"], preset_id=None, strength=100, overrides={})
        self.assertEqual(r.status, 200)
        self.assertEqual(decode(data).shape, (info["preview_height"], info["preview_width"], 3))

    async def test_broken_heic_open_is_400_and_server_lives(self):  # H6
        good = _heicgen.write_heic(os.path.join(self.photos, "good.heic"), _heicgen.pattern(64, 64))
        with open(good, "rb") as f:
            data = f.read()
        for name, blob in (("half.heic", data[: len(data) // 2]), ("junk.HEIC", os.urandom(2048)), ("empty.heif", b"")):
            path = os.path.join(self.photos, name)
            with open(path, "wb") as f:
                f.write(blob)
            r = await self.client.post("/api/open", json={"path": path})
            self.assertEqual(r.status, 400, name)
            err = (await r.json())["error"]
            prefix = APP_OPEN_ERROR.format(file_name=name, reason="HEIC 解碼失敗：")
            self.assertTrue(err.startswith(prefix), err)
            self.assertNotIn("\n", err)
            self.assertEqual((await self.client.get("/api/health")).status, 200)
        r = await self.client.post("/api/open", json={"path": good})
        self.assertEqual(r.status, 200)

    async def test_broken_icc_open_is_400_and_server_lives(self):  # F1: damaged profile, decodable pixels
        for name, icc in _iccgen.broken_profiles().items():
            path = _heicgen.write_heic(os.path.join(self.photos, name + ".heic"), _heicgen.pattern(32, 32), icc=icc)
            r = await self.client.post("/api/open", json={"path": path})
            self.assertEqual(r.status, 400, name)
            err = (await r.json())["error"]
            prefix = APP_OPEN_ERROR.format(file_name=name + ".heic", reason="HEIC 解碼失敗：內嵌色彩描述檔損壞（")
            self.assertTrue(err.startswith(prefix), err)
            self.assertNotIn("\n", err)
            self.assertEqual((await self.client.get("/api/health")).status, 200)

    async def test_other_read_errors_use_the_same_sentence(self):  # H6 / constant
        bad = os.path.join(self.photos, "broken.jpg")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        r = await self.client.post("/api/open", json={"path": bad})
        self.assertEqual(r.status, 400)
        self.assertTrue((await r.json())["error"].startswith("照片讀取失敗：broken.jpg："))

    async def test_server_never_writes_heic(self):  # H6 / B12
        for n in ("a.heic", "b.HEIF"):
            _heicgen.write_heic(os.path.join(self.photos, n), _heicgen.pattern(64, 96), bits=10,
                                icc=_iccgen.display_p3(), orientation=8)
        before = snapshot(self.photos, self.presets)
        for n in ("a.heic", "b.HEIF"):
            r = await self.client.post("/api/open", json={"path": os.path.join(self.photos, n)})
            info = await r.json()
            r, _ = await self.preview(image_id=info["image_id"], preset_id="p-expo", strength=150,
                                      overrides={"Exposure2012": 0.2})
            self.assertEqual(r.status, 200)
            await self.client.get("/api/folder", params={"image_id": info["image_id"]})
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual(sorted(os.listdir(self.photos)), ["a.heic", "b.HEIF"])


if __name__ == "__main__":
    unittest.main()
