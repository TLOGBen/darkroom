"""Submit every job in jobs.py to a running (headless) ComfyUI, one at a time; skip jobs already in runs.tsv.

usage: python run_ai.py [--only TAG_SUBSTR]
Uses the local copies aio.py / wait.py (so nothing is written into the repo's harness folder) and api/all-in-one.json.
Copies each output to ai/<tag>.png and the /history entry to ai/<tag>.history.json; appends to runs.tsv.
"""
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request
from jobs import jobs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 5))
HOST = "http://127.0.0.1:8188"
TSV = os.path.join(HERE, "runs.tsv")


def get(path):
    return json.loads(urllib.request.urlopen(HOST + path, timeout=30).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    os.makedirs(os.path.join(HERE, "ai"), exist_ok=True)
    done = set()
    if os.path.exists(TSV):
        done = {l.split("\t")[0] for l in open(TSV, encoding="utf-8") if l.strip()}
    else:
        open(TSV, "w", encoding="utf-8").write("tag\tprompt_id\tstatus\tcomfy_s\twall_s\tsteps\toutput\n")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for j in jobs():
        if j["tag"] in done or (a.only and a.only not in j["tag"]):
            continue
        while True:  # stay behind anybody else's work
            q = get("/queue")
            if not q["queue_running"] and not q["queue_pending"]:
                break
            time.sleep(10)
        cmd = [sys.executable, "aio.py", "--tag", j["tag"], "--graph", os.path.join(HERE, "api", "all-in-one.json"),
               "--img", f"1=aib_{j['photo']}.png", "--size", "0", "--sampler", str(j["sampler"]), "--pe", str(j["pe"]),
               "--text", j["text"]]
        if j.get("neg"):
            cmd += ["--neg", j["neg"]]
        t0 = time.time()
        out = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8", env=env)
        print(out.stdout.strip(), out.stderr.strip()[-2000:])
        m = re.search(r"^" + re.escape(j["tag"]) + r" (\S+) ", out.stdout, re.M)
        if not m:
            print("submit failed", j["tag"])
            continue
        pid = m.group(1)
        w = subprocess.run([sys.executable, "wait.py", pid], cwd=HERE, capture_output=True, text=True, encoding="utf-8", env=env)
        wall = time.time() - t0
        print(w.stdout.strip(), w.stderr.strip()[-1000:])
        lines = w.stdout.splitlines()
        status, secs = (lines[0].split() + ["?", "?"])[:2] if lines else ("?", "?")
        steps = next((l[7:] for l in lines if l.startswith("steps:")), "")
        outp = next((l[8:] for l in lines if l.startswith("output:")), "")
        if outp:
            shutil.copy(os.path.join(ROOT, outp), os.path.join(HERE, "ai", j["tag"] + ".png"))
        json.dump(get(f"/history/{pid}"), open(os.path.join(HERE, "ai", j["tag"] + ".history.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        with open(TSV, "a", encoding="utf-8") as f:
            f.write(f"{j['tag']}\t{pid}\t{status}\t{secs}\t{wall:.0f}\t{steps}\t{outp}\n")


if __name__ == "__main__":
    main()
