"""Is someone actually using the GPU right now? (skip rule for timing checks: app-shell B7, core A17)

Layer: utils (standard library only). Used by tests and tools/bench_*.py, never by a request. The write guard
allows its `nvidia-smi` subprocess from this file only (darkroom_app/utils/gpucheck.py).

Busy when either
  1. the median of BUSY_SAMPLES readings of `nvidia-smi --query-gpu=utilization.gpu` taken over about one
     second is above BUSY_UTIL_PERCENT, or
  2. a ComfyUI process is on the GPU (a compute process whose path contains "comfyui") and its
     /queue (127.0.0.1:8188) has a non-empty queue_running or queue_pending.
An idle ComfyUI that merely keeps models in memory does not count; an unreachable /queue counts as idle.
If nvidia-smi cannot be run at all, the GPU state is unknown and the timing is skipped (reason printed).

Why: the latency acceptance checks (B7 = "preview round trip while dragging at 60 Hz", A17 = "global pipeline
<= 25 ms") would fail for reasons that have nothing to do with darkroom when another program (typically ComfyUI
generating an image) is using the 16 GB GPU, and passing them silently would be worse. So a busy or unknown GPU
skips the timing with the reason printed instead.
"""
import json
import statistics
import subprocess
import time
import urllib.request

BUSY_UTIL_PERCENT = 15.0
BUSY_SAMPLES = 5
SAMPLE_INTERVAL_S = 0.2
COMFYUI_QUEUE_URL = "http://127.0.0.1:8188/queue"


def _run(args):
    """stdout of `nvidia-smi <args>` as text; OSError with nvidia-smi's own message on a non-zero exit."""
    r = subprocess.run(["nvidia-smi", *args], capture_output=True, timeout=30)
    if r.returncode != 0:
        raise OSError(r.stderr.decode("utf-8", "replace").strip() or f"nvidia-smi exited {r.returncode}")
    return r.stdout.decode("utf-8", "replace")


def _fetch_queue(url=COMFYUI_QUEUE_URL, timeout=2.0):
    """ComfyUI's /queue JSON (local only); raises OSError / ValueError when unreachable or malformed."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_compute_apps(csv_text):
    """'pid, name' lines -> [(pid, name)]."""
    out = []
    for line in csv_text.splitlines():
        if not line.strip():
            continue
        pid, _, name = line.partition(",")
        try:
            out.append((int(pid.strip()), name.strip()))
        except ValueError:
            continue
    return out


def parse_utilization(text):
    """First GPU's utilization.gpu (csv,noheader,nounits) -> float percent."""
    for line in text.splitlines():
        line = line.strip().rstrip("%").strip()
        if line:
            return float(line)
    raise ValueError("no utilization reading")


def gpu_busy(runner=_run, fetch_queue=_fetch_queue, sleep=time.sleep, samples=BUSY_SAMPLES):
    """(busy, reason). busy is True (skip), False (measure) or None (cannot tell: skip).

    runner / fetch_queue / sleep are injectable so the tests can simulate every case without a GPU. reason is a
    one-line zh-TW sentence printed with the skip. Side effects: runs nvidia-smi `samples + 1` times and may call
    ComfyUI's /queue once; never writes anything."""
    try:
        readings = []
        for i in range(samples):
            if i:
                sleep(SAMPLE_INTERVAL_S)
            readings.append(parse_utilization(runner(["--query-gpu=utilization.gpu",
                                                      "--format=csv,noheader,nounits"])))
        apps = parse_compute_apps(runner(["--query-compute-apps=pid,process_name", "--format=csv,noheader"]))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return None, f"nvidia-smi 無法執行，無法確認 GPU 是否忙碌（{e}）"
    med = statistics.median(readings)
    shown = "、".join(f"{r:g}" for r in readings)
    if med > BUSY_UTIL_PERCENT:
        return True, f"GPU 使用率中位數 {med:g}%（> {BUSY_UTIL_PERCENT:g}%；取樣 {shown}）"
    comfy = [(pid, name) for pid, name in apps if "comfyui" in name.lower()]
    if comfy:
        try:
            q = fetch_queue()
            running, pending = len(q.get("queue_running") or []), len(q.get("queue_pending") or [])
        except (OSError, ValueError, AttributeError):
            return False, f"GPU 使用率中位數 {med:g}%；ComfyUI（PID {comfy[0][0]}）的 /queue 連不到，當作閒置"
        if running or pending:
            return True, f"ComfyUI（PID {comfy[0][0]}）正在工作：佇列執行中 {running}、等待中 {pending}"
        return False, f"GPU 使用率中位數 {med:g}%；ComfyUI（PID {comfy[0][0]}）佇列是空的（閒置）"
    return False, f"GPU 使用率中位數 {med:g}%；沒有偵測到 ComfyUI"
