"""Part A metrics + side-by-side panels.

For each A job in runs.tsv: Qwen output size vs original (rounding to 32), global phase-correlation shift,
dense-flow misalignment (overall / face), SSIM and MAE vs original (overall / face), edge-alignment F1,
plus the same numbers for the program result and Qwen-vs-program similarity.
Writes metrics_A.json, metrics_A.md and panels/A_<tag>.png (row 1: original | program | Qwen, row 2: face zoom).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import HERE, REGIONS, load, resize_to, crop, ssim, mae, phase_shift, tile_shifts, ecc_align, flow, flow_stats, edge_match, panel, stack
from jobs import jobs

os.makedirs(os.path.join(HERE, "panels"), exist_ok=True)
runs = {l.split("\t")[0]: l.rstrip("\n").split("\t") for l in open(os.path.join(HERE, "runs.tsv"), encoding="utf-8")}
rows = []
for j in jobs():
    if j["part"] not in ("A", "Aneg") or j["tag"] not in runs or not os.path.exists(os.path.join(HERE, "ai", j["tag"] + ".png")):
        continue
    pid = j["photo"]
    o = load(os.path.join(HERE, "photos", f"{pid}.png"))
    H, W = o.shape[:2]
    prog = load(os.path.join(HERE, "prog", f"{pid}_{'neg' if j['part'] == 'Aneg' else 'pos'}.png"))
    q_raw = load(os.path.join(HERE, "ai", j["tag"] + ".png"))
    qh, qw = q_raw.shape[:2]
    q = resize_to(q_raw, W, H)
    face = REGIONS[pid]["face"]
    fl = flow(o, q)
    dx, dy, resp = phase_shift(o, q)
    ts = tile_shifts(o, q)
    qa, M = ecc_align(o, q)
    fla = flow(o, qa)
    r = dict(tag=j["tag"], photo=pid, pe=j["pe"], sampler=j["sampler"], part=j["part"],
             comfy_s=runs[j["tag"]][3], orig=f"{W}x{H}", qwen=f"{qw}x{qh}",
             aspect_err_pct=round(((qw / qh) / (W / H) - 1) * 100, 2),
             shift_dx=round(dx, 2), shift_dy=round(dy, 2), tiles=ts, ecc=M.round(4).tolist(), ssim_aligned=ssim(o, qa), ssim_aligned_face=ssim(crop(o, face), crop(qa, face)), flow_aligned=flow_stats(fla), edge_aligned=edge_match(o, qa),
             flow_all=flow_stats(fl), flow_face=flow_stats(fl, face),
             ssim_q=ssim(o, q), ssim_q_face=ssim(crop(o, face), crop(q, face)),
             ssim_p=ssim(o, prog), ssim_p_face=ssim(crop(o, face), crop(prog, face)),
             ssim_qp=ssim(prog, q), ssim_qp_face=ssim(crop(prog, face), crop(q, face)),
             mae_q=mae(o, q), mae_q_face=mae(crop(o, face), crop(q, face)),
             mae_p=mae(o, prog), mae_p_face=mae(crop(o, face), crop(prog, face)),
             edge_q=edge_match(o, q), edge_p=edge_match(o, prog))
    rows.append(r)
    top = panel([o, prog, q], ["原圖", "程式近似", f"Qwen pe{j['pe']} s{j['sampler']}"], 520)
    bot = panel([crop(o, face), crop(prog, face), crop(q, face)], ["原圖（臉／主體放大）", "程式", "Qwen"], 520)
    stack([top, bot], 0, 1800).save(os.path.join(HERE, "panels", f"A_{j['tag']}.png"))
    print(j["tag"], "done")

json.dump(rows, open(os.path.join(HERE, "metrics_A.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
hdr = ("| tag | 秒 | 原圖→Qwen 尺寸 | 比例誤差% | 位移 dx,dy（區塊比對中位數）| 區塊 dx 範圍 | 縮放 sx,sy | flow p50/p95 全圖 | flow p95 臉 | SSIM Qwen 全/臉 | SSIM 程式 全/臉 "
       "| SSIM Qwen↔程式 全/臉 | MAE Qwen 全/臉 | MAE 程式 全/臉 | 邊緣 F1 Qwen/程式 |\n|" + "---|" * 15)
lines = [hdr]
for r in rows:
    lines.append(f"| {r['tag']} | {r['comfy_s']} | {r['orig']}→{r['qwen']} | {r['aspect_err_pct']} | {r['tiles']['dx']:.0f},{r['tiles']['dy']:.0f} | {r['tiles']['dx_range'][0]:.0f}~{r['tiles']['dx_range'][1]:.0f} | {r['tiles']['sx']:.3f},{r['tiles']['sy']:.3f} "
                 f"| {r['flow_all']['p50']:.2f}/{r['flow_all']['p95']:.2f} | {r['flow_face']['p95']:.2f} "
                 f"| {r['ssim_q']:.3f}/{r['ssim_q_face']:.3f} | {r['ssim_p']:.3f}/{r['ssim_p_face']:.3f} "
                 f"| {r['ssim_qp']:.3f}/{r['ssim_qp_face']:.3f} | {r['mae_q']:.1f}/{r['mae_q_face']:.1f} | {r['mae_p']:.1f}/{r['mae_p_face']:.1f} "
                 f"| {r['edge_q']:.3f}/{r['edge_p']:.3f} | {r['ssim_aligned']:.3f}/{r['ssim_aligned_face']:.3f} | {r['flow_aligned']['p95']:.2f} | {r['edge_aligned']:.3f} |")
open(os.path.join(HERE, "metrics_A.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
