import sys, types, time, threading, subprocess, importlib.util
import numpy as np, torch
from aiohttp import web
srv = types.ModuleType("server")
class PS: pass
PS.instance = types.SimpleNamespace(routes=web.RouteTableDef())
srv.PromptServer = PS; sys.modules["server"] = srv
spec = importlib.util.spec_from_file_location("lrp", sys.argv[1] + "/__init__.py", submodule_search_locations=[sys.argv[1]])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.HERE = sys.argv[2]
m.ensure_loaded(1.5)
img = m._state["img"]
P = {"clarity": 0.5, "shadows": 0.3}

def smi():
    return subprocess.run(["nvidia-smi", "--query-gpu=clocks.gr,pstate,power.draw", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()

def one():
    torch.cuda.synchronize(); t = time.perf_counter()
    m.grade(img, P); torch.cuda.synchronize()
    return (time.perf_counter() - t) * 1000

def run(label, gap=1.5, n=8):
    ts = []
    for i in range(n):
        time.sleep(gap)
        if i == n // 2: s = smi()
        ts.append(one())
    print(f"{label:34s} gap={gap}s first-after-idle p50={np.median(ts):6.1f} max={max(ts):6.1f}  smi_before={s}", flush=True)

run("baseline")
A = torch.randn(2048, 2048, device="cuda")
for period, reps in [(0.1, 1), (0.05, 1), (0.1, 8), (0.02, 4)]:
    stop = [False]
    def keep():
        while not stop[0]:
            for _ in range(reps): A @ A
            torch.cuda.synchronize(); time.sleep(period)
    th = threading.Thread(target=keep, daemon=True); th.start(); time.sleep(1)
    run(f"keepalive matmul2048 x{reps} every {int(period*1000)}ms")
    stop[0] = True; th.join()
# warm-up burst right before the request (what a pointerdown/hover ping would do)
ts = []
for i in range(8):
    time.sleep(1.5)
    for _ in range(3): m.grade(img, {"llf": False})  # ~15 ms of throwaway work
    torch.cuda.synchronize(); time.sleep(0.03)
    ts.append(one())
print(f"{'3x cheap grade 30ms before':34s} p50={np.median(ts):6.1f} max={max(ts):6.1f}")
print("idle:", smi())
