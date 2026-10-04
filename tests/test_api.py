"""A1/A2 (amended by app-shell B1): public API surface."""
import os
import re
import unittest

import _util


class TestPublicApi(unittest.TestCase):
    def test_all_is_exactly_the_seven_names(self):  # A2 / B1
        import darkroom
        self.assertEqual(sorted(darkroom.__all__),
                         sorted(["load_preset", "Params", "render", "read_image", "write_image", "SCHEMA_VERSION",
                                 "UnsupportedPresetError"]))
        for name in darkroom.__all__:
            self.assertTrue(hasattr(darkroom, name), name)

    def test_schema_version_constant(self):
        import darkroom
        self.assertEqual(darkroom.SCHEMA_VERSION, "darkroom-params/1")

    def test_no_private_imports_outside_tests(self):
        """Code outside darkroom/ and tests/ must not reach into darkroom._* or private names."""
        bad = re.compile(r"(from\s+darkroom\._\w*|import\s+darkroom\._|from\s+darkroom\s+import\s+_)")
        offenders = []
        for root, dirs, files in os.walk(_util.REPO):
            rel = os.path.relpath(root, _util.REPO).replace("\\", "/")
            if rel.split("/")[0] in (".git", "tests", "darkroom", ".claude", ".strategic-advance"):
                dirs[:] = []
                continue
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(root, f), "rb") as fh:
                        if bad.search(fh.read().decode("utf-8", "replace")):
                            offenders.append(os.path.join(rel, f))
        self.assertEqual(offenders, [])

    def test_package_modules_are_private(self):
        """Only the seven names are public; implementation modules are underscore-prefixed."""
        pkg = os.path.join(_util.REPO, "darkroom")
        for f in os.listdir(pkg):
            if f.endswith(".py") and f not in ("__init__.py", "__main__.py"):
                self.assertTrue(f.startswith("_"), f)


    def test_read_write_image_are_the_io_functions(self):  # B1
        import darkroom
        from darkroom import _io
        self.assertIs(darkroom.read_image, _io.read_image)
        self.assertIs(darkroom.write_image, _io.write_image)

    def test_app_imports_only_public_names(self):  # B1: darkroom_app uses `darkroom`'s public names only
        import ast
        import darkroom
        app = os.path.join(_util.REPO, "darkroom_app")
        self.assertTrue(os.path.isdir(app))
        seen = set()
        for root, _, files in os.walk(app):
            for f in files:
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "darkroom":
                        self.assertEqual(node.module, "darkroom", f)
                        for a in node.names:
                            self.assertIn(a.name, darkroom.__all__, f)
                            seen.add(a.name)
                    elif isinstance(node, ast.Import):
                        for a in node.names:
                            self.assertFalse(a.name.startswith("darkroom."), f)
        self.assertIn("render", seen)
        self.assertIn("read_image", seen)


class TestRenderStaysOnDevice(unittest.TestCase):  # B1
    def test_gpu_tensor_in_gpu_tensor_out_without_host_copies(self):
        import torch
        from unittest import mock
        import darkroom
        if not torch.cuda.is_available():
            self.skipTest("needs CUDA")
        img = torch.rand(1, 3, 120, 180, device="cuda")
        p = darkroom.Params(values={"Exposure2012": 0.5, "Clarity2012": 30.0, "Texture": 20.0, "Contrast2012": 25.0,
                                    "SaturationAdjustmentRed": 30.0, "GrainAmount": 10.0, "Sharpness": 40.0,
                                    "PostCropVignetteAmount": -20.0, "SplitToningShadowSaturation": 30.0},
                            curves={"ToneCurvePV2012": [[0.0, 10.0], [128.0, 140.0], [255.0, 250.0]]})
        darkroom.render(img, p)  # warm the grain-noise cache (its CPU generator runs once per size)
        real_to = torch.Tensor.to

        def guarded_to(t, *a, **k):
            dev = k.get("device", a[0] if a and isinstance(a[0], (str, torch.device)) else None)
            if t.is_cuda and dev is not None and torch.device(dev).type == "cpu":
                raise AssertionError("render copied a GPU tensor back to the CPU")
            return real_to(t, *a, **k)

        def no_host(*a, **k):
            raise AssertionError("render copied a GPU tensor back to the CPU")
        with mock.patch.object(torch.Tensor, "cpu", no_host), mock.patch.object(torch.Tensor, "numpy", no_host),                 mock.patch.object(torch.Tensor, "to", guarded_to):
            out = darkroom.render(img, p, strength=1.5)
            out3 = darkroom.render(img[0], p)
        self.assertIsInstance(out, torch.Tensor)
        self.assertEqual(out.device, img.device)
        self.assertEqual(tuple(out.shape), (1, 3, 120, 180))
        self.assertEqual(out3.device, img.device)
        self.assertEqual(tuple(out3.shape), (3, 120, 180))


if __name__ == "__main__":
    unittest.main()
