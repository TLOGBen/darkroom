"""LLM looks at a photo and directly picks Lightroom slider values (no presets, no repaint).

Usage (ComfyUI embedded Python, from repo root or anywhere):
  python -s run_sliders.py --model A          # Qwen3.6-35B-A3B HauhauCS Q4_K_P, thinking off
  python -s run_sliders.py --model B          # PE-I2I Heretic Q8_0, thinking off
  python -s run_sliders.py --model A --only food_bluecast_dark   # subset

Starts its own llama-server (port 8092 default), waits for /health (= load time), then per photo
runs 2 neutral requests (seed 101 / 202, temperature 0.7) and, for the 3 "wish" photos, 2 more
requests with a want / don't-want line. Output format is forced with response_format json_schema.
Every raw response goes to raw/<model>/<photo>__<run>.json; summary in raw/<model>/summary.json.
The server it started is always killed at the end.
"""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
PHOTOS_DIR = os.path.join(HERE, "..", "llm-pick-experiment", "photos")
PHOTOS_JSON = os.path.join(HERE, "..", "llm-pick-experiment", "photos.json")
EXE = os.path.join(ROOT, "runtimes", "llama.cpp", "b11223-cuda", "llama-server.exe")
MODELS = {
    "A": dict(name="Qwen3.6-35B-A3B HauhauCS Q4_K_P",
              m="models/qwen3.6-35b-a3b/hauhaucs-aggressive/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf",
              mmproj="models/qwen3.6-35b-a3b/hauhaucs-aggressive/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf",
              extra=["--chat-template-file", os.path.join(ROOT, "projects", "qwen3.6-35b-a3b", "chat-template.jinja")]),
    "B": dict(name="PE-I2I Heretic Q8_0",
              m="models/qwen-image-2.1/text-encoders/pe-i2i-heretic/pe_i2i_heretic-Q8_0.gguf",
              mmproj="models/qwen-image-2.1/text-encoders/pe-i2i-heretic/pe_i2i_heretic.mmproj-bf16.gguf",
              extra=[]),
}
SEEDS = [101, 202]
SAMPLING = dict(temperature=0.7, top_p=0.9, top_k=20, min_p=0.0)

HSL_COLORS = ["Red", "Orange", "Yellow", "Green", "Aqua", "Blue"]
BASIC_INT = ["Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
             "IncrementalTemperature", "IncrementalTint", "Vibrance", "Saturation",
             "Clarity2012", "Dehaze", "Texture"]
HSL_KEYS = [f"{k}Adjustment{c}" for c in HSL_COLORS for k in ("Hue", "Saturation", "Luminance")]
ADJ_KEYS = ["Exposure2012"] + BASIC_INT + HSL_KEYS

WB_ENUM = ["neutral", "cool / blue", "warm / orange-yellow", "green", "magenta"]
EXP_ENUM = ["underexposed", "slightly underexposed", "normal", "slightly overexposed", "overexposed"]
CON_ENUM = ["low", "normal", "high"]


def build_schema():
    adj_props = {"Exposure2012": {"type": "number", "minimum": -5, "maximum": 5}}
    for k in BASIC_INT + HSL_KEYS:
        adj_props[k] = {"type": "integer", "minimum": -100, "maximum": 100}
    return {
        "type": "object",
        "properties": {
            "diagnosis": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "white_balance": {"type": "string", "enum": WB_ENUM},
                    "exposure": {"type": "string", "enum": EXP_ENUM},
                    "contrast": {"type": "string", "enum": CON_ENUM},
                    "main_problems": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                },
                "required": ["subject", "white_balance", "exposure", "contrast", "main_problems"],
                "additionalProperties": False,
            },
            "adjustments": {"type": "object", "properties": adj_props, "required": ADJ_KEYS,
                            "additionalProperties": False},
            "intent": {"type": "string"},
        },
        "required": ["diagnosis", "adjustments", "intent"],
        "additionalProperties": False,
    }


SYSTEM = ("You are an expert photo retoucher who edits in Adobe Lightroom Classic. "
          "You look at a photo, diagnose its technical problems, and then set Lightroom sliders to fix them. "
          "Answer with exactly one JSON object.")

