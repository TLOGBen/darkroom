"""CONTRACT-layering L3-L6: services behind the facade (list_presets, max_pixels, GPU thread, lazy Engine)."""
import os
import subprocess
import sys
import threading
import unittest
from unittest import mock

import cv2
import numpy as np

import _util
from darkroom_app.errors import DarkroomError
from test_app_server import make_presets, write_photo


class ServiceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        cls.tmp = _util.class_tmpdir(cls, "darkroom-test-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        d = os.path.join(cls.tmp, "presets")
        os.makedirs(d)
        cls.presets = make_presets(d)
        cls.photo = write_photo(os.path.join(cls.tmp, "a.png"), 1600, 1000)
        from darkroom_app.composition import build_facade
        cls.f = build_facade(cls.presets)
        cls.addClassCleanup(lambda: cls.f._photos.engine_ref.peek() and cls.f._photos.engine_ref.peek().shutdown())

    def err(self, fn, *a, **k):
        with self.assertRaises(DarkroomError) as cm:
            fn(*a, **k)
        return cm.exception.kind, cm.exception.message


class TestListPresets(ServiceCase):  # L4
    def test_shape_and_order(self):
        lib = self.f._presets.library
        r = self.f.list_presets()
        self.assertEqual(list(r), ["items", "total", "next_offset"])
        self.assertEqual([x["id"] for x in r["items"]], [e["id"] for e in lib.entries])
        for row in r["items"]:
            self.assertEqual(list(row), ["id", "group", "name", "supported", "skipped"])
        self.assertEqual((r["total"], r["next_offset"]), (6, None))

    def test_query_paging(self):
        r = self.f.list_presets("測試")                 # group
        self.assertEqual(r["total"], 3)
        self.assertEqual([x["id"] for x in self.f.list_presets("很亮")["items"]], ["p-strong"])   # name
        self.assertEqual(self.f.list_presets("P-OLD")["total"], 1)     # casefold; unsupported name = id
        page = self.f.list_presets(None, 0, 4)
        self.assertEqual((len(page["items"]), page["next_offset"]), (4, 4))
        page = self.f.list_presets(None, 4, 4)
        self.assertEqual((len(page["items"]), page["next_offset"]), (2, None))
        page = self.f.list_presets(None, 2, 4)
        self.assertEqual(page["next_offset"], None)
        self.assertEqual(self.f.list_presets(None, 99, 200), {"items": [], "total": 6, "next_offset": None})

    def test_invalid(self):
        for off in (-1, 1.0, True, "0", None):
            self.assertEqual(self.err(self.f.list_presets, None, off), ("invalid", "offset must be an integer >= 0"))
        for lim in (0, 201, 1.5, True, "5"):
            self.assertEqual(self.err(self.f.list_presets, None, 0, lim),
                             ("invalid", "limit must be an integer in 1..200"))
        self.assertEqual(self.f.list_presets(None, 0, 200)["total"], 6)
        self.assertEqual(self.f.list_presets(None, 0, 1)["next_offset"], 1)


class TestPreviewService(ServiceCase):  # L5
    def test_max_pixels(self):
        info = self.f.open_photo(self.photo)
        iid = info["image_id"]
        eng = self.f._previews.engine_ref.peek()
        full = self.f.preview(iid)
        self.assertEqual((full.width, full.height), (info["preview_width"], info["preview_height"]))
        from darkroom_app.engine import preview_size
        from darkroom_app.preview import effective_params
        for mp in (65536, 786432, 1500000):
            r = self.f.preview(iid, "p-expo", 100, None, mp)
            img = cv2.imdecode(np.frombuffer(r.jpeg, np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual((r.width, r.height), preview_size(info["preview_width"], info["preview_height"], mp))
            self.assertEqual(img.shape[:2], (r.height, r.width))
        for mp in (65535, 1500001, 70000.0, True, "70000"):
            self.assertEqual(self.err(self.f.preview, iid, None, 100, None, mp),
                             ("invalid", "max_pixels must be an integer in 65536..1500000"))
        # overrides are validated first
        self.assertEqual(self.err(self.f.preview, iid, None, 100, {"Bogus": 1}, 5)[1], "unknown slider key 'Bogus'")
        # max_pixels=None: the same bytes as Engine.preview with the same final parameters
        final = effective_params(self.f._presets.library.get("p-expo"), 0.5, {"Exposure2012": 0.3})
        direct, _ = eng.executor.submit(eng.preview, iid, final).result()
        via = self.f.preview(iid, "p-expo", 50, {"Exposure2012": 0.3})
        self.assertEqual(via.jpeg, direct)

    def test_gpu_reentrant_no_deadlock(self):  # L6
        info = self.f.open_photo(self.photo)
        eng = self.f._previews.engine_ref.peek()
        seen = []
        real = eng.preview

        def spy(*a, **k):
            seen.append(threading.current_thread().name)
            return real(*a, **k)
        with mock.patch.object(eng, "preview", spy):
            fut = eng.executor.submit(lambda: (self.f.preview(info["image_id"]),
                                               self.f.open_photo(self.photo)))
            res, opened = fut.result(timeout=2)       # would hang forever if it re-submitted to itself
            self.f.preview(info["image_id"])           # and from an ordinary thread
        self.assertEqual(len(res.jpeg) > 0, True)
        self.assertIn("image_id", opened)
        self.assertEqual(len(seen), 2)
        for name in seen:
            self.assertTrue(name.startswith("darkroom-gpu"), name)

    def test_open_runs_on_gpu_thread(self):  # L6
        eng = self.f._photos.engine_ref.get()
        seen = []
        real = eng.open

        def spy(path):
            seen.append(threading.current_thread().name)
            return real(path)
        with mock.patch.object(eng, "open", spy):
            self.f.open_photo(self.photo)
        self.assertTrue(seen and seen[0].startswith("darkroom-gpu"), seen)
        self.assertEqual(eng.executor._max_workers, 1)


class TestLazyEngine(unittest.TestCase):  # L1
    def test_engine_built_on_first_gpu_use(self):
        tmp = _util.tmpdir(self)
        d = os.path.join(tmp, "p")
        os.makedirs(d)
        make_presets(d)
        code = ("import sys\n"
                "from darkroom_app.composition import build_facade\n"
                "from darkroom_app.errors import DarkroomError\n"
                "f = build_facade(sys.argv[1])\n"
                "f.list_presets(); f.preset_detail('p-expo'); f.preset_flags(); f.slider_table()\n"
                "for call in (lambda: f.preview('x'), lambda: f.list_folder('x'), lambda: f.open_photo(''),\n"
                "             lambda: f.open_photo(sys.argv[1] + '/missing.jpg')):\n"
                "    try:\n"
                "        call()\n"
                "    except DarkroomError:\n"
                "        pass\n"
                "print(f._photos.engine_ref.peek() is None, 'torch' in sys.modules, 'cv2' in sys.modules)\n")
        r = subprocess.run([*_util.guarded_python(), "-c", code, d], cwd=_util.REPO, capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertEqual(r.stdout.decode().split(), ["True", "False", "False"])


if __name__ == "__main__":
    unittest.main()
