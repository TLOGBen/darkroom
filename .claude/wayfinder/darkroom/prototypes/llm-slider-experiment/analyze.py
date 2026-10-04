"""Summarise raw/A and raw/B into results-data.md (numbers only; interpretation goes in results.md).

python -s analyze.py
"""
import glob
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_sliders import ADJ_KEYS, BASIC_INT, HSL_KEYS, WISHES  # noqa: E402

MODELS = {"A": "35B-A3B", "B": "PE-I2I"}
PHOTO_ORDER = ["portrait_studio", "landscape_lighthouse", "night_street", "street_rain", "food_breakfast",
               "interior_cafe", "sunset_kite", "portrait_balaclava", "food_bluecast_dark"]


def load(m):
    recs = {}
    for f in glob.glob(os.path.join(HERE, "raw", m, "*__*.json")):
        r = json.load(open(f, encoding="utf-8"))
        recs[(r["photo"], r["run"])] = r
    summ = os.path.join(HERE, "raw", m, "summary.json")
    return recs, (json.load(open(summ, encoding="utf-8")) if os.path.exists(summ) else {})


def adj(r):
    p = r.get("parsed") or {}
    return p.get("adjustments") or {}


def diag(r):
    p = r.get("parsed") or {}
    return p.get("diagnosis") or {}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 2) if xs else None


# ---- direction checks: (id, description, photo, function(adj, diag) -> bool)
CHECKS = [
    ("bd-exp", "food_bluecast_dark: Exposure2012 > 0", "food_bluecast_dark", lambda a, d: a.get("Exposure2012", 0) > 0),
    ("bd-temp", "food_bluecast_dark: IncrementalTemperature > 0", "food_bluecast_dark", lambda a, d: a.get("IncrementalTemperature", 0) > 0),
    ("bd-con", "food_bluecast_dark: Contrast2012 > 0 or Blacks2012 < 0（反差低要加）", "food_bluecast_dark",
     lambda a, d: a.get("Contrast2012", 0) > 0 or a.get("Blacks2012", 0) < 0),
    ("bd-dwb", "food_bluecast_dark 診斷：白平衡判為 cool", "food_bluecast_dark", lambda a, d: d.get("white_balance") == "cool / blue"),
    ("bd-dexp", "food_bluecast_dark 診斷：曝光判為 under（含 slightly）", "food_bluecast_dark", lambda a, d: "under" in (d.get("exposure") or "")),
    ("sun-temp", "sunset_kite: IncrementalTemperature >= 0（不中和夕陽）", "sunset_kite", lambda a, d: a.get("IncrementalTemperature", 0) >= 0),
    ("sun-hl", "sunset_kite: Highlights2012 <= 0（太陽／天空）", "sunset_kite", lambda a, d: a.get("Highlights2012", 0) <= 0),
    ("night-hl", "night_street: Highlights2012 <= 0（路燈）", "night_street", lambda a, d: a.get("Highlights2012", 0) <= 0),
    ("night-exp", "night_street: Exposure2012 <= +0.7（不把夜景拉成白天）", "night_street", lambda a, d: a.get("Exposure2012", 0) <= 0.7),
]
GLOBAL = [
    ("g-exp", "|Exposure2012| <= 1.5（保守）", lambda a, d, p: abs(a.get("Exposure2012", 0)) <= 1.5),
    ("g-sat", "|Saturation| <= 30（保守）", lambda a, d, p: abs(a.get("Saturation", 0)) <= 30),
    ("g-blk", "沒有『Contrast > +10 且 Blacks > +20』的矛盾組合", lambda a, d, p: not (a.get("Contrast2012", 0) > 10 and a.get("Blacks2012", 0) > 20)),
]


def self_consistency(a, d):
    """list of (rule, ok) implied by the model's own diagnosis."""
    out = []
    e, wb = d.get("exposure") or "", d.get("white_balance") or ""
    if "under" in e:
        out.append(("diag under -> Exposure > 0", a.get("Exposure2012", 0) > 0))
    if "over" in e:
        out.append(("diag over -> Exposure < 0", a.get("Exposure2012", 0) < 0))
    if wb == "cool / blue":
        out.append(("diag cool -> Temp > 0", a.get("IncrementalTemperature", 0) > 0))
    if wb == "green":
        out.append(("diag green -> Tint > 0", a.get("IncrementalTint", 0) > 0))
    if wb == "magenta":
        out.append(("diag magenta -> Tint < 0", a.get("IncrementalTint", 0) < 0))
    if d.get("contrast") == "low":
        out.append(("diag low contrast -> Contrast>0 or Blacks<0 or Dehaze>0",
                    a.get("Contrast2012", 0) > 0 or a.get("Blacks2012", 0) < 0 or a.get("Dehaze", 0) > 0))
    return out