SLIDER_GUIDE = """Lightroom slider reference (what positive / negative values do):
- Exposure2012 (EV, -5.00..+5.00, decimals allowed): overall brightness in stops. +1.0 = twice as bright. Typical fixes are within -1.5..+1.5.
- Contrast2012 (-100..+100): + = more midtone contrast (punchier), - = flatter.
- Highlights2012: - = recover / darken bright areas (sky, lamps, skin shine); + = brighten them.
- Shadows2012: + = open up / brighten dark areas (recover shadow detail); - = darken shadows.
- Whites2012: sets the white point. + = brighter whites (may clip), - = pull whites down.
- Blacks2012: sets the black point. NEGATIVE = deeper, richer blacks (more punch). POSITIVE = lifts the blacks to grey, a faded / matte / hazy look. Do not use positive Blacks to "add contrast".
- IncrementalTemperature: + = warmer (more yellow/orange, use it to fix a blue/cool cast); - = cooler (bluer, fixes an orange/yellow cast).
- IncrementalTint: + = more magenta (fixes a green cast); - = more green (fixes a magenta cast).
- Vibrance: boosts muted colours more than already-saturated ones, protects skin; - = mutes.
- Saturation: boosts / mutes all colours equally (easy to overdo).
- Clarity2012: + = more local midtone contrast (gritty, crisp); - = softer, glow (flattering for skin).
- Dehaze: + = cuts haze/fog, adds contrast and saturation; - = adds haze.
- Texture: + = accentuates fine detail (skin pores, fabric); - = smooths it.
- HSL per colour (Red, Orange, Yellow, Green, Aqua, Blue):
  HueAdjustment<Color>: shifts that hue toward its neighbour (e.g. Orange - = toward red, + = toward yellow; Blue - = toward aqua, + = toward purple).
  SaturationAdjustment<Color>: + = more saturated, - = less.
  LuminanceAdjustment<Color>: + = brighter, - = darker (e.g. Blue - darkens a blue sky). Orange covers skin tones.
All values except Exposure2012 are integers from -100 to +100; 0 = unchanged."""

TASK = """Edit this photo in two steps.
Step 1 - diagnosis: identify the subject, the white balance (any colour cast), the exposure, the contrast, and list the main problems you actually see in THIS photo.
Step 2 - adjustments: set every slider to fix the problems you diagnosed. Every non-zero value must be justified by your diagnosis or by the requested look; leave sliders at 0 when nothing needs fixing. Be conservative but effective: big enough that the fix is visible, never so strong that the photo looks over-processed. Respect the scene's mood (e.g. do not neutralise a sunset's warmth or brighten a night scene into daylight) unless asked.
Finally, "intent": one sentence describing the look you are aiming for.

{guide}
{wish}"""


def wish_text(w):
    if not w:
        return ""
    return f"\nThe user's request for this photo:\n- WANT: {w['want']}\n- DO NOT WANT: {w['avoid']}\nFollow the request while still fixing real technical problems."


WISHES = {
    "food_breakfast": dict(tag="warm_airy", want="a warm, bright, airy Japanese-style fresh look (日系清新)", avoid="oversaturated colours"),
    "street_rain": dict(tag="cool_cine", want="a cool-toned, cinematic film look", avoid="warm or yellow tones"),
    "night_street": dict(tag="lift_shadows", want="recover the shadows so the dark areas show detail", avoid="a flat, washed-out, matte look"),
}


def image_data_url(path, max_side=1024):
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def http_json(url, payload=None, timeout=900):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def validate(obj):
    """Return list of problems (empty = fully valid against our own rules, incl. ranges)."""
    errs = []
    if not isinstance(obj, dict):
        return ["not an object"]
    d, a = obj.get("diagnosis"), obj.get("adjustments")
    if not isinstance(d, dict):
        errs.append("diagnosis missing")
    else:
        if d.get("white_balance") not in WB_ENUM:
            errs.append("wb enum")
        if d.get("exposure") not in EXP_ENUM:
            errs.append("exposure enum")
        if d.get("contrast") not in CON_ENUM:
            errs.append("contrast enum")
        if not isinstance(d.get("main_problems"), list):
            errs.append("problems not list")
    if not isinstance(a, dict):
        errs.append("adjustments missing")
    else:
        for k in ADJ_KEYS:
            v = a.get(k)
            if k == "Exposure2012":
                if not isinstance(v, (int, float)) or not -5 <= v <= 5:
                    errs.append(f"{k}={v}")
            elif not isinstance(v, int) or isinstance(v, bool) or not -100 <= v <= 100:
                errs.append(f"{k}={v}")
    if not isinstance(obj.get("intent"), str) or not obj.get("intent").strip():
        errs.append("intent")
    return errs


