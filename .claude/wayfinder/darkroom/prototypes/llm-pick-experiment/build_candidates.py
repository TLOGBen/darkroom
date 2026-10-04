"""Build candidates.json: for each photo, 18 Lightroom presets (with describe() text at 100%) from mixed groups.

Per photo: 2 presets from each of 2 "on-topic" groups (4) + 1 from each of 12 top-level categories + 2 random = 18.
Deterministic (random.Random seeded by the photo id). Same set is given to both models.
"""
import importlib.util
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
NODE = os.path.join(ROOT, "projects", "comfyui", "custom_nodes", "ComfyUI-LightroomXMP", "__init__.py")
os.environ.setdefault("LIGHTROOM_PRESET_DIR", os.path.join(ROOT, "artifact", "11_preset", "xmp"))

spec = importlib.util.spec_from_file_location("lightroom_xmp", NODE)
lx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lx)

ON_TOPIC = {
    "portrait_studio": ["風格 - 人像聚焦", "風格 - 質感棚拍"],
    "landscape_lighthouse": ["自然 - 海洋魄力", "風格 - 戲劇性"],
    "night_street": ["城市 - 燈光 - 霓虹", "時間 - 黑夜"],
    "street_rain": ["電影 - 室外街道", "城市 - 柏油 - 城市街景"],
    "food_breakfast": ["物件 - 食物 - 美食專家", "物件 - 食物 - 午餐"],
    "interior_cafe": ["城市 - 室內設計", "顏色 - 經典歐式建築棕"],
    "sunset_kite": ["顏色 - 黃金日落", "自然 - 海島"],
    "portrait_balaclava": ["風格 - 皮膚強調", "人物 - 女人"],
    "food_bluecast_dark": ["物件 - 食物 - 暗色主題", "物件 - 食物 - 經典"],
}
TOP = ["顏色", "電影", "自然", "城市", "器材", "復古", "黑白", "風格", "地區", "時間", "物件", "人物"]
BW_GROUPS = {"顏色 - 黑與白", "顏色 - 時尚黑白", "顏色 - 經典電影灰色"}


def main():
    presets = lx._presets()  # {"group / name": path}
    by_group = {}
    for label, path in presets.items():
        g = label.split(" / ")[0] if " / " in label else ""
        by_group.setdefault(g, []).append(label)
    photos = [p for p in json.load(open(os.path.join(HERE, "photos.json"), encoding="utf-8")) if not p["id"].startswith("_")]
    out = {}
    for ph in photos:
        rng = random.Random(ph["id"])
        chosen = []
        for g in ON_TOPIC[ph["id"]]:
            chosen += rng.sample(sorted(by_group[g]), 2)
        used_groups = set(ON_TOPIC[ph["id"]])
        for top in TOP:
            if top == "黑白":
                pool = [g for g in by_group if g in BW_GROUPS]
            else:
                pool = [g for g in by_group if g.split(" - ")[0] == top and g not in used_groups and g not in BW_GROUPS]
            g = rng.choice(sorted(pool))
            used_groups.add(g)
            chosen.append(rng.choice(sorted(set(by_group[g]) - set(chosen))))
        rest = sorted(set(presets) - set(chosen))
        chosen += rng.sample(rest, 2)
        out[ph["id"]] = [{"key": f"P{i + 1:02d}", "label": lab, "file": os.path.basename(presets[lab]),
                          "on_topic": i < 4, "desc": lx.describe(presets[lab], 100)} for i, lab in enumerate(chosen)]
    with open(os.path.join(HERE, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for pid, cands in out.items():
        print(pid, len(cands), sum(len(c["desc"]) for c in cands), "chars")


if __name__ == "__main__":
    main()