def wish_checks(photo, a, base_mean):
    b = lambda k: base_mean.get(k, 0)
    if photo == "food_breakfast":
        return [("Temp > 0", a.get("IncrementalTemperature", 0) > 0),
                ("Temp > 中性兩次平均", a.get("IncrementalTemperature", 0) > b("IncrementalTemperature")),
                ("Exposure >= 中性平均（明亮）", a.get("Exposure2012", 0) >= b("Exposure2012")),
                ("Saturation <= 0（不過飽和）", a.get("Saturation", 0) <= 0),
                ("Saturation+Vibrance <= 中性平均", a.get("Saturation", 0) + a.get("Vibrance", 0) <= b("Saturation") + b("Vibrance")),
                ("Contrast <= 中性平均（清新＝柔）", a.get("Contrast2012", 0) <= b("Contrast2012"))]
    if photo == "street_rain":
        return [("Temp < 0", a.get("IncrementalTemperature", 0) < 0),
                ("Temp < 中性兩次平均", a.get("IncrementalTemperature", 0) < b("IncrementalTemperature")),
                ("Orange/Yellow 飽和度沒有加（<=0）", a.get("SaturationAdjustmentOrange", 0) <= 0 and a.get("SaturationAdjustmentYellow", 0) <= 0)]
    if photo == "night_street":
        return [("Shadows >= +30", a.get("Shadows2012", 0) >= 30),
                ("Shadows > 中性兩次平均", a.get("Shadows2012", 0) > b("Shadows2012")),
                ("Blacks <= 0（不霧面）", a.get("Blacks2012", 0) <= 0),
                ("Contrast >= -10（不扁平）", a.get("Contrast2012", 0) >= -10)]
    return []


def fmt_adj(a, keys=None, skip_zero=True):
    keys = keys or ADJ_KEYS
    out = []
    for k in keys:
        v = a.get(k)
        if v is None or (skip_zero and v == 0):
            continue
        short = (k.replace("2012", "").replace("Incremental", "").replace("Adjustment", "")
                 .replace("Saturation", "Sat").replace("Luminance", "Lum").replace("Temperature", "Temp"))
        out.append(f"{short} {v:+g}" if isinstance(v, (int, float)) else f"{short} {v}")
    return ", ".join(out) if out else "（全 0）"


