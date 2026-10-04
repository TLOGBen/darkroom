"""Run the photo-describe / preset-pick experiment against one local vision LLM via llama-server.

Usage (from this folder, system Python 3.13 with Pillow):
  python run_experiment.py --model A --think off      # Qwen3.6-35B-A3B, thinking disabled
  python run_experiment.py --model A --think on
  python run_experiment.py --model B --think off      # PE-I2I Heretic (Qwen-Image 2.1 prompt enhancer)

The script starts its own llama-server (port 8091 by default), waits for /health (= load time),
runs 3 requests per photo (describe, pick, pick with shuffled candidate order), saves every raw
response to raw/<config>/, writes raw/<config>/summary.json, and always kills the server it started.
No grammar / response_format is used: JSON validity is what the model produces from the prompt alone.
"""
import argparse
import base64
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
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
SAMPLING = dict(temperature=0.7, top_p=0.9, top_k=20, min_p=0.0, seed=42)
SYSTEM = "You are a professional photo retoucher who knows Adobe Lightroom presets well. Answer with exactly one JSON object and nothing else: no markdown code fences, no commentary."

DESCRIBE_KEYS = ["subject", "main_subject", "lighting", "color_tone", "contrast", "issues", "style_directions"]
DESCRIBE_PROMPT = """Look at this photo and describe it for a photo editor. Output one JSON object with exactly these keys:
{
  "subject": string,            // genre / what kind of photo (e.g. "portrait", "night street")
  "main_subject": string,       // the main subject and where it is in the frame
  "lighting": string,           // light source, direction, quality, time of day
  "color_tone": string,         // overall palette, white balance, any colour cast
  "contrast": "low" | "medium" | "high",
  "issues": [string],           // concrete technical problems (e.g. "blue colour cast", "underexposed shadows", "blown highlights"); [] if none
  "style_directions": [string]  // 2-4 editing / grading directions that would suit this photo
}"""

PICK_KEYS = ["id", "strength", "reason"]
PICK_PROMPT = """Here are {n} Lightroom preset candidates, each described by its actual settings at 100% strength.

{cands}

Choose the 3 presets that would best improve THIS photo (consider its subject, light and problems; avoid presets that would fight the content).
For each, give a strength from 0 to 150 (% of the preset's amount; 100 = as designed, lower = subtler) and one short reason.
Output one JSON object exactly in this form, best pick first:
{{"picks": [{{"id": <candidate number>, "strength": <integer 0-150>, "reason": "<one sentence>"}}, {{...}}, {{...}}]}}"""


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


def parse_json(text):
    """Return (obj_strict, obj_lenient). strict = json.loads on the whole content; lenient strips fences / extracts {...}."""
    strict = lenient = None
    try:
        strict = json.loads(text.strip())
    except Exception:
        pass
    if strict is not None:
        return strict, strict
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            lenient = json.loads(t[i:j + 1])
        except Exception:
            pass
    return None, lenient


def check_describe(obj):
    return isinstance(obj, dict) and all(k in obj for k in DESCRIBE_KEYS) \
        and isinstance(obj.get("issues"), list) and isinstance(obj.get("style_directions"), list) \
        and obj.get("contrast") in ("low", "medium", "high")


def check_pick(obj, n):
    if not isinstance(obj, dict) or not isinstance(obj.get("picks"), list) or len(obj["picks"]) != 3:
        return False
    ids = []
    for p in obj["picks"]:
        if not isinstance(p, dict) or not all(k in p for k in PICK_KEYS):
            return False
        if not isinstance(p["id"], int) or not 1 <= p["id"] <= n:
            return False
        if not isinstance(p["strength"], (int, float)) or not 0 <= p["strength"] <= 150:
            return False
        ids.append(p["id"])
    return len(set(ids)) == 3