def chat(port, img_url, text, seed, schema, max_tokens=2000):
    payload = dict(messages=[{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_url}},
                                                          {"type": "text", "text": text}]}],
                   max_tokens=max_tokens, stream=False, seed=seed, **SAMPLING,
                   chat_template_kwargs={"enable_thinking": False},
                   response_format={"type": "json_schema", "json_schema": {"name": "lr_edit", "schema": schema}})
    t0 = time.time()
    r = http_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload)
    wall = time.time() - t0
    msg = r["choices"][0]["message"]
    tm = r.get("timings", {})
    return dict(content=msg.get("content") or "", reasoning=msg.get("reasoning_content") or "",
                finish=r["choices"][0].get("finish_reason"), wall_s=round(wall, 2),
                prompt_n=tm.get("prompt_n"), prompt_tps=tm.get("prompt_per_second"),
                gen_n=tm.get("predicted_n"), gen_tps=tm.get("predicted_per_second"))


def start_server(model, port, log_path):
    m = MODELS[model]
    args = [EXE, "-m", os.path.join(ROOT, m["m"]), "--mmproj", os.path.join(ROOT, m["mmproj"]),
            "-dev", "CUDA0", "-c", "32768", "-np", "1", "-fa", "on", "--jinja",
            "--host", "127.0.0.1", "--port", str(port)] + m["extra"]
    log = open(log_path, "w", encoding="utf-8")
    t0 = time.time()
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited early, see {log_path}")
        try:
            if http_json(f"http://127.0.0.1:{port}/health", timeout=5).get("status") == "ok":
                break
        except Exception:
            pass
        if time.time() - t0 > 900:
            proc.kill()
            raise RuntimeError("load timeout")
        time.sleep(0.5)
    return proc, round(time.time() - t0, 1)


def vram_used():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS), required=True)
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--only", default="", help="comma-separated photo ids")
    a = ap.parse_args()
    out_dir = os.path.join(HERE, "raw", a.model)
    os.makedirs(out_dir, exist_ok=True)
    photos = [p for p in json.load(open(PHOTOS_JSON, encoding="utf-8")) if not p["id"].startswith("_")]
    if a.only:
        photos = [p for p in photos if p["id"] in a.only.split(",")]
    schema = build_schema()
    vram0 = vram_used()
    proc, load_s = start_server(a.model, a.port, os.path.join(out_dir, "llama-server.log"))
    vram1 = vram_used()
    print(f"[{a.model}] loaded in {load_s}s (pid {proc.pid}); VRAM {vram0} -> {vram1} MiB", flush=True)
    runs = []
    try:
        for ph in photos:
            img = image_data_url(os.path.join(PHOTOS_DIR, ph["file"]))
            jobs = [(f"base_s{s}", s, None) for s in SEEDS]
            if ph["id"] in WISHES:
                w = WISHES[ph["id"]]
                jobs += [(f"{w['tag']}_s{s}", s, w) for s in SEEDS]
            for run, seed, w in jobs:
                text = TASK.format(guide=SLIDER_GUIDE, wish=wish_text(w))
                r = chat(a.port, img, text, seed, schema)
                try:
                    obj = json.loads(r["content"])
                    parse_ok = True
                except Exception:
                    obj, parse_ok = None, False
                errs = validate(obj) if parse_ok else ["json parse"]
                r.update(photo=ph["id"], run=run, seed=seed, wish=w, parse_ok=parse_ok, errors=errs,
                         valid=not errs, parsed=obj)
                runs.append({k: r[k] for k in ("photo", "run", "seed", "wall_s", "prompt_n", "prompt_tps",
                                               "gen_n", "gen_tps", "parse_ok", "valid", "finish")})
                with open(os.path.join(out_dir, f"{ph['id']}__{run}.json"), "w", encoding="utf-8") as f:
                    json.dump(r, f, ensure_ascii=False, indent=1)
                ex = obj["adjustments"].get("Exposure2012") if parse_ok and isinstance(obj.get("adjustments"), dict) else None
                print(f"  {ph['id']:20s} {run:18s} {r['wall_s']:6.1f}s prompt {r['prompt_n']} gen {r['gen_n']} "
                      f"@{r['gen_tps'] and round(r['gen_tps'], 1)} valid={not errs} {errs[:3]} EV={ex}", flush=True)
        vram2 = vram_used()
    finally:
        proc.kill()
        proc.wait(timeout=60)
        print(f"[{a.model}] server pid {proc.pid} stopped", flush=True)
    summary = dict(model=MODELS[a.model]["name"], load_s=load_s, vram_before=vram0, vram_loaded=vram1,
                   vram_after_runs=vram2, sampling=SAMPLING, seeds=SEEDS, runs=runs)
    if not a.only:
        with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
    else:
        with open(os.path.join(out_dir, f"summary_{a.only.replace(',', '+')}.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