def main():
    L = ["# llm-slider-experiment 數字（analyze.py 產生）", ""]
    data = {m: load(m) for m in MODELS}
    # ---- performance & validity
    L += ["## 速度與格式", "", "| | " + " | ".join(MODELS.values()) + " |", "|---|" + "---|" * len(MODELS)]
    rows = {}
    for m, (recs, summ) in data.items():
        rs = list(recs.values())
        rows.setdefault("載入到 /health ok（秒）", []).append(summ.get("load_s"))
        rows.setdefault("VRAM 載入前 → 載入後 → 跑完（MiB）", []).append(
            f"{summ.get('vram_before')} → {summ.get('vram_loaded')} → {summ.get('vram_after_runs')}")
        rows.setdefault("請求數", []).append(len(rs))
        rows.setdefault("每次秒數 平均（最小–最大）", []).append(
            f"{mean([r['wall_s'] for r in rs])}（{min(r['wall_s'] for r in rs) if rs else '-'}–{max(r['wall_s'] for r in rs) if rs else '-'}）")
        rows.setdefault("提示詞 tokens 平均", []).append(mean([r["prompt_n"] for r in rs]))
        rows.setdefault("提示詞處理 tok/s 平均", []).append(mean([r["prompt_tps"] for r in rs]))
        rows.setdefault("生成 tokens 平均", []).append(mean([r["gen_n"] for r in rs]))
        rows.setdefault("生成 tok/s 平均", []).append(mean([r["gen_tps"] for r in rs]))
        rows.setdefault("json.loads 成功", []).append(f"{sum(r['parse_ok'] for r in rs)}/{len(rs)}")
        rows.setdefault("欄位齊全＋範圍合法", []).append(f"{sum(r['valid'] for r in rs)}/{len(rs)}")
        bad = [f"{r['photo']}/{r['run']}: {r['errors']}" for r in rs if not r["valid"]]
        rows.setdefault("不合格內容", []).append("; ".join(bad) or "-")
    for k, v in rows.items():
        L.append(f"| {k} | " + " | ".join(str(x) for x in v) + " |")
    # ---- run-to-run difference
    L += ["", "## 兩次（seed 101 vs 202，中性提示詞）數值差異：各滑桿平均絕對差（9 張平均）", ""]
    keys_show = ["Exposure2012"] + BASIC_INT
    L += ["| 滑桿 | " + " | ".join(MODELS.values()) + " |", "|---|" + "---|" * len(MODELS)]
    diffs = {m: {} for m in MODELS}
    for m, (recs, _) in data.items():
        for k in ADJ_KEYS:
            ds = []
            for p in PHOTO_ORDER:
                r1, r2 = recs.get((p, "base_s101")), recs.get((p, "base_s202"))
                if r1 and r2 and r1["valid"] and r2["valid"]:
                    ds.append(abs(adj(r1)[k] - adj(r2)[k]))
            diffs[m][k] = mean(ds)
    for k in keys_show:
        L.append(f"| {k} | " + " | ".join(str(diffs[m][k]) for m in MODELS) + " |")
    L.append("| HSL 18 鍵平均 | " + " | ".join(str(mean([diffs[m][k] for k in HSL_KEYS])) for m in MODELS) + " |")
    L.append("| 基本 12 鍵（整數）平均 | " + " | ".join(str(mean([diffs[m][k] for k in BASIC_INT])) for m in MODELS) + " |")
    # sign agreement
    L += ["", "兩次正負號一致率（兩次都非 0 的滑桿中，正負號相同的比例；以及兩次『是否為 0』相同的比例）：", ""]
    for m, (recs, _) in data.items():
        same_sign = tot = zero_same = ztot = 0
        for p in PHOTO_ORDER:
            r1, r2 = recs.get((p, "base_s101")), recs.get((p, "base_s202"))
            if not (r1 and r2 and r1["valid"] and r2["valid"]):
                continue
            for k in ADJ_KEYS:
                a1, a2 = adj(r1)[k], adj(r2)[k]
                ztot += 1
                zero_same += (a1 == 0) == (a2 == 0)
                if a1 and a2:
                    tot += 1
                    same_sign += (a1 > 0) == (a2 > 0)
        L.append(f"- {MODELS[m]}：正負號一致 {same_sign}/{tot}（{round(100 * same_sign / tot) if tot else '-'}%）；是否動這個滑桿一致 {zero_same}/{ztot}（{round(100 * zero_same / ztot) if ztot else '-'}%）")
    # diagnosis agreement
    L += ["", "兩次診斷（白平衡／曝光／反差）相同的張數：", ""]
    for m, (recs, _) in data.items():
        c = {"white_balance": 0, "exposure": 0, "contrast": 0}
        n = 0
        for p in PHOTO_ORDER:
            r1, r2 = recs.get((p, "base_s101")), recs.get((p, "base_s202"))
            if r1 and r2 and r1["valid"] and r2["valid"]:
                n += 1
                for k in c:
                    c[k] += diag(r1).get(k) == diag(r2).get(k)
        L.append(f"- {MODELS[m]}：白平衡 {c['white_balance']}/{n}、曝光 {c['exposure']}/{n}、反差 {c['contrast']}/{n}")
    # nonzero count
    L += ["", "每次回應動了幾個滑桿（非 0 個數，31 個中）平均："]
    for m, (recs, _) in data.items():
        L.append(f"- {MODELS[m]}：{mean([sum(1 for k in ADJ_KEYS if adj(r).get(k)) for r in recs.values() if r['valid']])}")
    # ---- direction checks
    L += ["", "## 方向檢查（中性提示詞的 2 次都算）", "", "| 檢查 | " + " | ".join(MODELS.values()) + " |", "|---|" + "---|" * len(MODELS)]
    tot_ok = {m: [0, 0] for m in MODELS}
    for cid, desc, photo, fn in CHECKS:
        cells = []
        for m, (recs, _) in data.items():
            ok = n = 0
            for run in ("base_s101", "base_s202"):
                r = recs.get((photo, run))
                if r and r["valid"]:
                    n += 1
                    ok += bool(fn(adj(r), diag(r)))
            tot_ok[m][0] += ok
            tot_ok[m][1] += n
            cells.append(f"{ok}/{n}")
        L.append(f"| {desc} | " + " | ".join(cells) + " |")
    L.append("| **照片專屬檢查合計** | " + " | ".join(f"**{a}/{b}**" for a, b in tot_ok.values()) + " |")
    for gid, desc, fn in GLOBAL:
        cells = []
        for m, (recs, _) in data.items():
            rs = [r for (p, run), r in recs.items() if run.startswith("base") and r["valid"]]
            ok = sum(bool(fn(adj(r), diag(r), r["photo"])) for r in rs)
            fails = [f"{r['photo']}/{r['run'][-4:]}" for r in rs if not fn(adj(r), diag(r), r["photo"])]
            cells.append(f"{ok}/{len(rs)}" + (f"（違反：{', '.join(fails)}）" if fails else ""))
        L.append(f"| 全部照片：{desc} | " + " | ".join(cells) + " |")
    L += ["", "自我一致（模型自己的診斷 → 自己的數值方向）："]
    for m, (recs, _) in data.items():
        items = []
        for (p, run), r in sorted(recs.items()):
            if r["valid"]:
                for rule, ok in self_consistency(adj(r), diag(r)):
                    items.append((p, run, rule, ok))
        bad = [f"{p}/{run}: {rule}" for p, run, rule, ok in items if not ok]
        L.append(f"- {MODELS[m]}：{sum(ok for *_, ok in items)}/{len(items)}" + (f"；不一致：{'; '.join(bad)}" if bad else ""))
    # ---- wishes
    L += ["", "## 想要／不想要", ""]
    for photo, w in WISHES.items():
        L += [f"### {photo}：想要「{w['want']}」，不想要「{w['avoid']}」", ""]
        for m, (recs, _) in data.items():
            bases = [adj(recs[(photo, f"base_s{s}")]) for s in (101, 202) if (photo, f"base_s{s}") in recs]
            bm = {k: st.mean([b[k] for b in bases]) for k in ADJ_KEYS} if bases else {}
            L.append(f"- **{MODELS[m]}** 中性兩次平均：{fmt_adj({k: round(v, 1) for k, v in bm.items()})}")
            for s in (101, 202):
                r = recs.get((photo, f"{w['tag']}_s{s}"))
                if not r or not r["valid"]:
                    L.append(f"  - seed {s}：無效")
                    continue
                cks = wish_checks(photo, adj(r), bm)
                L.append(f"  - seed {s}（{sum(ok for _, ok in cks)}/{len(cks)}）：" + "、".join(f"{n} {'✓' if ok else '✗'}" for n, ok in cks))
                L.append(f"    - 數值：{fmt_adj(adj(r))}")
                L.append(f"    - intent：{(r['parsed'] or {}).get('intent')}")
        L.append("")
    # ---- per photo
    L += ["## 每張照片（seed 101 / 202）", ""]
    for p in PHOTO_ORDER:
        L += [f"### {p}", ""]
        for m, (recs, _) in data.items():
            for s in (101, 202):
                r = recs.get((p, f"base_s{s}"))
                if not r:
                    continue
                d = diag(r)
                L.append(f"- **{MODELS[m]} s{s}**（{r['wall_s']}s）：{d.get('subject')}｜WB {d.get('white_balance')}｜曝光 {d.get('exposure')}｜反差 {d.get('contrast')}")
                L.append(f"  - 問題：{'; '.join(d.get('main_problems') or [])}")
                L.append(f"  - 數值：{fmt_adj(adj(r))}")
                L.append(f"  - intent：{(r['parsed'] or {}).get('intent')}")
        L.append("")
    open(os.path.join(HERE, "results-data.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote results-data.md")


if __name__ == "__main__":
    main()