def chat(port, img_url, text, think, max_tokens):
    payload = dict(messages=[{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_url}},
                                                          {"type": "text", "text": text}]}],
                   max_tokens=max_tokens, stream=False, **SAMPLING)
    if think is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": think}
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
        time.sleep(1)
    return proc, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS), required=True)
    ap.add_argument("--think", choices=["on", "off", "default"], default="off")
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--photos", default="", help="comma-separated photo ids (default: all)")
    a = ap.parse_args()
    think = {"on": True, "off": False, "default": None}[a.think]
    cfg = f"{a.model}-think-{a.think}"
    out_dir = os.path.join(HERE, "raw", cfg)
    os.makedirs(out_dir, exist_ok=True)
    photos = [p for p in json.load(open(os.path.join(HERE, "photos.json"), encoding="utf-8")) if not p["id"].startswith("_")]
    if a.photos:
        photos = [p for p in photos if p["id"] in a.photos.split(",")]
    cands = json.load(open(os.path.join(HERE, "candidates.json"), encoding="utf-8"))
    max_tokens = 12000 if think else 2000

    proc, load_s = start_server(a.model, a.port, os.path.join(out_dir, "llama-server.log"))
    print(f"[{cfg}] loaded in {load_s}s (pid {proc.pid})", flush=True)
    results = []
    try:
        props = http_json(f"http://127.0.0.1:{a.port}/props")
        for ph in photos:
            img = image_data_url(os.path.join(HERE, "photos", ph["file"]))
            rec = dict(photo=ph["id"])
            # 1. describe
            r = chat(a.port, img, DESCRIBE_PROMPT, think, max_tokens)
            s, l = parse_json(r["content"])
            r.update(strict_ok=s is not None, lenient_ok=l is not None, schema_ok=check_describe(l), parsed=l)
            rec["describe"] = r
            print(f"  {ph['id']} describe {r['wall_s']}s gen {r['gen_n']} @ {r['gen_tps'] and round(r['gen_tps'], 1)} strict={r['strict_ok']} schema={r['schema_ok']}", flush=True)
            # 2/3. pick, original order then shuffled order
            cl = cands[ph["id"]]
            for run, order in (("pick1", list(range(len(cl)))), ("pick2", random.Random("shuffle-" + ph["id"]).sample(range(len(cl)), len(cl)))):
                listing = "\n\n".join(f"Candidate {i + 1}:\n{cl[o]['desc']}" for i, o in enumerate(order))
                r = chat(a.port, img, PICK_PROMPT.format(n=len(cl), cands=listing), think, max_tokens)
                s, l = parse_json(r["content"])
                ok = check_pick(l, len(cl))
                picks = []
                if isinstance(l, dict) and isinstance(l.get("picks"), list):
                    for p in l["picks"]:
                        if isinstance(p, dict) and isinstance(p.get("id"), int) and 1 <= p["id"] <= len(cl):
                            c = cl[order[p["id"] - 1]]
                            picks.append(dict(key=c["key"], label=c["label"], on_topic=c["on_topic"],
                                              strength=p.get("strength"), reason=p.get("reason")))
                r.update(strict_ok=s is not None, lenient_ok=l is not None, schema_ok=ok, parsed=l,
                         order=[cl[o]["key"] for o in order], picks=picks)
                rec[run] = r
                print(f"  {ph['id']} {run} {r['wall_s']}s prompt {r['prompt_n']} @ {r['prompt_tps'] and round(r['prompt_tps'])} gen {r['gen_n']} @ {r['gen_tps'] and round(r['gen_tps'], 1)} schema={ok} -> {[p['key'] for p in picks]}", flush=True)
            k1 = [p["key"] for p in rec["pick1"]["picks"]]
            k2 = [p["key"] for p in rec["pick2"]["picks"]]
            rec["overlap"] = len(set(k1) & set(k2))
            rec["top1_same"] = bool(k1 and k2 and k1[0] == k2[0])
            results.append(rec)
            with open(os.path.join(out_dir, f"{ph['id']}.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
    finally:
        proc.kill()
        proc.wait(timeout=60)
        print(f"[{cfg}] server pid {proc.pid} stopped", flush=True)
    summary = dict(config=cfg, model=MODELS[a.model]["name"], think=a.think, load_s=load_s, sampling=SAMPLING,
                   chat_template_has_thinking="enable_thinking" in (props.get("chat_template") or ""),
                   photos=[r["photo"] for r in results])
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
