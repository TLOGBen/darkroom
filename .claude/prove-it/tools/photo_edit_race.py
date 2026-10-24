"""Replay hypothesis photo-edit paths P1 / P2 on the real App (HTTP) and the real AI-agent entry (MCP stdio).

Verification scaffolding for /prove-it. Usage:

    <darkroom python> -s .claude/prove-it/tools/photo_edit_race.py --repo <checkout> --out <evidence dir> --path P1|P2

What it starts (and stops again, by the process handles it holds): the App through gated_app.py (a real
`darkroom_app.__main__` server on 127.0.0.1:<free port>, with the order gate described there) and one MCP server
(`python -s -m darkroom_app.mcp_server` through run_module.py, another process, line-delimited JSON-RPC on stdio). Both use a disposable
preset folder (two synthetic xmp files), one synthetic photo and a disposable data_dir, all under <out>/run/;
nothing outside <out> is read or written except the checkout's code.

P1 (rule R1): the App saves edit A (PUT /api/edit), clears it (DELETE /api/edit: A becomes the previous edit), then
presses "restore" (POST /api/edit/restore); the gate stops restore right after it has read the current and the
previous edit; the agent saves edit B (MCP darkroom_edit_set); the gate is released.
P2 (rule R2): the photo has no edit; the App presses "reset to original" (DELETE /api/edit); the gate stops it right
after it has seen "no edit"; the agent saves edit A over MCP; the gate is released.

The agent's call is given 1.5 s to answer while the App is stopped (an answer = it was not blocked), then the gate
is released and its answer awaited. The outcome is read back twice: GET /api/edit from the App and
`python -s -m darkroom_app.cli edit get --json` (a third process, through run_module.py), plus the raw files under data_dir/edits/.
Everything goes to <out>/: transcript.json (every request, response and timing), app.log, mcp.log, cli-*.json,
edits-files.json, verdict.txt. Exit 0 when the run completed (whatever the verdict), 2 when it could not run.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
A = {"preset_id": "p-expo", "strength": 130}
B = {"preset_id": "p-strong", "strength": 70}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Run:
    def __init__(self, repo, out, path):
        self.repo, self.out, self.path = os.path.abspath(repo), os.path.abspath(out), path
        self.base = os.path.join(self.out, "run")
        self.gate = os.path.join(self.base, "gate")
        self.presets = os.path.join(self.base, "lib", "xmp")
        self.data = os.path.join(self.base, "data")
        self.photo = os.path.join(self.base, "photos", "a.jpg")
        self.log = []
        self.t0 = time.monotonic()
        self.app = self.mcp = None
        self.mcp_lines = []
        self.mcp_id = 0

    def note(self, what, **kw):
        entry = {"t": round(time.monotonic() - self.t0, 3), "what": what, **kw}
        self.log.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    # ------------------------------------------------------------------ fixtures
    def fixtures(self):
        if os.path.exists(self.base):
            shutil.rmtree(self.base)
        for d in (self.gate, self.presets, os.path.dirname(self.photo)):
            os.makedirs(d)
        sys.path.insert(0, os.path.join(self.repo, "tests"))
        import _xmpgen
        _xmpgen.write(self.presets, "p-expo.xmp", _xmpgen.xmp_text({"Exposure2012": "+1.00"}, name="曝光一", group="測試"))
        _xmpgen.write(self.presets, "p-strong.xmp", _xmpgen.xmp_text({"Exposure2012": "+4.50"}, name="很亮", group="測試"))
        import numpy as np
        import cv2
        rgb = (np.random.default_rng(0).random((480, 640, 3)) * 255).astype("uint8")
        ok, enc = cv2.imencode(".jpg", rgb)
        assert ok
        with open(self.photo, "wb") as f:
            f.write(enc.tobytes())

    # ------------------------------------------------------------------ the App (HTTP)
    def start_app(self):
        self.port = free_port()
        cmd = [sys.executable, "-s", os.path.join(HERE, "gated_app.py"), "--repo", self.repo, "--gate-dir", self.gate,
               "--", "--port", str(self.port), "--preset-dir", self.presets, "--data-dir", self.data]
        self.note("start app", cmd=cmd)
        self.app_log = open(os.path.join(self.out, "app.log"), "wb")
        env = dict(os.environ, PYTHONUTF8="1")
        self.app = subprocess.Popen(cmd, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            line = self.app.stdout.readline()
            if not line:
                raise RuntimeError("app exited before it was ready")
            self.app_log.write(line)
            self.app_log.flush()
            if "darkroom 已啟動".encode("utf-8") in line:
                break
        else:
            raise RuntimeError("app not ready in 180 s")
        threading.Thread(target=self._pump_app, daemon=True).start()
        self.note("app ready", line=line.decode("utf-8", "replace").strip())

    def _pump_app(self):
        for line in iter(self.app.stdout.readline, b""):
            self.app_log.write(line)
            self.app_log.flush()

    def http(self, method, route, body=None, query=None):
        url = f"http://127.0.0.1:{self.port}{route}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"X-Darkroom": "1", "Content-Type": "application/json"})
        t = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = raw.decode("utf-8", "replace")
        self.note("http", method=method, route=route, query=query, body=body, status=status, response=payload,
                  ms=round((time.monotonic() - t) * 1000))
        return status, payload

    # ------------------------------------------------------------------ the AI agent (MCP stdio)
    def start_mcp(self):
        cmd = [sys.executable, "-s", os.path.join(HERE, "run_module.py"), "--repo", self.repo,
               "darkroom_app.mcp_server", "--preset-dir", self.presets, "--data-dir", self.data]
        self.note("start mcp", cmd=cmd)
        self.mcp_log = open(os.path.join(self.out, "mcp.log"), "wb")
        env = dict(os.environ, PYTHONUTF8="1")
        self.mcp = subprocess.Popen(cmd, cwd=self.repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=self.mcp_log, env=env)
        threading.Thread(target=self._pump_mcp, daemon=True).start()
        self.mcp_call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "prove-it", "version": "1"}}, wait=60)
        self.mcp_send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _pump_mcp(self):
        for line in iter(self.mcp.stdout.readline, b""):
            self.mcp_lines.append((time.monotonic(), json.loads(line.decode("utf-8"))))

    def mcp_send(self, msg):
        self.mcp.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        self.mcp.stdin.flush()

    def mcp_call(self, method, params, wait):
        """Send one request; return (answer or None if none within `wait` s, request id)."""
        self.mcp_id += 1
        rid = self.mcp_id
        self.mcp_send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        self.note("mcp send", id=rid, method=method, params=params)
        return self.mcp_wait(rid, wait), rid

    def mcp_wait(self, rid, wait):
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            for t, msg in self.mcp_lines:
                if msg.get("id") == rid:
                    self.note("mcp answer", id=rid, answer=msg)
                    return msg
            time.sleep(0.01)
        self.note("mcp no answer yet", id=rid, waited_s=wait)
        return None

    def tool(self, name, args, wait):
        return self.mcp_call("tools/call", {"name": name, "arguments": args}, wait)

    # ------------------------------------------------------------------ gate
    def arm(self, gate):
        open(os.path.join(self.gate, "arm-" + gate), "w").close()
        self.note("armed gate", gate=gate)

    def wait_paused(self, gate, wait=60):
        p = os.path.join(self.gate, "paused-" + gate)
        deadline = time.monotonic() + wait
        while not os.path.exists(p):
            if time.monotonic() > deadline:
                raise RuntimeError(f"gate {gate} never paused")
            time.sleep(0.01)
        with open(p, encoding="utf-8") as f:
            self.note("app paused at gate", gate=gate, at=f.read().strip())

    def release(self, gate):
        open(os.path.join(self.gate, "go-" + gate), "w").close()
        self.note("released gate", gate=gate)

    # ------------------------------------------------------------------ read back
    def read_back(self, tag):
        _, via_http = self.http("GET", "/api/edit", query={"path": self.photo})
        cmd = [sys.executable, "-s", os.path.join(HERE, "run_module.py"), "--repo", self.repo, "darkroom_app.cli",
               "--preset-dir", self.presets, "--data-dir", self.data, "edit", "get", self.photo, "--json"]
        p = subprocess.run(cmd, cwd=self.repo, capture_output=True, env=dict(os.environ, PYTHONUTF8="1"))
        via_cli = {"cmd": cmd, "exit": p.returncode, "stdout": p.stdout.decode("utf-8", "replace"),
                   "stderr": p.stderr.decode("utf-8", "replace")}
        with open(os.path.join(self.out, f"cli-{tag}.json"), "w", encoding="utf-8") as f:
            json.dump(via_cli, f, ensure_ascii=False, indent=2)
        self.note("cli edit get", exit=p.returncode, stdout=via_cli["stdout"].strip())
        files = {}
        root = os.path.join(self.data, "edits")
        for dp, _, names in os.walk(root):
            for n in sorted(names):
                full = os.path.join(dp, n)
                rel = os.path.relpath(full, self.data).replace(os.sep, "/")
                with open(full, "rb") as f:
                    raw = f.read()
                files[rel] = raw.decode("utf-8", "replace") if n.endswith(".json") else f"<{len(raw)} bytes>"
        with open(os.path.join(self.out, f"edits-files-{tag}.json"), "w", encoding="utf-8") as f:
            json.dump(files, f, ensure_ascii=False, indent=2)
        self.note("edit files", files=sorted(files))
        cli = json.loads(via_cli["stdout"])["result"] if p.returncode == 0 else None
        return via_http, cli, files

    @staticmethod
    def label(edit):
        return None if not edit else f"{edit['preset']['id'] if edit['preset'] else None}@{edit['strength']}"

    def prev_label(self, files):
        for rel, text in files.items():
            if rel.endswith(".prev.json"):
                e = json.loads(text)
                return self.label(e)
        return None

    # ------------------------------------------------------------------ the paths
    def p1(self):
        self.http("PUT", "/api/edit", {"path": self.photo, **A})                      # 1. edit A
        self.http("DELETE", "/api/edit", query={"path": self.photo})                  # 2. clear: A kept
        self.tool("darkroom_edit_get", {"path": self.photo}, wait=120)               # agent warmed up, reads only
        self.arm("P1")
        box = {}
        th = threading.Thread(target=lambda: box.update(r=self.http("POST", "/api/edit/restore", {"path": self.photo})))
        th.start()                                                                    # 3-4. restore reads
        self.wait_paused("P1")
        answer, rid = self.tool("darkroom_edit_set", {"path": self.photo, **B}, wait=1.5)   # 5. agent saves B
        answered_while_paused = answer is not None
        self.release("P1")                                                            # 6. restore goes on
        th.join(120)
        if answer is None:
            answer = self.mcp_wait(rid, 30)
        via_http, cli, files = self.read_back("after")
        agent_ok = bool(answer) and not answer.get("result", {}).get("isError")
        final = self.label(cli and cli["edit"])
        verdict = {
            "path": "P1", "rule": "R1",
            "restore_response": box.get("r"),
            "agent_answered_while_app_paused": answered_while_paused,
            "agent_saved_B": agent_ok,
            "final_edit_http": self.label(via_http.get("edit") if isinstance(via_http, dict) else None),
            "final_edit_cli": final, "previous_edit": self.prev_label(files),
            "edit_lost": agent_ok and final != self.label({"preset": {"id": B["preset_id"]}, "strength": B["strength"]}),
        }
        return verdict

    def p2(self):
        self.tool("darkroom_edit_get", {"path": self.photo}, wait=120)               # agent warmed up, reads only
        self.http("GET", "/api/edit", query={"path": self.photo})                     # 1. no edit
        self.arm("P2")
        box = {}
        th = threading.Thread(target=lambda: box.update(r=self.http("DELETE", "/api/edit", query={"path": self.photo})))
        th.start()                                                                    # 2. clear sees "no edit"
        self.wait_paused("P2")
        answer, rid = self.tool("darkroom_edit_set", {"path": self.photo, **A}, wait=1.5)   # 3. agent saves A
        answered_while_paused = answer is not None
        self.release("P2")                                                            # 4-6. clear goes on
        th.join(120)
        if answer is None:
            answer = self.mcp_wait(rid, 30)
        via_http, cli, files = self.read_back("after")
        agent_ok = bool(answer) and not answer.get("result", {}).get("isError")
        final = self.label(cli and cli["edit"])
        prev = self.prev_label(files)
        a = self.label({"preset": {"id": A["preset_id"]}, "strength": A["strength"]})
        return {
            "path": "P2", "rule": "R2",
            "clear_response": box.get("r"),
            "agent_answered_while_app_paused": answered_while_paused,
            "agent_saved_A": agent_ok,
            "final_edit_http": self.label(via_http.get("edit") if isinstance(via_http, dict) else None),
            "final_edit_cli": final, "previous_edit": prev,
            "edit_lost": agent_ok and final != a and prev != a,
        }

    # ------------------------------------------------------------------ cleanup
    def stop(self):
        if self.mcp is not None:
            try:
                self.mcp.stdin.close()
                self.mcp.wait(15)
            except Exception:                    # noqa: BLE001
                self.mcp.kill()
            self.note("mcp stopped", exit=self.mcp.returncode)
        if self.app is not None:
            self.app.terminate()
            try:
                self.app.wait(15)
            except subprocess.TimeoutExpired:
                self.app.kill()
            self.note("app stopped", exit=self.app.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--path", choices=("P1", "P2"), required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    run = Run(a.repo, a.out, a.path)
    head = subprocess.run(["git", "-C", run.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", run.repo, "status", "--porcelain", "--", "darkroom_app"],
                           capture_output=True, text=True).stdout.strip()
    run.note("version", repo=run.repo, head=head, darkroom_app_dirty=bool(dirty), python=sys.executable)
    verdict, code = None, 0
    try:
        run.fixtures()
        run.start_app()
        with open(os.path.join(run.gate, "app-module.txt"), encoding="utf-8") as f:
            module = f.read().strip()
        _, health = run.http("GET", "/api/health")
        run.note("doctor", health=health, app_module=module,
                 module_in_repo=os.path.normcase(module).startswith(os.path.normcase(run.repo)))
        run.start_mcp()
        verdict = run.p1() if a.path == "P1" else run.p2()
        run.note("verdict", **verdict)
    except Exception as e:                       # noqa: BLE001
        run.note("could not run", error=f"{type(e).__name__}: {e}")
        code = 2
    finally:
        run.stop()
        with open(os.path.join(a.out, "transcript.json"), "w", encoding="utf-8") as f:
            json.dump(run.log, f, ensure_ascii=False, indent=2)
        with open(os.path.join(a.out, "verdict.txt"), "w", encoding="utf-8") as f:
            f.write(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n")
        shutil.rmtree(run.base, ignore_errors=True)            # disposable fixtures; the evidence files stay
    return code


if __name__ == "__main__":
    sys.exit(main())
