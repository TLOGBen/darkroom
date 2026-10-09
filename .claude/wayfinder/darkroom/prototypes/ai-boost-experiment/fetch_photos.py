"""Collect test photos into ./photos and write photos.json. Re-runnable (skips existing files).

Commons photos are 1024px thumbnails; local ones are AI-generated images already in this repo.
Also copies each photo (as PNG) into ComfyUI/input/ as aib_<id>.png for the Qwen runs.
"""
import json, os, shutil, sys, urllib.request
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
sys.path.insert(0, os.path.join(HERE, "..", "llm-pick-experiment"))
from fetch_photos import commons_info, _get, UA  # noqa: E402

OUT = os.path.join(HERE, "photos")
INPUT = os.path.join(ROOT, "runtimes/comfyui/v0.39.0-portable-nvidia/ComfyUI_windows_portable/ComfyUI/input")
LOCAL = [
    ("portrait_studio", "runtimes/comfyui/v0.39.0-portable-nvidia/ComfyUI_windows_portable/ComfyUI/input/portrait_model_denim.png",
     "portrait (studio, AI-generated, profile face)"),
    ("landscape_lighthouse", "outputs/comfyui/qw/2026-10-04-lr-latency-busy_00001_.png", "landscape (stormy coast, AI-generated)"),
]
COMMONS = [
    ("portrait_laughing", "File:Laughing woman.jpg", "portrait (real, frontal face)"),
    ("portrait_oldman", "File:Old man face.jpg", "portrait (real, close-up, skin texture)"),
    ("fog_karst", "File:Green karst peaks seen from the top of Mount Nam Xay a sunny morning with fog Vang Vieng Laos.jpg",
     "fog / low contrast landscape"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for pid, rel, subj in LOCAL:
        dst = os.path.join(OUT, pid + ".png")
        if not os.path.exists(dst):
            Image.open(os.path.join(ROOT, rel)).convert("RGB").save(dst)
        rows.append(dict(id=pid, file=os.path.basename(dst), subject=subj, source=rel, license="local (generated in this repo)"))
    for pid, title, subj in COMMONS:
        dst = os.path.join(OUT, pid + ".png")
        thumb, desc, lic, artist = commons_info(title)
        if not os.path.exists(dst):
            tmp = dst + ".jpg"
            with _get(urllib.request.Request(thumb, headers=UA), 300) as r, open(tmp, "wb") as f:
                f.write(r.read())
            Image.open(tmp).convert("RGB").save(dst)
            os.remove(tmp)
        rows.append(dict(id=pid, file=os.path.basename(dst), subject=subj, source=desc, license=f"{lic}, by {artist}"))
    for r in rows:
        im = Image.open(os.path.join(OUT, r["file"]))
        r["size"] = im.size
        shutil.copy(os.path.join(OUT, r["file"]), os.path.join(INPUT, "aib_" + r["id"] + ".png"))
    with open(os.path.join(HERE, "photos.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(r["id"], r["size"], r["license"])


if __name__ == "__main__":
    main()
