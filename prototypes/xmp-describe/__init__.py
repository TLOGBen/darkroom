"""
Lightroom preset（.xmp）→ 文字描述，給 PE 寫修圖提示詞用（7 萬事通「套用 Lightroom preset」模式）。

只讀 xmp、不改圖：把非零的設定（基本、曲線、HSL、分離色調／顏色分級、校正、效果）轉成英文描述，
每項附上數值與「輕微／明顯／強烈」這類程度詞，再由 PE 看著照片把它寫成「這張照片要變成什麼樣子」。
強度照 Lightroom 的 Amount：每個數值乘上強度，曲線點往直線內插。

preset 資料夾預設是 repo 的 artifact/11_preset/xmp（往上找到含 artifact/ 的那層），環境變數 LIGHTROOM_PRESET_DIR 可改。
"""
import glob
import os
import re

TAG = "[LightroomXMP]"


def _preset_dir():
    d = os.environ.get("LIGHTROOM_PRESET_DIR")
    if d:
        return d
    cur = os.path.dirname(os.path.abspath(__file__))
    while True:
        cand = os.path.join(cur, "artifact", "11_preset", "xmp")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            return ""
        cur = parent


def _lang_alt(text, tag):
    m = re.search(rf"<crs:{tag}>.*?<rdf:li[^>]*>([^<]*)</rdf:li>", text, re.S)
    return m.group(1).strip() if m else ""


_CACHE = {"dir": None, "map": {}}


def _presets():
    """{選單標籤: 檔案路徑}；標籤＝「群組 / 名稱」，重名時補檔名前 6 碼。"""
    d = _preset_dir()
    if _CACHE["dir"] == d:
        return _CACHE["map"]
    found = {}
    for path in sorted(glob.glob(os.path.join(d, "**", "*.xmp"), recursive=True)):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        group, name = _lang_alt(text, "Group"), _lang_alt(text, "Name") or os.path.splitext(os.path.basename(path))[0]
        label = f"{group} / {name}" if group else name
        if label in found:
            label = f"{label} [{os.path.basename(path)[:6]}]"
        found[label] = path
    _CACHE.update(dir=d, map=dict(sorted(found.items())))
    return _CACHE["map"]


def _num(attrs, key):
    v = attrs.get(key)
    try:
        return float(v) if v is not None else 0.0
    except ValueError:
        return 0.0


def _degree(v, scale=100.0):
    a = abs(v) / scale
    return "slightly" if a < 0.15 else "moderately" if a < 0.4 else "strongly" if a < 0.7 else "very strongly"


def _hue_name(h):
    names = [(15, "red"), (40, "orange"), (65, "yellow"), (90, "yellow-green"), (150, "green"), (190, "cyan"),
             (215, "cyan-blue"), (250, "blue"), (285, "violet"), (330, "magenta"), (360, "red")]
    h %= 360
    return next(n for limit, n in names if h < limit)


def _signed(v, digits=0):
    return f"{v:+.{digits}f}"


def _curve(text, tag, k):
    m = re.search(rf"<crs:{tag}>\s*<rdf:Seq>(.*?)</rdf:Seq>", text, re.S)
    if not m:
        return None
    pts = [tuple(float(x) for x in p.split(",")) for p in re.findall(r"<rdf:li>([^<]*)</rdf:li>", m.group(1))]
    pts = [(x, x + (y - x) * k) for x, y in pts]          # 強度：往直線內插
    if all(abs(x - y) < 1 for x, y in pts):
        return None

    def at(x):
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                return y0 + (y1 - y0) * (x - x0) / max(x1 - x0, 1e-6)
        return x
    bits = []
    if pts[0][1] > 4:
        bits.append(f"blacks lifted to {pts[0][1]:.0f}/255 (faded, matte shadows)")
    if pts[-1][1] < 251:
        bits.append(f"whites capped at {pts[-1][1]:.0f}/255 (soft, dimmed highlights)")
    lo, hi = at(64) - 64, at(192) - 192
    if lo < -4 and hi > 4:
        bits.append("S-shaped (more midtone contrast)")
    elif lo > 4 and hi < -4:
        bits.append("inverse S (flatter midtones)")
    elif lo > 4 or hi > 4:
        bits.append(f"brightened ({'shadows' if lo > hi else 'highlights'} raised)")
    elif lo < -4 or hi < -4:
        bits.append(f"darkened ({'shadows' if lo < hi else 'highlights'} lowered)")
    return ", ".join(bits) or "gently reshaped"


