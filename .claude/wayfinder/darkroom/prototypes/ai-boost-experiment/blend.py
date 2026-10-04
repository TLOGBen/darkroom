"""Part B: blend program result (clarity+40/dehaze+30/texture+40) with the Qwen boost at 0/25/50/75/100 %.

Qwen output is resized back to the original size, then out = (1-a)*program + a*qwen.
Ghosting check: dense flow program->Qwen (misalignment in px, overall and per detail crop), and the misalignment error
a*|qwen - qwen_warped_onto_program| (what the blend gets wrong because the two layers are not aligned), p99 per crop.
Writes blends/<photo>_<pct>.png, panels/B_<photo>.png (full blends row + zoom grid) and metrics_B.json / .md.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import HERE, REGIONS, load, resize_to, crop, flow, flow_stats, warp, ssim, mae, panel, stack
from jobs import jobs

os.makedirs(os.path.join(HERE, "blends"), exist_ok=True)
os.makedirs(os.path.join(HERE, "panels"), exist_ok=True)
ALPHAS = [0, 0.25, 0.5, 0.75, 1.0]
runs = {l.split("\t")[0]: l.rstrip("\n").split("\t") for l in open(os.path.join(HERE, "runs.tsv"), encoding="utf-8")}
rows = []
for j in jobs():
    if j["part"] != "B" or not os.path.exists(os.path.join(HERE, "ai", j["tag"] + ".png")):
        continue
    pid = j["photo"]
    o = load(os.path.join(HERE, "photos", f"{pid}.png"))
    H, W = o.shape[:2]
    prog = load(os.path.join(HERE, "prog", f"{pid}_pos.png")).astype(np.float32)
    q_raw = load(os.path.join(HERE, "ai", j["tag"] + ".png"))
    q = resize_to(q_raw, W, H).astype(np.float32)
    fl = flow(prog.astype(np.uint8), q.astype(np.uint8))
    qw = warp(q, fl)                         # Qwen pulled onto program geometry
    mis = np.abs(q - qw).mean(2)             # per-pixel error caused by misalignment (at a=1)
    det = {k: b for k, b in REGIONS[pid].items() if k != "face"}
    r = dict(tag=j["tag"], photo=pid, comfy_s=runs[j["tag"]][3], qwen=f"{q_raw.shape[1]}x{q_raw.shape[0]}",
             flow_all=flow_stats(fl), flow_face=flow_stats(fl, REGIONS[pid]["face"]),
             flow_crops={k: flow_stats(fl, b) for k, b in det.items()},
             mis_p99_crops={k: float(np.percentile(crop(mis, b), 99)) for k, b in det.items()},
             ssim_q_orig=ssim(o, q.astype(np.uint8)), mae_q_orig=mae(o, q.astype(np.uint8)))
    blends = []
    for a in ALPHAS:
        b = ((1 - a) * prog + a * q).clip(0, 255).astype(np.uint8)
        from PIL import Image
        Image.fromarray(b).save(os.path.join(HERE, "blends", f"{pid}_{int(a * 100):03d}.png"))
        blends.append(b)
    r["blend_mis_err_p99"] = {f"{int(a * 100)}%": round(a * float(np.percentile(mis, 99)), 2) for a in ALPHAS}
    rows.append(r)
    full = panel([o] + blends, ["原圖", "程式 100%", "Qwen 25%", "50%", "75%", "Qwen 100%"], 360)
    grids = [full]
    for k, bx in det.items():
        grids.append(panel([crop(o, bx)] + [crop(x, bx) for x in blends],
                           [f"{k}：原圖", "0%", "25%", "50%", "75%", "100%"], 300))
    stack(grids, 4, 2400).save(os.path.join(HERE, "panels", f"B_{pid}.png"))
    print(pid, "done")

json.dump(rows, open(os.path.join(HERE, "metrics_B.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lines = ["| photo | 秒 | Qwen 尺寸 | flow 程式→Qwen p50/p95/p99 全圖 | flow p95 臉 | 各細節區 flow p95 | 錯位誤差 p99（a=100%）各區 | SSIM/MAE Qwen vs 原圖 |",
         "|" + "---|" * 8]
for r in rows:
    fc = ", ".join(f"{k} {v['p95']:.2f}" for k, v in r["flow_crops"].items())
    mc = ", ".join(f"{k} {v:.1f}" for k, v in r["mis_p99_crops"].items())
    lines.append(f"| {r['photo']} | {r['comfy_s']} | {r['qwen']} | {r['flow_all']['p50']:.2f}/{r['flow_all']['p95']:.2f}/{r['flow_all']['p99']:.2f} "
                 f"| {r['flow_face']['p95']:.2f} | {fc} | {mc} | {r['ssim_q_orig']:.3f}/{r['mae_q_orig']:.1f} |")
open(os.path.join(HERE, "metrics_B.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
