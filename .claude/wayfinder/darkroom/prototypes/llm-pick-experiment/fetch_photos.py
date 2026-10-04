"""Collect the test photos into ./photos and write photos.json (id, file, subject, source, license).

Local: two ComfyUI images from this repo. Remote: Wikimedia Commons "Quality images" (1024px thumbnails).
One synthetic: a Commons food photo with an added blue cast + underexposure, to test problem detection.
Re-runnable: skips files that already exist.
"""
import json
import os
import shutil
import urllib.parse
import urllib.request
import urllib.error

from PIL import Image, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
OUT = os.path.join(HERE, "photos")
UA = {"User-Agent": "LocalLLMs-experiment/0.1 (personal research)"}

LOCAL = [
    ("portrait_studio", "runtimes/comfyui/v0.38.0-portable-nvidia/ComfyUI_windows_portable/ComfyUI/input/portrait_model_denim.png",
     "portrait (studio, AI-generated)"),
    ("landscape_lighthouse", "outputs/comfyui/qw/2026-10-04-lr-latency-busy_00001_.png", "landscape (stormy coast, AI-generated)"),
]
COMMONS = [
    ("night_street", "File:Petit Champlain at night, Quebec city.jpg", "night street"),
    ("street_rain", "File:Rainy day at Merchant's Arch, Temple Bar, Dublin.jpg", "street (rainy day)"),
    ("food_breakfast", "File:Full English breakfast at the Chalet Cafe, Cowfold, West Sussex, England.jpg", "food"),
    ("interior_cafe", "File:Vault Café Central Vienna Wien.jpg", "interior (cafe)"),
    ("sunset_kite", "File:Kitesurfer at sunset, Workum, may 2017.jpg", "sunset / backlit"),
    ("portrait_balaclava", "File:Portrait of a young woman wearing a gray balaclava.jpg", "portrait (real, outdoor)"),
    ("_src_food2", "File:Breakfast in Île d'Orléans 072.jpg", "source for synthetic"),
]


def _get(req, timeout):
    import time
    for i in range(6):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(10 * (i + 1))
    raise RuntimeError("rate limited")


def commons_info(title):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
                                "iiprop": "url|extmetadata", "iiurlwidth": 1024,
                                "iiextmetadatafilter": "LicenseShortName|Artist"})
    with _get(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers=UA), timeout=120) as r:
        page = next(iter(json.load(r)["query"]["pages"].values()))
    ii = page["imageinfo"][0]
    m = ii.get("extmetadata", {})
    import re
    artist = re.sub(r"<[^>]+>", "", m.get("Artist", {}).get("value", "")).strip()
    return ii["thumburl"], ii["descriptionurl"], m.get("LicenseShortName", {}).get("value", ""), artist


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for pid, rel, subj in LOCAL:
        dst = os.path.join(OUT, pid + os.path.splitext(rel)[1])
        if not os.path.exists(dst):
            shutil.copy(os.path.join(ROOT, rel), dst)
        rows.append(dict(id=pid, file=os.path.basename(dst), subject=subj, source=rel, license="local (generated in this repo)"))
    for pid, title, subj in COMMONS:
        dst = os.path.join(OUT, pid + ".jpg")
        thumb, desc, lic, artist = commons_info(title)
        if not os.path.exists(dst):
            with _get(urllib.request.Request(thumb, headers=UA), 300) as r, open(dst, "wb") as f:
                f.write(r.read())
        rows.append(dict(id=pid, file=os.path.basename(dst), subject=subj, source=desc, license=f"{lic}, by {artist}"))
    # synthetic problem photo: blue cast + -1 EV-ish + low contrast
    src = next(r for r in rows if r["id"] == "_src_food2")
    dst = os.path.join(OUT, "food_bluecast_dark.jpg")
    if not os.path.exists(dst):
        im = Image.open(os.path.join(OUT, src["file"])).convert("RGB")
        r_, g_, b_ = im.split()
        im = Image.merge("RGB", (r_.point(lambda v: v * 0.66), g_.point(lambda v: v * 0.9), b_.point(lambda v: min(255, v * 1.3 + 25))))
        im = ImageEnhance.Brightness(im).enhance(0.55)
        im = ImageEnhance.Contrast(im).enhance(0.8)
        im.save(dst, quality=92)
    rows.append(dict(id="food_bluecast_dark", file="food_bluecast_dark.jpg", subject="food (synthetic problem: blue cast + underexposed + flat)",
                     source=f"derived from {src['source']} by fetch_photos.py", license=src["license"] + " (modified)"))
    rows = [r for r in rows if not r["id"].startswith("_")] + [src]
    with open(os.path.join(HERE, "photos.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(r["id"], r["license"])


if __name__ == "__main__":
    main()