def describe(path, strength):
    text = open(path, encoding="utf-8", errors="replace").read()
    attrs = dict(re.findall(r'crs:(\w+)="([^"]*)"', text))
    k = strength / 100.0

    def val(key):
        return _num(attrs, key) * k
    group, name = _lang_alt(text, "Group"), _lang_alt(text, "Name")
    lines = [f'Lightroom preset "{name}"' + (f' (category: {group})' if group else "") + f", applied at {strength:.0f}% strength."]

    basic = []
    ev = val("Exposure2012")
    if abs(ev) >= 0.05:
        basic.append(f"exposure {_signed(ev, 2)} EV ({'brighter' if ev > 0 else 'darker'} overall)")
    for key, label, pos, neg in (("Contrast2012", "contrast", "punchier", "flatter"),
                                 ("Highlights2012", "highlights", "brighter highlights", "highlights pulled down and recovered"),
                                 ("Shadows2012", "shadows", "shadows opened up", "deeper shadows"),
                                 ("Whites2012", "whites", "brighter whites", "whites dimmed, no pure white"),
                                 # Lightroom 的黑色：正值＝抬黑（變灰、霧面），負值＝壓黑（2026-10-04 修正：原本寫反）
                                 ("Blacks2012", "blacks", "blacks lifted (faded, matte, no pure black)", "deeper, crushed blacks"),
                                 ("Texture", "texture", "more fine surface detail", "smoother surfaces"),
                                 ("Clarity2012", "clarity", "more midtone local contrast and grit", "softer, dreamier midtones"),
                                 ("Dehaze", "dehaze", "less haze, deeper colours", "added haze and glow"),
                                 ("Vibrance", "vibrance", "muted colours boosted", "muted colours reduced"),
                                 ("Saturation", "saturation", "more saturated", "less saturated")):
        v = val(key)
        if abs(v) >= 3:
            basic.append(f"{label} {_signed(v)} ({_degree(v)} {pos if v > 0 else neg})")
    for key, label, pos, neg in (("IncrementalTemperature", "white balance temperature", "warmer", "cooler"),
                                 ("IncrementalTint", "white balance tint", "more magenta", "more green")):
        v = val(key)
        if abs(v) >= 3:
            basic.append(f"{label} {_signed(v)} ({_degree(v)} {pos if v > 0 else neg})")
    if basic:
        lines.append("Tone and presence: " + "; ".join(basic) + ".")

    curves = []
    par = [(lab, val(key)) for key, lab in (("ParametricShadows", "shadows"), ("ParametricDarks", "darks"),
                                           ("ParametricLights", "lights"), ("ParametricHighlights", "highlights"))]
    par = [f"{lab} {_signed(v)}" for lab, v in par if abs(v) >= 3]
    if par:
        curves.append("parametric curve " + ", ".join(par))
    for tag, lab in (("ToneCurvePV2012", "master"), ("ToneCurvePV2012Red", "red channel"),
                     ("ToneCurvePV2012Green", "green channel"), ("ToneCurvePV2012Blue", "blue channel")):
        c = _curve(text, tag, k)
        if c:
            curves.append(f"{lab} curve: {c}")
    if curves:
        lines.append("Tone curve: " + "; ".join(curves) + ".")

    hsl = []
    for col in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta"):
        h, s, l = val(f"HueAdjustment{col}"), val(f"SaturationAdjustment{col}"), val(f"LuminanceAdjustment{col}")
        bits = []
        if abs(h) >= 5:
            bits.append(f"hue {_signed(h)} (shifted toward {'the next hue' if h > 0 else 'the previous hue'})")
        if abs(s) >= 5:
            bits.append(f"saturation {_signed(s)} ({_degree(s)} {'richer' if s > 0 else 'more muted'})")
        if abs(l) >= 5:
            bits.append(f"luminance {_signed(l)} ({_degree(l)} {'lighter' if l > 0 else 'darker'})")
        if bits:
            hsl.append(f"{'aquas/cyans' if col == 'Aqua' else col.lower() + 's'}: " + ", ".join(bits))
    if hsl:
        lines.append("Per-colour (HSL): " + "; ".join(hsl) + ". Hue order is red → orange → yellow → green → aqua → blue → purple → magenta.")

    grade = []
    for zone, hk, sk in (("shadows", "SplitToningShadowHue", "SplitToningShadowSaturation"),
                         ("highlights", "SplitToningHighlightHue", "SplitToningHighlightSaturation"),
                         ("midtones", "ColorGradeMidtoneHue", "ColorGradeMidtoneSat"),
                         ("overall", "ColorGradeGlobalHue", "ColorGradeGlobalSat")):
        s = val(sk)
        if s >= 3:
            hue = _num(attrs, hk)
            grade.append(f"{zone} tinted {_hue_name(hue)} (hue {hue:.0f}°, strength {s:.0f}/100, {_degree(s)})")
    bal = val("SplitToningBalance")
    if grade and abs(bal) >= 10:
        grade.append(f"balance {_signed(bal)} (favouring {'highlights' if bal > 0 else 'shadows'})")
    if grade:
        lines.append("Colour grading (split toning): " + "; ".join(grade) + ".")

    calib = []
    for col in ("Red", "Green", "Blue"):
        h, s = val(f"{col}Hue"), val(f"{col}Saturation")
        bits = [f"hue {_signed(h)}" for _ in [0] if abs(h) >= 5] + [f"saturation {_signed(s)}" for _ in [0] if abs(s) >= 5]
        if bits:
            calib.append(f"{col.lower()} primary " + ", ".join(bits))
    if calib:
        lines.append("Camera calibration (shifts the whole palette): " + "; ".join(calib) + ".")

    fx = []
    vig = val("PostCropVignetteAmount")
    if abs(vig) >= 3:
        fx.append(f"vignette {_signed(vig)} ({_degree(vig)} {'brighter' if vig > 0 else 'darker'} corners)")
    grain = val("GrainAmount")
    if grain >= 3:
        size = _num(attrs, "GrainSize")
        fx.append(f"film grain {grain:.0f}/100 ({_degree(grain)}, {'coarse' if size > 40 else 'fine'} grain)")
    if fx:
        lines.append("Effects: " + "; ".join(fx) + ".")

    notes = []
    look = re.search(r'<crs:Look>\s*<rdf:Description[^>]*crs:Name="([^"]*)"', text, re.S)
    if look:
        notes.append(f'it also uses Adobe\'s built-in look "{look.group(1)}" (not described here)')
    if "MaskGroupBasedCorrections" in text:
        notes.append("it contains local masked adjustments (not described here)")
    if notes:
        lines.append("Note: " + "; ".join(notes) + ".")
    return "\n".join(lines)


class LightroomXMPDescribe:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "preset": (list(_presets()) or ["（找不到 artifact/11_preset/xmp）"],),
            "strength": ("FLOAT", {"default": 100.0, "min": 0.0, "max": 200.0, "step": 5.0,
                                   "tooltip": "Lightroom 的強度（Amount）：100＝原樣，0＝不套，200＝加倍"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("description",)
    FUNCTION = "run"
    CATEGORY = "image/lightroom"
    DESCRIPTION = "把 Lightroom preset（.xmp）的設定轉成英文文字描述，給 PE 寫修圖提示詞。不處理圖片。"

    def run(self, preset, strength):
        path = _presets().get(preset)
        if path is None:
            raise FileNotFoundError(f"{TAG} 找不到 preset：{preset}")
        return (describe(path, strength),)


NODE_CLASS_MAPPINGS = {"LightroomXMPDescribe": LightroomXMPDescribe}
NODE_DISPLAY_NAME_MAPPINGS = {"LightroomXMPDescribe": "Lightroom preset → 文字描述"}
