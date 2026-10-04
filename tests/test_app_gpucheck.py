"""B7 / A17 skip rule (patched 2026-10-04): skip only while the GPU is really busy.

Busy = median of 5 utilization samples > 15 %, or a ComfyUI process whose /queue is not empty.
Idle ComfyUI = measure; unreachable /queue = idle; nvidia-smi unavailable = cannot tell (skip).
"""
import importlib.util
import os
import unittest

import _util

COMFY = "X:\\LocalLLMs\\runtimes\\comfyui\\ComfyUI_windows_portable\\python_embeded\\python.exe"
APPS_WITH_COMFY = f"15728, C:\\Windows\\explorer.exe\n36260, {COMFY}\n"
APPS_NO_COMFY = "15728, C:\\Windows\\explorer.exe\n9999, X:\\llama.cpp\\llama-server.exe\n"


def fake_smi(utils, apps):
    it = iter(utils)

    def run(args):
        if args[0].startswith("--query-gpu=utilization.gpu"):
            return f"{next(it)}\n"
        if args[0].startswith("--query-compute-apps"):
            return apps
        raise AssertionError(args)
    return run


def queue(running=0, pending=0):
    def fetch():
        return {"queue_running": [[i] for i in range(running)], "queue_pending": [[i] for i in range(pending)]}
    return fetch


def unreachable():
    raise ConnectionRefusedError("[WinError 10061] connection refused")


def busy(utils, apps, fetch):
    from darkroom_app import gpucheck
    return gpucheck.gpu_busy(runner=fake_smi(utils, apps), fetch_queue=fetch, sleep=lambda s: None)


def load_bench():
    path = os.path.join(_util.REPO, "tools", "bench_preview.py")
    spec = importlib.util.spec_from_file_location("bench_preview", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGpuBusy(unittest.TestCase):
    def test_constants(self):
        from darkroom_app import gpucheck
        self.assertEqual((gpucheck.BUSY_UTIL_PERCENT, gpucheck.BUSY_SAMPLES), (15.0, 5))
        self.assertEqual(gpucheck.COMFYUI_QUEUE_URL, "http://127.0.0.1:8188/queue")
        self.assertLessEqual(gpucheck.SAMPLE_INTERVAL_S * (gpucheck.BUSY_SAMPLES - 1), 1.0)

    def test_idle_comfyui_with_empty_queue_measures(self):
        b, reason = busy([4, 7, 5, 6, 3], APPS_WITH_COMFY, queue(0, 0))
        self.assertIs(b, False)
        self.assertIn("5%", reason)
        self.assertIn("佇列是空的", reason)

    def test_comfyui_running_is_busy(self):
        b, reason = busy([4, 7, 5, 6, 3], APPS_WITH_COMFY, queue(1, 2))
        self.assertIs(b, True)
        self.assertIn("執行中 1", reason)
        self.assertIn("等待中 2", reason)
        b, _ = busy([4, 7, 5, 6, 3], APPS_WITH_COMFY, queue(0, 1))   # only pending also counts
        self.assertIs(b, True)

    def test_comfyui_queue_unreachable_is_idle(self):
        b, reason = busy([4, 7, 5, 6, 3], APPS_WITH_COMFY, unreachable)
        self.assertIs(b, False)
        self.assertIn("連不到", reason)

    def test_high_utilization_is_busy(self):
        b, reason = busy([90, 95, 10, 88, 91], APPS_NO_COMFY, queue())
        self.assertIs(b, True)
        self.assertIn("90%", reason)          # median of the five samples
        self.assertIn("90、95、10、88、91", reason)

    def test_utilization_threshold_is_strictly_above_15(self):
        self.assertIs(busy([15, 15, 15, 15, 15], APPS_NO_COMFY, queue())[0], False)
        self.assertIs(busy([16, 16, 0, 0, 16], APPS_NO_COMFY, queue())[0], True)
        self.assertIs(busy([60, 70, 2, 3, 4], APPS_NO_COMFY, queue())[0], False)   # a short spike is not busy

    def test_queue_not_checked_without_comfyui(self):
        def must_not_fetch():
            raise AssertionError("queried ComfyUI although it is not on the GPU")
        b, reason = busy([3, 3, 3, 3, 3], APPS_NO_COMFY, must_not_fetch)
        self.assertIs(b, False)
        self.assertIn("沒有偵測到 ComfyUI", reason)

    def test_nvidia_smi_failure_cannot_tell(self):
        from darkroom_app import gpucheck

        def broken(args):
            raise OSError("nvidia-smi not found")
        b, reason = gpucheck.gpu_busy(runner=broken, fetch_queue=queue(), sleep=lambda s: None)
        self.assertIsNone(b)
        self.assertIn("nvidia-smi", reason)

    def test_samples_spread_over_about_a_second(self):
        from darkroom_app import gpucheck
        waits = []
        gpucheck.gpu_busy(runner=fake_smi([1] * 5, APPS_NO_COMFY), fetch_queue=queue(), sleep=waits.append)
        self.assertEqual(len(waits), 4)
        self.assertAlmostEqual(sum(waits), 0.8)


class TestBenchSkip(unittest.TestCase):
    def test_bench_skips_with_reason_only_when_busy(self):
        bench = load_bench()
        skip, msg = bench.gpu_check(runner=fake_smi([5] * 5, APPS_WITH_COMFY), fetch_queue=queue(1, 0),
                                    sleep=lambda s: None)
        self.assertTrue(skip)
        self.assertTrue(msg.startswith("[B7] 跳過："))
        self.assertIn("執行中 1", msg)
        skip, msg = bench.gpu_check(runner=fake_smi([5] * 5, APPS_WITH_COMFY), fetch_queue=queue(),
                                    sleep=lambda s: None)
        self.assertFalse(skip)
        skip, msg = bench.gpu_check(runner=fake_smi([5] * 5, APPS_WITH_COMFY), fetch_queue=unreachable,
                                    sleep=lambda s: None)
        self.assertFalse(skip)
        skip, msg = bench.gpu_check(runner=fake_smi([80] * 5, APPS_NO_COMFY), fetch_queue=queue(),
                                    sleep=lambda s: None)
        self.assertTrue(skip)
        self.assertIn("80%", msg)

    def test_bench_thresholds(self):
        bench = load_bench()
        self.assertEqual((bench.MEDIAN_LIMIT_MS, bench.P95_LIMIT_MS), (100.0, 150.0))
        self.assertEqual((bench.HZ, bench.SECONDS, bench.MEGAPIXELS), (60, 10.0, 24.0))


if __name__ == "__main__":
    unittest.main()
