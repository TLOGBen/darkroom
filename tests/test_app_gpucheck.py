"""B7 / A17 skip rule: other compute processes on the GPU (nvidia-smi --query-compute-apps, type C only)."""
import importlib.util
import os
import unittest

import _util

APPS = """8876, D:\\SteamLibrary\\wallpaper64.exe
15728, C:\\Windows\\explorer.exe
36260, X:\\ComfyUI\\python_embeded\\python.exe
{me}, X:\\darkroom\\python.exe
"""
PIDS = """GPU 00000000:01:00.0
    Processes
        GPU instance ID                   : N/A
        Process ID                        : 8876
            Type                          : C+G
            Name                          : D:\\SteamLibrary\\wallpaper64.exe
        Process ID                        : 15728
            Type                          : C+G
            Name                          : C:\\Windows\\explorer.exe
        Process ID                        : 36260
            Type                          : C
            Name                          : X:\\ComfyUI\\python_embeded\\python.exe
        Process ID                        : {me}
            Type                          : C
            Name                          : X:\\darkroom\\python.exe
"""


def fake_runner(apps, pids):
    def run(args):
        if args[0].startswith("--query-compute-apps"):
            return apps
        return pids
    return run


def load_bench():
    path = os.path.join(_util.REPO, "tools", "bench_preview.py")
    spec = importlib.util.spec_from_file_location("bench_preview", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGpuCheck(unittest.TestCase):
    def test_only_other_pure_compute_processes_count(self):
        from darkroom_app import gpucheck
        me = os.getpid()
        run = fake_runner(APPS.format(me=me), PIDS.format(me=me))
        self.assertEqual(gpucheck.other_compute_processes(runner=run),
                         [(36260, "X:\\ComfyUI\\python_embeded\\python.exe")])
        self.assertEqual(gpucheck.other_compute_processes(exclude=[36260], runner=run), [])

    def test_unknown_type_counts_as_compute(self):
        from darkroom_app import gpucheck
        run = fake_runner("4242, X:\\mystery.exe\n", "")
        self.assertEqual(gpucheck.other_compute_processes(runner=run), [(4242, "X:\\mystery.exe")])

    def test_nvidia_smi_failure_is_none(self):
        from darkroom_app import gpucheck

        def broken(args):
            raise OSError("nvidia-smi not found")
        self.assertIsNone(gpucheck.other_compute_processes(runner=broken))

    def test_bench_skip_message_names_processes(self):
        bench = load_bench()
        me = os.getpid()
        run = fake_runner(APPS.format(me=me), PIDS.format(me=me))
        skip, msg = bench.gpu_check(exclude=(), runner=run)
        self.assertTrue(skip)
        self.assertIn("X:\\ComfyUI\\python_embeded\\python.exe", msg)
        self.assertIn("36260", msg)
        self.assertNotIn("explorer.exe", msg)
        skip, msg = bench.gpu_check(exclude=(36260,), runner=run)
        self.assertFalse(skip)

    def test_bench_thresholds(self):
        bench = load_bench()
        self.assertEqual((bench.MEDIAN_LIMIT_MS, bench.P95_LIMIT_MS), (100.0, 150.0))
        self.assertEqual((bench.HZ, bench.SECONDS, bench.MEGAPIXELS), (60, 10.0, 24.0))


if __name__ == "__main__":
    unittest.main()
