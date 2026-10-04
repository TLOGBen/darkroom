# -*- coding: utf-8 -*-
"""Lightroom 校正集產生器（可重跑）。

產出：
  1. 合成標準圖（16-bit TIFF，內嵌 sRGB ICC）：syn-tone、syn-detail、syn-color，外加 layout JSON。
  2. 真實照片（Wikimedia Commons CC0）：下載原檔、驗 SHA1、轉 sRGB、縮到長邊 2048 存 JPEG。
  3. 校正用 preset（Lightroom Classic 可匯入的 .xmp，ProcessVersion 11.0），每個滑桿每個取值一個，另打包成 zip。
  4. 方案 A 用的「內嵌設定」圖檔：每張圖 × 每個設定一份，設定寫在檔案自己的 XMP 裡，
     匯入 Lightroom 後全選一次匯出即可。
  5. manifest.csv、expected 檔名清單；--check 可比對 Lightroom 匯出的資料夾少了哪些。

用法（在 repo 根目錄）：
  $PY = "runtimes/comfyui/v0.38.0-portable-nvidia/ComfyUI_windows_portable/python_embeded/python.exe"
  & $PY -s <本檔> build                 # 產生全部（預設下載真實照片）
  & $PY -s <本檔> build --no-download   # 不下載；真實照片要自己放進 <out>/sources/
  & $PY -s <本檔> check <Lightroom 匯出資料夾>      # 檔名開頭有沒有 YYYY-MM-DD- 都認得
  & $PY -s <本檔> stamp <匯出資料夾> <YYYY-MM-DD>  # 補日期前綴並搬到 outputs/lr-calibration/
只用 numpy、PIL、cv2（ComfyUI 可攜版內建），不需要安裝套件。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import struct
import sys
import urllib.request
import uuid
import zipfile
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PRESET_SRC = REPO / "artifact" / "11_preset" / "xmp"
DEFAULT_OUT = REPO / "scratch" / "lr-calibration"

W, H = 2048, 1366          # 合成圖尺寸（3:2，約 2.8MP）
REAL_LONG_EDGE = 2048      # 真實照片縮到的長邊
CRS_VERSION = "15.2"       # 照使用者 preset 最常見的值
PROCESS_VERSION = "11.0"   # PV2012 第 5 版（使用者 1277 個 preset 用這個）
UUID_NS = uuid.UUID("6f1c2d0e-5b7a-4c1e-9a43-0c41b7ca1b2e")

# --------------------------------------------------------------------------------------
# 標準圖清單
# --------------------------------------------------------------------------------------
REAL_PHOTOS = {
    # key: (Commons 檔名, 原檔網址, SHA1, 作者, 用途)
    "real-portrait": (
        "File:Woman in a headwrap in Quebec City.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/8/8f/Woman_in_a_headwrap_in_Quebec_City.jpg",
        "f3ccadd76e1c4e1cbcf101a9c4396722f1b925c3", "Wilfredor", "人像：膚色、黑布料暗部、亮背景"),
    "real-landscape": (
        "File:Wetterspitzen (Stubaier Alpen).jpg",
        "https://upload.wikimedia.org/wikipedia/commons/3/39/Wetterspitzen_%28Stubaier_Alpen%29.jpg",
        "d04ca4e2a844a70f318429c435da0c10d70c6231", "Jörg Braukmann", "風景高反差：白雲＋陰影山壁、藍天、綠地"),
    "real-night": (
        "File:Saint Peter's Basilica, Sant'Angelo bridge, by night, Rome, Italy.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/3/36/Saint_Peter%27s_Basilica%2C_Sant%27Angelo_bridge%2C_by_night%2C_Rome%2C_Italy.jpg",
        "a71f468fbca249a32ec13ff7670ff8b92ac69a2f", "Jebulon", "夜景：大片暗部、點光源、鈉燈色"),
    "real-fog": (
        "File:Jetty in fog at Holländaröd 1.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/4/4a/Jetty_in_fog_at_Holl%C3%A4ndar%C3%B6d_1.jpg",
        "fba5d3177b17b4dee3d485211cb8752f7fa80dc2", "W.carter", "低對比霧景：由近到遠霧越濃（去朦朧用）"),
}
# 解析度相依測試用：同一張風景的小／大版本（局部運算的半徑是否跟著圖的尺寸走）
SIZE_VARIANTS = {"real-landscape-1024": ("real-landscape", 1024), "real-landscape-4096": ("real-landscape", 4096)}

SYN = ["syn-tone", "syn-detail", "syn-color"]
REAL = list(REAL_PHOTOS)
ALL7 = SYN + REAL

# 10 個真實 preset（整體驗收）：檔名前 8 碼 → 類型說明
ACCEPTANCE = [
    ("0467a0ad", "霧面：正 Blacks +84＋曲線抬黑"),
    ("132c4109", "霧面：曲線大幅抬黑（0→66）、絕對色溫"),
    ("2970af8c", "膠片：低對比、曲線抬黑、絕對色溫"),
    ("0b8938e5", "膠片＋顆粒 80（顆粒只比統計量）"),
    ("2464bac9", "電影色調：Contrast -75、Whites -61"),
    ("11e359dc", "高反差：Highlights -100、Shadows +60、Whites -88、Blacks +88、Clarity +42"),
    ("2f20566e", "黑白（Embedded profile）"),
    ("999ff87d", "黑白（Default Monochrome profile）、Whites -100、Dehaze +21"),
    ("0ec7b00a", "ProcessVersion 15.4（新版處理流程）"),
    ("0b10ebcc", "ProcessVersion 6.7（PV2010 舊版處理流程）"),
]

# --------------------------------------------------------------------------------------
# 中性設定（所有滑桿歸零；每個校正設定都從這裡改一兩個值）
# --------------------------------------------------------------------------------------
LINEAR_CURVE = [(0, 0), (255, 255)]
HSL_COLORS = ["Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta"]
UNSIGNED = {"ParametricShadowSplit", "ParametricMidtoneSplit", "ParametricHighlightSplit", "Sharpness",
            "SharpenDetail", "SharpenEdgeMasking", "LuminanceSmoothing", "ColorNoiseReduction",
            "SplitToningShadowHue", "SplitToningShadowSaturation", "SplitToningHighlightHue",
            "SplitToningHighlightSaturation", "ColorGradeMidtoneHue", "ColorGradeMidtoneSat",
            "ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeBlending", "GrainAmount", "GrainSize",
            "GrainFrequency", "PostCropVignetteStyle", "PostCropVignetteMidpoint", "PostCropVignetteFeather",
            "AutoLateralCA", "LensProfileEnable", "DefringePurpleAmount", "DefringeGreenAmount"}


def neutral() -> dict:
    s = {
        "WhiteBalance": "As Shot", "IncrementalTemperature": 0, "IncrementalTint": 0,
        "Exposure2012": 0.0, "Contrast2012": 0, "Highlights2012": 0, "Shadows2012": 0,
        "Whites2012": 0, "Blacks2012": 0, "Texture": 0, "Clarity2012": 0, "Dehaze": 0,
        "Vibrance": 0, "Saturation": 0,
        "ParametricShadows": 0, "ParametricDarks": 0, "ParametricLights": 0, "ParametricHighlights": 0,
        "ParametricShadowSplit": 25, "ParametricMidtoneSplit": 50, "ParametricHighlightSplit": 75,
        "Sharpness": 0, "SharpenRadius": "+1.0", "SharpenDetail": 25, "SharpenEdgeMasking": 0,
        "LuminanceSmoothing": 0, "ColorNoiseReduction": 0,
    }
    for kind in ("Hue", "Saturation", "Luminance"):
        for c in HSL_COLORS:
            s[f"{kind}Adjustment{c}"] = 0
    s.update({
        "SplitToningShadowHue": 0, "SplitToningShadowSaturation": 0, "SplitToningHighlightHue": 0,
        "SplitToningHighlightSaturation": 0, "SplitToningBalance": 0,
        "ColorGradeMidtoneHue": 0, "ColorGradeMidtoneSat": 0, "ColorGradeShadowLum": 0,
        "ColorGradeMidtoneLum": 0, "ColorGradeHighlightLum": 0, "ColorGradeBlending": 50,
        "ColorGradeGlobalHue": 0, "ColorGradeGlobalSat": 0, "ColorGradeGlobalLum": 0,
        "AutoLateralCA": 0, "LensProfileEnable": 0, "DefringePurpleAmount": 0, "DefringeGreenAmount": 0,
        "VignetteAmount": 0, "GrainAmount": 0, "PostCropVignetteAmount": 0,
        "ShadowTint": 0, "RedHue": 0, "RedSaturation": 0, "GreenHue": 0, "GreenSaturation": 0,
        "BlueHue": 0, "BlueSaturation": 0,
        "ConvertToGrayscale": "False",
        "ToneCurveName2012": "Linear",
        "CameraProfile": "Embedded",
        "HasSettings": "True",
    })
    for c in HSL_COLORS:
        s[f"GrayMixer{c}"] = 0
    return s


def neutral_curves() -> dict:
    return {k: list(LINEAR_CURVE) for k in ("ToneCurvePV2012", "ToneCurvePV2012Red",
                                             "ToneCurvePV2012Green", "ToneCurvePV2012Blue")}


def fmt(k, v) -> str:
    if isinstance(v, str):
        return v
    if k == "Exposure2012":
        return "0.00" if v == 0 else f"{v:+.2f}"
    v = int(round(v))
    if k in UNSIGNED or v == 0:
        return str(v)
    return f"{v:+d}"


def slug(v) -> str:
    if isinstance(v, float):                      # 曝光：m2p00 = -2.00 EV
        s = f"{abs(v):.2f}".replace(".", "p")
    else:
        s = f"{abs(int(v)):03d}"
    return ("m" if v < 0 else "p") + s


# --------------------------------------------------------------------------------------
# 設定清單（必做 A / 選做 B）
# --------------------------------------------------------------------------------------
class Job:
    def __init__(self, code, group, label, changes, images, tier, curves=None, src_preset=None, note=""):
        self.code, self.group, self.label = code, group, label
        self.changes, self.images, self.tier = changes, images, tier
        self.curves, self.src_preset, self.note = curves or {}, src_preset, note

    @property
    def settings(self):
        s = neutral()
        s.update(self.changes)
        return s

    @property
    def all_curves(self):
        c = neutral_curves()
        c.update(self.curves)
        return c

    @property
    def stem(self):
        return f"{self.code}_{self.label}"


def build_jobs() -> list[Job]:
    jobs: list[Job] = []
    TONE6 = ["syn-tone", "syn-detail"] + REAL
    SL8 = [-100, -75, -50, -25, 25, 50, 75, 100]
    SL4 = [-100, -50, 50, 100]
    EV8 = [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0]
    WB4 = [-50, -25, 25, 50]

    def sweep(gcode, param, values, images, tier, gname=None):
        for i, v in enumerate(values, 1):
            jobs.append(Job(f"{gcode}-{i:02d}", f"校正 - {gname or param}", f"{param}_{slug(v)}",
                            {param: v}, images, tier))

    # ---------------- 必做 ----------------
    jobs.append(Job("A00-01", "校正 - 基準", "Baseline_all0", {}, ALL7, "must",
                    note="全部歸零；確認 Lightroom 對 JPEG/TIFF 的預設是否等於原圖"))
    sweep("A01", "Exposure2012", EV8, ["syn-tone", "syn-color"] + REAL, "must")
    sweep("A02", "Highlights2012", SL8, TONE6, "must")
    sweep("A03", "Shadows2012", SL8, TONE6, "must")
    sweep("A04", "Whites2012", SL8, TONE6, "must")
    sweep("A05", "Blacks2012", SL8, TONE6, "must")
    sweep("A06", "Contrast2012", SL4, ["syn-tone", "syn-color"] + REAL, "must")
    sweep("A07", "Clarity2012", SL4, TONE6, "must")
    sweep("A08", "Dehaze", SL4, ALL7, "must")
    sweep("A09", "Texture", SL4, ["syn-detail", "real-portrait", "real-landscape", "real-fog"], "must")
    combos = [
        ("Hm050_Sp050", {"Highlights2012": -50, "Shadows2012": 50}),
        ("Hm100_Sp100", {"Highlights2012": -100, "Shadows2012": 100}),
        ("Wm050_Bp050", {"Whites2012": -50, "Blacks2012": 50}),
        ("Ep1p00_Hm050", {"Exposure2012": 1.0, "Highlights2012": -50}),
    ]
    for i, (lab, ch) in enumerate(combos, 1):
        jobs.append(Job(f"A10-{i:02d}", "校正 - 組合", f"Combo_{lab}", ch, ["syn-tone"] + REAL, "must",
                        note="檢查效果能不能相加"))
    for i, (prefix, note) in enumerate(ACCEPTANCE, 1):
        f = next(PRESET_SRC.glob(prefix + "*.xmp"), None)
        jobs.append(Job(f"A11-{i:02d}", "校正 - 驗收", f"Preset_{prefix}", {}, ALL7, "must",
                        src_preset=f, note=note))

    # ---------------- 選做 ----------------
    C3 = ["syn-color", "real-portrait", "real-landscape"]
    sweep("B01", "Vibrance", SL4, C3, "optional")
    sweep("B02", "Saturation", SL4, C3, "optional")
    sweep("B03", "IncrementalTemperature", WB4, ["syn-tone", "syn-color", "real-portrait", "real-landscape"],
          "optional", gname="白平衡 Temp")
    sweep("B04", "IncrementalTint", WB4, ["syn-tone", "syn-color", "real-portrait", "real-landscape"],
          "optional", gname="白平衡 Tint")
    n = 0
    for c in HSL_COLORS:
        for kind in ("Hue", "Saturation", "Luminance"):
            for v in (-50, 50):
                n += 1
                p = f"{kind}Adjustment{c}"
                jobs.append(Job(f"B05-{n:02d}", "校正 - HSL", f"{p}_{slug(v)}", {p: v},
                                ["syn-color", "real-portrait"], "optional"))
    cg = []
    for h in (0, 60, 120, 180, 240, 300):
        cg.append((f"ShadowHue{h:03d}_Sat50", {"SplitToningShadowHue": h, "SplitToningShadowSaturation": 50}))
    for h in (0, 60, 120, 180, 240, 300):
        cg.append((f"HighlightHue{h:03d}_Sat50", {"SplitToningHighlightHue": h, "SplitToningHighlightSaturation": 50}))
    for h in (0, 120, 240):
        cg.append((f"MidtoneHue{h:03d}_Sat50", {"ColorGradeMidtoneHue": h, "ColorGradeMidtoneSat": 50}))
    for h in (0, 120, 240):
        cg.append((f"GlobalHue{h:03d}_Sat50", {"ColorGradeGlobalHue": h, "ColorGradeGlobalSat": 50}))
    split = {"SplitToningShadowHue": 220, "SplitToningShadowSaturation": 50,
             "SplitToningHighlightHue": 40, "SplitToningHighlightSaturation": 50}
    cg += [("Split_Bal000_Blend050", {**split}),
           ("Split_Balm50_Blend050", {**split, "SplitToningBalance": -50}),
           ("Split_Balp50_Blend050", {**split, "SplitToningBalance": 50}),
           ("Split_Bal000_Blend100", {**split, "ColorGradeBlending": 100})]
    for i, (lab, ch) in enumerate(cg, 1):
        jobs.append(Job(f"B06-{i:02d}", "校正 - 顏色分級", f"ColorGrade_{lab}", ch,
                        ["syn-tone", "syn-color", "real-portrait"], "optional"))
    curves = [
        ("Matte_lift40", {"ToneCurvePV2012": [(0, 40), (255, 255)]}),
        ("S_medium", {"ToneCurvePV2012": [(0, 0), (64, 52), (128, 128), (192, 204), (255, 255)]}),
        ("S_strong", {"ToneCurvePV2012": [(0, 0), (64, 40), (128, 128), (192, 216), (255, 255)]}),
        ("Film_matteS", {"ToneCurvePV2012": [(0, 36), (60, 56), (128, 128), (196, 204), (255, 236)]}),
        ("White_cap215", {"ToneCurvePV2012": [(0, 0), (255, 215)]}),
        ("Mid_lift160", {"ToneCurvePV2012": [(0, 0), (128, 160), (255, 255)]}),
        ("Red_lift30", {"ToneCurvePV2012Red": [(0, 30), (255, 255)]}),
        ("Blue_fade", {"ToneCurvePV2012Blue": [(0, 20), (128, 120), (255, 235)]}),
    ]
    n = 0
    for lab, cv in curves:
        n += 1
        jobs.append(Job(f"B07-{n:02d}", "校正 - 曲線", f"Curve_{lab}", {"ToneCurveName2012": "Custom"},
                        ["syn-tone", "syn-color", "real-portrait", "real-landscape"], "optional", curves=cv))
    for p in ("ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights"):
        for v in (-50, 50):
            n += 1
            jobs.append(Job(f"B07-{n:02d}", "校正 - 曲線", f"{p}_{slug(v)}", {p: v},
                            ["syn-tone", "syn-color", "real-portrait", "real-landscape"], "optional"))
    n = 0
    for p in ("ShadowTint", "RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation"):
        for v in (-50, 50):
            n += 1
            jobs.append(Job(f"B08-{n:02d}", "校正 - 相機校正", f"{p}_{slug(v)}", {p: v},
                            ["syn-color", "real-portrait"], "optional"))
    vig = {"PostCropVignetteStyle": 1, "PostCropVignetteMidpoint": 50, "PostCropVignetteFeather": 50,
           "PostCropVignetteRoundness": 0, "PostCropVignetteHighlightContrast": 0}
    for i, v in enumerate((-50, 50), 1):
        jobs.append(Job(f"B09-{i:02d}", "校正 - 暗角", f"PostCropVignetteAmount_{slug(v)}",
                        {**vig, "PostCropVignetteAmount": v}, ["syn-tone", "real-portrait", "real-landscape"],
                        "optional"))
    bw = [("BW_mix0", {}), ("BW_Redp50", {"GrayMixerRed": 50}), ("BW_Greenp50", {"GrayMixerGreen": 50}),
          ("BW_Bluem50", {"GrayMixerBlue": -50})]
    for i, (lab, ch) in enumerate(bw, 1):
        jobs.append(Job(f"B10-{i:02d}", "校正 - 黑白", lab, {"ConvertToGrayscale": "True", **ch},
                        ["syn-color", "real-portrait", "real-landscape"], "optional"))
    for i, v in enumerate((25, 50, 100), 1):
        jobs.append(Job(f"B11-{i:02d}", "校正 - 顆粒", f"GrainAmount_{slug(v)}",
                        {"GrainAmount": v, "GrainSize": 25, "GrainFrequency": 50},
                        ["syn-tone", "real-portrait"], "optional", note="顆粒是隨機的，只比統計量"))
    size_tests = [("Highlights2012", -100), ("Shadows2012", 100), ("Clarity2012", 100), ("Dehaze", 100),
                  ("Texture", 100)]
    for i, (p, v) in enumerate(size_tests, 1):
        jobs.append(Job(f"B12-{i:02d}", "校正 - 解析度相依", f"{p}_{slug(v)}", {p: v},
                        list(SIZE_VARIANTS), "optional",
                        note="同設定套在 1024／4096 長邊版本，和 A 組的 2048 版比，看半徑是否隨尺寸縮放"))
    return jobs


# --------------------------------------------------------------------------------------
# XMP 產生
# --------------------------------------------------------------------------------------
def _curve_xml(curves: dict, indent: str) -> str:
    out = []
    for k, pts in curves.items():
        out.append(f"{indent}<crs:{k}>\n{indent} <rdf:Seq>")
        for x, y in pts:
            out.append(f"{indent}  <rdf:li>{x}, {y}</rdf:li>")
        out.append(f"{indent} </rdf:Seq>\n{indent}</crs:{k}>")
    return "\n".join(out)


def _alt(tag, text, indent):
    body = f'<rdf:li xml:lang="x-default">{text}</rdf:li>' if text else '<rdf:li xml:lang="x-default"/>'
    return f"{indent}<crs:{tag}>\n{indent} <rdf:Alt>\n{indent}  {body}\n{indent} </rdf:Alt>\n{indent}</crs:{tag}>"


def preset_name(job: Job, src_name: str | None = None) -> str:
    if src_name:
        return f"{job.code} {src_name}"
    return f"{job.code} {job.label.replace('_', ' ')}"


def preset_xmp(job: Job) -> str:
    """Lightroom Classic 可匯入的 preset（照使用者現有 xmp 的欄位排列）。"""
    head = {
        "PresetType": "Normal", "Cluster": "",
        "UUID": uuid.uuid5(UUID_NS, job.code).hex.upper(),
        "SupportsAmount2": "True", "SupportsAmount": "True", "SupportsColor": "True",
        "SupportsMonochrome": "True", "SupportsHighDynamicRange": "True",
        "SupportsNormalDynamicRange": "True", "SupportsSceneReferred": "True",
        "SupportsOutputReferred": "True", "RequiresRGBTables": "False",
        "CameraModelRestriction": "", "Copyright": "", "ContactInfo": "",
        "Version": CRS_VERSION, "ProcessVersion": PROCESS_VERSION,
    }
    attrs = {**head, **{k: fmt(k, v) for k, v in job.settings.items()}}
    lines = ['<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">',
             ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
             '  <rdf:Description rdf:about=""',
             '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"']
    items = list(attrs.items())
    for i, (k, v) in enumerate(items):
        lines.append(f'   crs:{k}="{v}"' + (">" if i == len(items) - 1 else ""))
    ind = "   "
    lines += [_alt("Name", preset_name(job), ind), _alt("ShortName", "", ind), _alt("SortName", "", ind),
              _alt("Group", job.group, ind), _alt("Description", job.note, ind),
              _curve_xml(job.all_curves, ind),
              "  </rdf:Description>", " </rdf:RDF>", "</x:xmpmeta>", ""]
    return "\n".join(lines)


PRESET_ONLY_ATTRS = ["PresetType", "Cluster", "UUID", "SupportsAmount2", "SupportsAmount", "SupportsColor",
                     "SupportsMonochrome", "SupportsHighDynamicRange", "SupportsNormalDynamicRange",
                     "SupportsSceneReferred", "SupportsOutputReferred", "RequiresRGBTables",
                     "CameraModelRestriction", "Copyright", "ContactInfo", "ShowInPresets", "ShowInQuickActions"]
PRESET_ONLY_ELEMS = ["Name", "ShortName", "SortName", "Group", "Description"]


def acceptance_preset_xmp(job: Job) -> tuple[str, str]:
    """複製真實 preset，只改 Name／Group／UUID（避免跟使用者原本匯入的同一個 preset 撞 UUID）。"""
    t = job.src_preset.read_text(encoding="utf-8")
    m = re.search(r"<crs:Name>.*?<rdf:li[^>]*>([^<]*)<", t, re.S)
    src_name = m.group(1) if m else job.src_preset.stem
    t = re.sub(r'crs:UUID="[^"]*"', f'crs:UUID="{uuid.uuid5(UUID_NS, job.code).hex.upper()}"', t, count=1)
    t = re.sub(r"(<crs:Name>\s*<rdf:Alt>\s*)(<rdf:li[^>]*?)(/>|>[^<]*</rdf:li>)",
               lambda mm: mm.group(1) + '<rdf:li xml:lang="x-default">' + preset_name(job, src_name) + "</rdf:li>",
               t, count=1, flags=re.S)
    t = re.sub(r"(<crs:Group>\s*<rdf:Alt>\s*)(<rdf:li[^>]*?)(/>|>[^<]*</rdf:li>)",
               lambda mm: mm.group(1) + '<rdf:li xml:lang="x-default">' + job.group + "</rdf:li>",
               t, count=1, flags=re.S)
    return t, src_name


def wrap_packet(xmpmeta: str) -> bytes:
    pkt = ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + xmpmeta.strip() + "\n"
           + (" " * 99 + "\n") * 20 + '<?xpacket end="w"?>')
    return pkt.encode("utf-8")


def embedded_xmp(job: Job) -> bytes:
    """寫進圖檔裡的 XMP（Camera Raw 設定，非 preset）：Lightroom 匯入時會讀成這張的編輯設定。"""
    if job.src_preset is not None:
        t = acceptance_preset_xmp(job)[0]
        for a in PRESET_ONLY_ATTRS:
            t = re.sub(rf'\n\s*crs:{a}="[^"]*"', "", t)
        for e in PRESET_ONLY_ELEMS:
            t = re.sub(rf"\s*<crs:{e}>.*?</crs:{e}>", "", t, flags=re.S)
        t = t.replace('crs:HasSettings="True"', 'crs:HasSettings="True"\n   crs:AlreadyApplied="False"', 1)
        t = re.sub(r'\s*x:xmptk="[^"]*"', "", t, count=1)
        return wrap_packet(t)
    attrs = {"Version": CRS_VERSION, "ProcessVersion": PROCESS_VERSION,
             **{k: fmt(k, v) for k, v in job.settings.items()}, "AlreadyApplied": "False"}
    lines = ['<x:xmpmeta xmlns:x="adobe:ns:meta/">',
             ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
             '  <rdf:Description rdf:about=""',
             '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"']
    items = list(attrs.items())
    for i, (k, v) in enumerate(items):
        lines.append(f'   crs:{k}="{v}"' + (">" if i == len(items) - 1 else ""))
    lines += [_curve_xml(job.all_curves, "   "), "  </rdf:Description>", " </rdf:RDF>", "</x:xmpmeta>"]
    return wrap_packet("\n".join(lines))


# --------------------------------------------------------------------------------------
# 檔案寫入：16-bit TIFF（deflate＋predictor，內嵌 ICC 與 XMP）、JPEG 插 XMP
# --------------------------------------------------------------------------------------
_SRGB_ICC = None


def srgb_icc() -> bytes:
    global _SRGB_ICC
    if _SRGB_ICC is None:
        _SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _SRGB_ICC


def tiff16_bytes(img: np.ndarray, xmp: bytes | None = None, rows_per_strip: int = 64) -> bytes:
    """img: HxWx3 uint16。回傳 TIFF 檔內容（little-endian、Adobe Deflate、水平差分 predictor）。"""
    assert img.dtype == np.uint16 and img.ndim == 3 and img.shape[2] == 3
    h, w, _ = img.shape
    diff = img.copy()
    diff[:, 1:, :] = img[:, 1:, :] - img[:, :-1, :]       # uint16 環繞相減＝TIFF predictor 2
    strips = []
    for y in range(0, h, rows_per_strip):
        strips.append(zlib.compress(diff[y:y + rows_per_strip].astype("<u2").tobytes(), 6))
    icc = srgb_icc()
    entries = []  # (tag, type, count, value_bytes)

    def short(v): return struct.pack("<H", v)
    def long_(v): return struct.pack("<I", v)

    n = len(strips)
    entries.append([256, 4, 1, long_(w)])
    entries.append([257, 4, 1, long_(h)])
    entries.append([258, 3, 3, short(16) * 3])
    entries.append([259, 3, 1, short(8)])
    entries.append([262, 3, 1, short(2)])
    entries.append([273, 4, n, b"\0" * 4 * n])      # 之後填
    entries.append([277, 3, 1, short(3)])
    entries.append([278, 4, 1, long_(rows_per_strip)])
    entries.append([279, 4, n, b"".join(long_(len(s)) for s in strips)])
    entries.append([282, 5, 1, long_(300) + long_(1)])
    entries.append([283, 5, 1, long_(300) + long_(1)])
    entries.append([284, 3, 1, short(1)])
    entries.append([296, 3, 1, short(2)])
    entries.append([305, 2, 0, b"lr-calibration make_calibration_set.py\0"])
    entries.append([317, 3, 1, short(2)])
    if xmp:
        entries.append([700, 1, len(xmp), xmp])
    entries.append([34675, 7, len(icc), icc])
    for e in entries:
        if e[1] == 2:
            e[2] = len(e[3])
    ifd_off = 8
    ifd_size = 2 + 12 * len(entries) + 4
    data_off = ifd_off + ifd_size
    blobs = []
    cur = data_off
    # 先排外部資料（>4 bytes），strip 資料最後
    ext_off = {}
    for e in entries:
        if len(e[3]) > 4 and e[0] != 273:
            ext_off[e[0]] = cur
            blobs.append(e[3] + (b"\0" if len(e[3]) % 2 else b""))
            cur += len(blobs[-1])
    so_off = cur
    cur += 4 * n
    strip_offsets = []
    for s in strips:
        strip_offsets.append(cur)
        cur += len(s)
    so_bytes = b"".join(long_(o) for o in strip_offsets)
    out = io.BytesIO()
    out.write(b"II*\0" + long_(ifd_off))
    out.write(short(len(entries)))
    for tag, typ, cnt, val in entries:
        out.write(short(tag) + short(typ) + long_(cnt))
        if tag == 273:
            out.write(long_(so_off) if n > 1 else so_bytes)
        elif len(val) > 4:
            out.write(long_(ext_off[tag]))
        else:
            out.write(val.ljust(4, b"\0"))
    out.write(long_(0))
    for b in blobs:
        out.write(b)
    out.write(so_bytes)
    for s in strips:
        out.write(s)
    return out.getvalue()


def jpeg_with_xmp(jpeg: bytes, xmp: bytes) -> bytes:
    assert jpeg[:2] == b"\xff\xd8"
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp
    assert len(payload) + 2 <= 65535, "XMP 太大，塞不進一個 APP1"
    seg = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    pos = 2
    if jpeg[2:4] == b"\xff\xe0":                       # 放在 JFIF APP0 後面
        pos = 4 + struct.unpack(">H", jpeg[4:6])[0]
    return jpeg[:pos] + seg + jpeg[pos:]


# --------------------------------------------------------------------------------------
# 合成標準圖
# --------------------------------------------------------------------------------------
def lin2srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


BG = float(lin2srgb(0.18))  # 18% 灰（sRGB 約 0.461）


def hsl2rgb(h, s, l):
    import colorsys
    return colorsys.hls_to_rgb((h % 360) / 360.0, l, s)


def chart_tone():
    img = np.full((H, W, 3), BG, np.float64)
    lay = []
    x0, x1 = 32, W - 32
    xs = np.linspace(0, 1, x1 - x0)
    # R1：sRGB 碼值線性漸層 0→1
    img[32:302, x0:x1, :] = xs[None, :, None]
    lay.append({"name": "ramp_srgb", "rect": [x0, 32, x1, 302], "desc": "sRGB 碼值 0→1 沿 x 線性"})
    # R2：21 階（sRGB 碼值 0, 0.05, ... 1.0），相鄰無縫
    n = 21
    edges = np.linspace(x0, x1, n + 1).round().astype(int)
    for i in range(n):
        v = i / 20
        img[334:604, edges[i]:edges[i + 1], :] = v
        lay.append({"name": f"step21_{i:02d}", "rect": [int(edges[i]), 334, int(edges[i + 1]), 604], "srgb": [v] * 3})
    # R3：線性光對數漸層 2^-12 → 1（12 檔）
    img[636:906, x0:x1, :] = lin2srgb(np.power(2.0, -12 + 12 * xs))[None, :, None]
    lay.append({"name": "ramp_log_linear", "rect": [x0, 636, x1, 906], "desc": "線性光 = 2^(-12+12t)，t 沿 x 0→1"})
    # R4：兩端細階（黑端 0..22/255、白端 233..255/255 每 2 碼一階）
    n = 24
    edges = np.linspace(x0, x1, n + 1).round().astype(int)
    for i in range(n):
        code = i * 2 if i < 12 else 255 - (23 - i) * 2
        img[938:1208, edges[i]:edges[i + 1], :] = code / 255
        lay.append({"name": f"endstep_{code:03d}", "rect": [int(edges[i]), 938, int(edges[i + 1]), 1208], "srgb": [code / 255] * 3})
    # R5：獨立色塊（周圍是 18% 灰），sRGB 0.0..1.0 每 0.1
    pw, gap = 120, (x1 - x0 - 11 * 120) // 10
    for i in range(11):
        xa = x0 + i * (pw + gap)
        img[1240:1334, xa:xa + pw, :] = i / 10
        lay.append({"name": f"iso_{i:02d}", "rect": [xa, 1240, xa + pw, 1334], "srgb": [i / 10] * 3})
    return img, lay


def chart_detail():
    rng = np.random.default_rng(20261004)
    img = np.full((H, W, 3), BG, np.float64)
    lay = []
    periods = [2, 4, 8, 16, 32, 64, 128]
    cw, x0 = 280, 44
    rows = [(b, a) for b in (0.15, 0.45, 0.80) for a in (0.03, 0.12)]
    for r, (base, amp) in enumerate(rows):
        y0 = 32 + r * 150
        for c, per in enumerate(periods):
            xa = x0 + c * cw
            xx = np.arange(cw - 16)
            g = base + amp * np.sin(2 * np.pi * xx / per)
            img[y0:y0 + 136, xa:xa + cw - 16, :] = g[None, :, None]
            lay.append({"name": f"grating_b{base:.2f}_a{amp:.2f}_p{per:03d}",
                        "rect": [xa, y0, xa + cw - 16, y0 + 136], "base": base, "amp": amp, "period_px": per})
    # 光暈測試：亮天空＋暗山稜線
    ya, yb = 960, H - 32
    xa, xb = 44, 1000
    img[ya:yb, xa:xb, :] = 0.92
    xs = np.arange(xb - xa)
    ridge = (ya + (yb - ya) * 0.45 + 90 * np.sin(xs / 70) + 40 * np.sin(xs / 17 + 1)
             + np.cumsum(rng.normal(0, 3, xs.size))).astype(int)
    ridge = np.clip(ridge, ya + 20, yb - 20)
    for i, ry in enumerate(ridge):
        img[ry:yb, xa + i, :] = 0.08
    lay.append({"name": "halo_ridge", "rect": [xa, ya, xb, yb], "desc": "上 0.92 亮天空、下 0.08 暗山，稜線不規則"})
    # 細雜訊（高頻）與中頻紋理
    xc = 1040
    noise = 0.5 + rng.normal(0, 0.03, (yb - ya, 460))
    img[ya:yb, xc:xc + 460, :] = noise[:, :, None]
    lay.append({"name": "noise_fine", "rect": [xc, ya, xc + 460, yb], "base": 0.5, "sigma": 0.03})
    raw = rng.normal(0, 1, (yb - ya, 500)).astype(np.float32)
    import cv2
    mid = cv2.GaussianBlur(raw, (0, 0), 3) - cv2.GaussianBlur(raw, (0, 0), 9)
    mid = 0.5 + 0.06 * mid / (mid.std() + 1e-9)
    img[ya:yb, xc + 480:xc + 980, :] = mid[:, :, None]
    lay.append({"name": "texture_mid", "rect": [xc + 480, ya, xc + 980, yb], "base": 0.5,
                "desc": "DoG(σ3−σ9) 帶通雜訊，標準差 0.06"})
    return img, lay


COLORCHECKER = [  # X-Rite 公布的 sRGB 近似值（D50→sRGB，8-bit）
    ("dark_skin", 115, 82, 68), ("light_skin", 194, 150, 130), ("blue_sky", 98, 122, 157),
    ("foliage", 87, 108, 67), ("blue_flower", 133, 128, 177), ("bluish_green", 103, 189, 170),
    ("orange", 214, 126, 44), ("purplish_blue", 80, 91, 166), ("moderate_red", 193, 90, 99),
    ("purple", 94, 60, 108), ("yellow_green", 157, 188, 64), ("orange_yellow", 224, 163, 46),
    ("blue", 56, 61, 150), ("green", 70, 148, 73), ("red", 175, 54, 60),
    ("yellow", 231, 199, 31), ("magenta", 187, 86, 149), ("cyan", 8, 133, 161),
    ("white", 243, 243, 242), ("neutral_8", 200, 200, 200), ("neutral_6.5", 160, 160, 160),
    ("neutral_5", 122, 122, 121), ("neutral_3.5", 85, 85, 85), ("black", 52, 52, 52),
]


def chart_color():
    img = np.full((H, W, 3), BG, np.float64)
    lay = []
    ps, g = 160, 24
    for i, (name, r, gg, b) in enumerate(COLORCHECKER):
        cx, cy = i % 6, i // 6
        xa, ya = 40 + cx * (ps + g), 40 + cy * (ps + g)
        img[ya:ya + ps, xa:xa + ps] = (r / 255, gg / 255, b / 255)
        lay.append({"name": f"cc_{i + 1:02d}_{name}", "rect": [xa, ya, xa + ps, ya + ps], "srgb": [r / 255, gg / 255, b / 255]})
    # 膚色 4×4：色相 12/20/28/36°，四種明度
    sl = [(0.45, 0.80), (0.45, 0.65), (0.50, 0.45), (0.45, 0.28)]
    for j, (s, l) in enumerate(sl):
        for i, hue in enumerate((12, 20, 28, 36)):
            rgb = hsl2rgb(hue, s, l)
            xa, ya = 1220 + i * (ps + g), 40 + j * (ps + g)
            img[ya:ya + ps, xa:xa + ps] = rgb
            lay.append({"name": f"skin_h{hue:02d}_s{s:.2f}_l{l:.2f}", "rect": [xa, ya, xa + ps, ya + ps], "srgb": list(rgb)})
    # 色相掃描：36 色相 × 6 列（L 0.30/0.50/0.75 × S 0.5/1.0）
    pw, ph = 54, 80
    for r, (l, s) in enumerate([(l, s) for l in (0.30, 0.50, 0.75) for s in (0.5, 1.0)]):
        ya = 820 + r * 86
        for i in range(36):
            hue = i * 10
            rgb = hsl2rgb(hue, s, l)
            xa = 52 + i * pw
            img[ya:ya + ph, xa:xa + pw - 4] = rgb
            lay.append({"name": f"hue{hue:03d}_s{s:.1f}_l{l:.2f}", "rect": [xa, ya, xa + pw - 4, ya + ph], "srgb": list(rgb)})
    return img, lay


def to_u16(img):
    return np.clip(np.round(img * 65535), 0, 65535).astype(np.uint16)


# --------------------------------------------------------------------------------------
# 真實照片
# --------------------------------------------------------------------------------------
UA = "LocalLLMs-lr-calibration/1.0 (personal research; https://commons.wikimedia.org/wiki/Commons:Reusing_content)"


def fetch_sources(src_dir: Path, download: bool) -> dict:
    src_dir.mkdir(parents=True, exist_ok=True)
    found = {}
    for key, (title, url, sha1, _a, _u) in REAL_PHOTOS.items():
        p = src_dir / f"{key}.jpg"
        if p.exists() and hashlib.sha1(p.read_bytes()).hexdigest() == sha1:
            found[key] = p
            continue
        if not download:
            print(f"[缺] {key}: 請下載 {url} 存成 {p}")
            continue
        print(f"[下載] {key} ← {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            data = urllib.request.urlopen(req, timeout=600).read()
        except Exception as e:  # noqa: BLE001
            print(f"  下載失敗：{e}；請手動下載存成 {p}")
            continue
        got = hashlib.sha1(data).hexdigest()
        if got != sha1:
            print(f"  SHA1 不符（{got} ≠ {sha1}），不採用；請確認 Commons 上的檔案是否換過版本")
            continue
        p.write_bytes(data)
        found[key] = p
    return found


def prepare_real(src: Path, long_edge: int) -> bytes:
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)
    icc = im.info.get("icc_profile")
    im = im.convert("RGB")
    if icc:
        try:
            srcp = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, srcp, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except Exception:  # noqa: BLE001
            pass
    scale = long_edge / max(im.size)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95, subsampling=0, icc_profile=srgb_icc(), optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------------------
def build(args):
    out = Path(args.out).resolve()
    jobs = build_jobs()
    missing_presets = [j.code for j in jobs if j.src_preset is None and j.code.startswith("A11")]
    if missing_presets:
        sys.exit(f"找不到驗收用 preset：{missing_presets}（應在 {PRESET_SRC}）")

    # 1) 合成圖 → prototypes/calibration/charts/
    charts_dir = HERE / "charts"
    charts_dir.mkdir(exist_ok=True)
    base_imgs = {}   # key -> (ext, bytes_without_xmp, encoder)
    layouts = {}
    for key, fn in (("syn-tone", chart_tone), ("syn-detail", chart_detail), ("syn-color", chart_color)):
        img, lay = fn()
        u16 = to_u16(img)
        base_imgs[key] = ("tif", u16)
        (charts_dir / f"{key}.tif").write_bytes(tiff16_bytes(u16))
        layouts[key] = {"size": [W, H], "encoding": "sRGB, 16-bit, 值 0..1 = 0..65535", "patches": lay}
        print(f"[合成] {key}.tif")
    (charts_dir / "layout.json").write_text(json.dumps(layouts, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2) 真實照片
    srcs = fetch_sources(out / "sources", not args.no_download)
    for key, p in srcs.items():
        base_imgs[key] = ("jpg", prepare_real(p, REAL_LONG_EDGE))
    if "real-landscape" in srcs:
        for vkey, (k, le) in SIZE_VARIANTS.items():
            base_imgs[vkey] = ("jpg", prepare_real(srcs[k], le))

    # 3) preset xmp（方案 B）→ prototypes/calibration/presets/
    pdir = HERE / "presets"
    for tier in ("must", "optional"):
        (pdir / tier).mkdir(parents=True, exist_ok=True)
        for f in (pdir / tier).glob("*.xmp"):
            f.unlink()
    src_names = {}
    for j in jobs:
        if j.src_preset is not None:
            text, src_names[j.code] = acceptance_preset_xmp(j)
        else:
            text = preset_xmp(j)
        (pdir / j.tier / f"{j.stem}.xmp").write_text(text, encoding="utf-8")
    for tier in ("must", "optional"):
        with zipfile.ZipFile(pdir / f"presets_{tier}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted((pdir / tier).glob("*.xmp")):
                z.write(f, f.name)

    # 4) 方案 A：內嵌設定圖檔；方案 B：乾淨的原圖
    plan_a = out / "planA"
    plan_b = out / "planB_base"
    for d in (plan_a / "must", plan_a / "optional", plan_b):
        d.mkdir(parents=True, exist_ok=True)
    for key, (ext, data) in base_imgs.items():
        p = plan_b / f"{key}.{ext}"
        p.write_bytes(tiff16_bytes(data) if ext == "tif" else data)
    rows, expected = [], {"must": [], "optional": []}
    skipped = set()
    for j in jobs:
        xmp = embedded_xmp(j)
        for key in j.images:
            if key not in base_imgs:
                skipped.add(key)
                continue
            ext, data = base_imgs[key]
            name = f"{j.stem}__{key}"
            fp = plan_a / j.tier / f"{name}.{ext}"
            if args.skip_plan_a:
                pass
            elif ext == "tif":
                fp.write_bytes(tiff16_bytes(data, xmp))
            else:
                fp.write_bytes(jpeg_with_xmp(data, xmp))
            expected[j.tier].append(name)
        changed = {k: fmt(k, v) for k, v in j.changes.items()}
        rows.append({"code": j.code, "tier": j.tier, "group": j.group, "label": j.label,
                     "changes": json.dumps(changed, ensure_ascii=False),
                     "curves": json.dumps(j.curves) if j.curves else "",
                     "source_preset": (j.src_preset.name + " / " + src_names.get(j.code, "")) if j.src_preset else "",
                     "images": " ".join(j.images), "n_images": len(j.images), "note": j.note})
    with open(HERE / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    for tier in ("must", "optional"):
        (HERE / f"expected_{tier}.txt").write_text("\n".join(expected[tier]) + "\n", encoding="utf-8")
    src_info = {k: {"commons": v[0], "url": v[1], "sha1": v[2], "author": v[3], "license": "CC0 1.0",
                    "use": v[4]} for k, v in REAL_PHOTOS.items()}
    (HERE / "sources.json").write_text(json.dumps(src_info, ensure_ascii=False, indent=1), encoding="utf-8")

    nm = sum(1 for j in jobs if j.tier == "must")
    no = len(jobs) - nm
    print(f"\n設定數：必做 {nm}、選做 {no}；方案 A 檔數：必做 {len(expected['must'])}、選做 {len(expected['optional'])}")
    if skipped:
        print(f"[注意] 缺少這些標準圖，對應檔案沒產生：{sorted(skipped)}")
    print(f"方案 A 圖檔：{plan_a}\n方案 B 原圖：{plan_b}\npreset：{pdir}")


DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def check(args):
    d = Path(args.render_dir)
    have = {p.stem for p in d.rglob("*") if p.suffix.lower() in (".tif", ".tiff")}
    # 開頭的 YYYY-MM-DD- 日期前綴先去掉；方案 B 的檔名是「<代碼>__<圖名>」，
    # 代碼只有 A02-03 這段；統一成 (代碼, 圖名) 比對
    def key(stem):
        stem = DATE_PREFIX.sub("", stem)
        code = stem.split("_", 1)[0]
        img = stem.rsplit("__", 1)[-1]
        return code, img
    have_k = {key(s) for s in have}
    for tier in ("must", "optional"):
        exp = [s for s in (HERE / f"expected_{tier}.txt").read_text(encoding="utf-8").split() if s]
        miss = [s for s in exp if key(s) not in have_k]
        print(f"{tier}: 應有 {len(exp)}，缺 {len(miss)}")
        for s in miss[:50]:
            print("  缺", s)
    exp_all = {key(s) for t in ("must", "optional")
               for s in (HERE / f"expected_{t}.txt").read_text(encoding="utf-8").split() if s}
    extra = sorted(s for s in have if key(s) not in exp_all)
    if extra:
        print(f"多出來（不在清單裡）{len(extra)} 個，例如：{extra[:5]}")


def stamp(args):
    """把匯出資料夾裡的 TIFF 加上日期前綴，搬到 outputs/lr-calibration/（已有前綴的只搬不重複加）。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        sys.exit("日期格式要是 YYYY-MM-DD")
    src = Path(args.render_dir).resolve()
    dst = Path(args.dest).resolve()
    dst.mkdir(parents=True, exist_ok=True)
    moved = skipped = 0
    for p in sorted(src.glob("*")):
        if p.suffix.lower() not in (".tif", ".tiff"):
            continue
        name = p.name if DATE_PREFIX.match(p.name) else f"{args.date}-{p.name}"
        target = dst / name
        if target.exists():
            print(f"已存在，略過：{target.name}")
            skipped += 1
            continue
        p.rename(target) if not args.copy else target.write_bytes(p.read_bytes())
        moved += 1
    print(f"完成：{moved} 個檔案 → {dst}（略過 {skipped} 個）")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=str(DEFAULT_OUT), help="大檔輸出位置（預設 repo 的 scratch/lr-calibration）")
    b.add_argument("--no-download", action="store_true", help="不下載真實照片")
    b.add_argument("--skip-plan-a", action="store_true", help="不寫方案 A 的大量圖檔（只算清單）")
    c = sub.add_parser("check")
    c.add_argument("render_dir")
    s = sub.add_parser("stamp", help="匯出檔加日期前綴並搬到 outputs/lr-calibration/")
    s.add_argument("render_dir")
    s.add_argument("date", help="渲染日期 YYYY-MM-DD")
    s.add_argument("--dest", default=str(REPO / "outputs" / "lr-calibration"))
    s.add_argument("--copy", action="store_true", help="用複製代替搬移")
    args = ap.parse_args()
    {"build": build, "check": check, "stamp": stamp}[args.cmd](args)


if __name__ == "__main__":
    main()
