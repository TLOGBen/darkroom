"""Extra check for Part B: does aligning Qwen onto the program result before blending remove ghosting?
Variants at 50%: plain blend, ECC-affine-aligned blend, dense-flow (Farneback) warped blend. Writes panels/B50_aligned_<photo>.png."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import HERE, REGIONS, load, resize_to, crop, flow, warp, ecc_align, panel, stack
from jobs import jobs

for j in jobs():
    if j["part"] != "B":
        continue
    pid = j["photo"]
    o = load(os.path.join(HERE, "photos", f"{pid}.png")); H, W = o.shape[:2]
    p = load(os.path.join(HERE, "prog", f"{pid}_pos.png"))
    q = resize_to(load(os.path.join(HERE, "ai", j["tag"] + ".png")), W, H)
    qe, _ = ecc_align(p, q)
    qf = warp(q, flow(p, q))
    mix = lambda x: (0.5 * p.astype(np.float32) + 0.5 * x.astype(np.float32)).astype(np.uint8)
    vs = [mix(q), mix(qe), mix(qf)]
    rows = [panel([crop(v, b) for v in vs], [f"{k} 50% 直接混", "ECC 對齊後混", "光流對齊後混"], 320)
            for k, b in REGIONS[pid].items() if k != "face"]
    stack(rows, 4, 1800).save(os.path.join(HERE, "panels", f"B50_aligned_{pid}.png"))
    print(pid)
