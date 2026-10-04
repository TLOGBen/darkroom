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

def clocks():
    o = subprocess.run(["nvidia-smi", "--query-gpu=clocks.gr,clocks.mem,pstate", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    return o

def one(p=P):
    torch.cuda.synchronize(); t = time.perf_counter()
    u8 = m.grade(img, p)
    t_enq = time.perf_counter()
    torch.cuda.synchronize(); t2 = time.perf_counter()
    return (t_enq - t) * 1000, (t2 - t) * 1000

def run(gap, n=15, p=P, label=""):
    enq, tot, ck = [], [], None
    for i in range(n):
        time.sleep(gap)
        if i == n // 2:
            ck = clocks()  # clocks right before a request (after idle gap)
            time.sleep(0.0)
        e, t = one(p); enq.append(e); tot.append(t)
    print(f"{label:28s} gap={gap*1000:4.0f}ms  total p50={np.median(tot):6.1f} p95={np.percentile(tot,95):6.1f}  "
          f"cpu-enqueue p50={np.median(enq):6.1f}  clocks_before={ck}")

for g in [0, 0.1, 0.2, 0.5, 1.0]:
    run(g, label="all ops")
for g in [0, 0.5]:
    run(g, p={"llf": False}, label="no LLF")

# remedy A: keep-alive thread launching a tiny kernel every 20 ms
stop = False
def keepalive():
    x = torch.zeros(1, device="cuda")
    while not stop:
        x += 1; torch.cuda.synchronize(); time.sleep(0.02)
th = threading.Thread(target=keepalive, daemon=True); th.start()
for g in [0.5, 1.0]:
    run(g, label="keepalive 20ms tiny kernel")
stop = True; th.join()
# remedy B: CPU busy-spin keepalive (no GPU work)
stop = False
def spin():
    while not stop:
        pass
th = threading.Thread(target=spin, daemon=True); th.start()
for g in [0.5]:
    run(g, label="CPU spin thread only")
stop = True; th.join()
# remedy C: CUDA graph capture of the whole chain (fixed params)
s = torch.cuda.Stream()
static = img.clone()
with torch.cuda.stream(s):
    for _ in range(3): m.grade(static, {"clarity": 0.5, "shadows": 0.3, "curve": [[0, 0], [1, 1]]})
torch.cuda.synchronize()
try:
    g_ = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g_):
        out = m.grade(static, {"clarity": 0.5, "shadows": 0.3, "curve": [[0, 0], [1, 1]]})
    for gap in [0, 0.5]:
        ts = []
        for i in range(15):
            time.sleep(gap); torch.cuda.synchronize(); t = time.perf_counter(); g_.replay(); torch.cuda.synchronize(); ts.append((time.perf_counter() - t) * 1000)
        print(f"{'CUDA graph replay':28s} gap={gap*1000:4.0f}ms  total p50={np.median(ts):6.1f} p95={np.percentile(ts,95):6.1f}")
except Exception as ex:
    print("CUDA graph failed:", repr(ex)[:300])
print("idle clocks:", clocks())
