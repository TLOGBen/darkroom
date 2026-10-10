"""CONTRACT-layering L10: the MCP stdio server (framing, both protocol eras, tools, errors, clean stdout)."""
import base64
import io
import json
import os
import subprocess
import sys
import time
import unittest

import cv2
import numpy as np

import _util
from test_app_server import make_presets, write_photo

SERVER_INFO = {"name": "darkroom", "version": "0.1.0"}                      # verbatim
TOOLS = ["darkroom_presets_list", "darkroom_preset_show", "darkroom_preset_flags", "darkroom_sliders",
         "darkroom_open_photo", "darkroom_photo_folder", "darkroom_preview",
         "darkroom_export",    # verbatim, in order (CONTRACT-export XP4; K16: the library tools after it)
         "darkroom_preset_groups", "darkroom_preset_rename", "darkroom_preset_move", "darkroom_preset_favorite",
         "darkroom_group_create", "darkroom_group_rename", "darkroom_presets_import", "darkroom_preset_save",
         "darkroom_presets_rebuild",
         "darkroom_edit_get", "darkroom_edit_set", "darkroom_edit_clear", "darkroom_edit_paste",
         "darkroom_folder_thumbnails", "darkroom_thumbnail", "darkroom_edit_save_preset",   # PL6 / PLP6: 18..24
         "darkroom_edit_restore",                                                           # S4: 25
         "darkroom_semantic_build", "darkroom_semantic_status",   # CONTRACT-semantic-index SI1 / SI11: 26, 27 (merge patch)
         "darkroom_export_presets_list", "darkroom_export_preset_save", "darkroom_export_preset_delete",
         "darkroom_preset_files", "darkroom_presets_export", "darkroom_capabilities",   # S2 E25: 28..33
         "darkroom_settings_get", "darkroom_settings_set", "darkroom_settings_export", "darkroom_settings_import",
         "darkroom_version"]                                                            # plan-v2 §3: 34..38
SEMANTIC_BUILD_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                              "openWorldHint": True}   # verbatim (SI11)
S2_ANNOTATIONS = {   # verbatim (CONTRACT-s2-export-detect 操作表)
    "darkroom_export_presets_list": {"readOnlyHint": True, "openWorldHint": False},
    "darkroom_export_preset_save": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                                    "openWorldHint": False},
    "darkroom_export_preset_delete": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                                      "openWorldHint": False},
    "darkroom_preset_files": {"readOnlyHint": True, "openWorldHint": False},
    "darkroom_presets_export": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                                "openWorldHint": False},
    "darkroom_capabilities": {"readOnlyHint": True, "openWorldHint": False}}
LIBRARY_IDEMPOTENT = {"darkroom_preset_rename": True, "darkroom_preset_move": True, "darkroom_preset_favorite": True,
                      "darkroom_presets_rebuild": True, "darkroom_group_create": False, "darkroom_group_rename": False,
                      "darkroom_presets_import": False, "darkroom_preset_save": False,
                      "darkroom_edit_save_preset": False}   # K16, PLP6
EDIT_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                    "openWorldHint": False}   # verbatim (CONTRACT-photo-library PL6)
EDIT_TOOLS = ("darkroom_edit_set", "darkroom_edit_clear", "darkroom_edit_paste", "darkroom_edit_restore")
EXPORT_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                      "openWorldHint": False}   # verbatim (CONTRACT-export XP4)
MODERN = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


def req(id_, method, params=None, meta=None):
    m = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None or meta is not None:
        m["params"] = dict(params or {})
        if meta is not None:
            m["params"]["_meta"] = meta
    return m


def lines(*msgs):
    out = b""
    for m in msgs:
        out += (m if isinstance(m, bytes) else json.dumps(m, ensure_ascii=False).encode("utf-8")) + b"\n"
    return out


class McpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = _util.tmpdir(self)
        d = os.path.join(self.tmp, "presets")
        os.makedirs(d)
        self.presets = make_presets(d)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.photo = write_photo(os.path.join(self.photos, "a.png"), 1600, 1000)

    def exchange(self, *msgs, facade=None):
        from darkroom_app.mcp_server import serve
        out = io.BytesIO()
        rc = serve(io.BytesIO(lines(*msgs)), out, facade=facade, preset_dir=self.presets)
        self.assertEqual(rc, 0)
        raw = out.getvalue()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw == b"" or raw.endswith(b"\n"))
        return [json.loads(x) for x in raw.decode("utf-8").split("\n") if x]


class TestMcpProtocol(McpCase):
    def test_mcp_legacy_flow(self):
        res = self.exchange(
            req(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            req(2, "tools/list"),
            req(3, "tools/call", {"name": "darkroom_presets_list", "arguments": {"limit": 2}}),
            req(4, "ping"))
        self.assertEqual([r["id"] for r in res], [1, 2, 3, 4])       # the notification got no answer
        self.assertEqual(res[0]["result"], {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                            "serverInfo": SERVER_INFO})
        tools = res[1]["result"]["tools"]
        self.assertNotIn("nextCursor", res[1]["result"])
        self.assertEqual([t["name"] for t in tools], TOOLS)
        for t in tools:
            if t["name"] in LIBRARY_IDEMPOTENT:
                want = dict(EXPORT_ANNOTATIONS, idempotentHint=LIBRARY_IDEMPOTENT[t["name"]])
            elif t["name"] in EDIT_TOOLS:
                want = EDIT_ANNOTATIONS
            elif t["name"] == "darkroom_semantic_build":
                want = SEMANTIC_BUILD_ANNOTATIONS
            elif t["name"] in S2_ANNOTATIONS:                    # CONTRACT-s2-export-detect E27 constants
                want = S2_ANNOTATIONS[t["name"]]
            elif t["name"] in ("darkroom_settings_set", "darkroom_settings_import"):   # plan-v2 §3: replace settings
                want = EDIT_ANNOTATIONS
            elif t["name"] == "darkroom_settings_export":                              # writes a new file with dest
                want = EXPORT_ANNOTATIONS
            else:
                want = EXPORT_ANNOTATIONS if t["name"] == "darkroom_export" else {"readOnlyHint": True,
                                                                                  "openWorldHint": False}
            self.assertEqual(t["annotations"], want)
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIs(t["inputSchema"]["additionalProperties"], False)
        call = res[2]["result"]
        self.assertNotIn("isError", call)
        self.assertEqual(call["structuredContent"]["total"], 6)
        self.assertEqual(len(call["structuredContent"]["items"]), 2)
        self.assertEqual(call["structuredContent"]["next_offset"], 2)
        self.assertEqual(call["content"], [{"type": "text", "text": json.dumps(call["structuredContent"],
                                                                               ensure_ascii=False)}])
        self.assertEqual(res[3]["result"], {})
        for r in res:
            self.assertNotIn("resultType", r["result"])
            self.assertNotIn("ttlMs", r["result"])

    def test_mcp_discover_flow(self):
        res = self.exchange(
            req(1, "server/discover", meta=MODERN),
            req(2, "tools/list", meta=MODERN),
            req(3, "tools/call", {"name": "darkroom_preset_show", "arguments": {"preset_id": "nope"}}, meta=MODERN),
            req(4, "tools/list", meta={"io.modelcontextprotocol/protocolVersion": "2099-01-01"}),
            req(5, "ping", meta=MODERN),
            req(6, "server/discover"))
        self.assertEqual(res[0]["result"], {"resultType": "complete", "supportedVersions": ["2026-07-28"],
                                            "capabilities": {"tools": {}},
                                            "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO},
                                            "ttlMs": 3600000, "cacheScope": "public"})
        self.assertEqual(res[1]["result"]["resultType"], "complete")
        self.assertEqual((res[1]["result"]["ttlMs"], res[1]["result"]["cacheScope"]), (3600000, "public"))
        self.assertEqual([t["name"] for t in res[1]["result"]["tools"]], TOOLS)
        self.assertEqual(res[2]["result"], {"content": [{"type": "text", "text": "unknown preset nope"}],
                                            "structuredContent": {"kind": "not_found",
                                                                  "message": "unknown preset nope"},
                                            "isError": True, "resultType": "complete"})
        self.assertEqual(res[3]["error"], {"code": -32022, "message": "Unsupported protocol version",
                                           "data": {"supported": ["2026-07-28", "2025-11-25"],
                                                    "requested": "2099-01-01"}})
        self.assertEqual(res[4]["result"], {"resultType": "complete"})
        self.assertEqual(res[5]["result"]["supportedVersions"], ["2026-07-28"])

    def test_mcp_protocol_errors(self):
        res = self.exchange(
            b"{not json",
            b"[1, 2]",
            b'"x"',
            {"jsonrpc": "2.0", "id": 1},
            {"jsonrpc": "1.0", "id": 2, "method": "ping"},
            req(3, "nope/method"),
            req(4, "tools/call", {"name": "darkroom_bogus", "arguments": {}}),
            req(5, "tools/call", {"name": "darkroom_sliders", "arguments": [1]}),
            req(6, "tools/call", {"name": "darkroom_sliders", "arguments": "x"}),
            {"jsonrpc": "2.0", "method": "nope/notification"},
            {"jsonrpc": "2.0", "id": 99, "result": {}},
            b"",
            req(7, "tools/call", {"name": "darkroom_sliders"}))
        codes = [(r.get("id"), r["error"]["code"]) if "error" in r else (r["id"], "ok") for r in res]
        self.assertEqual(codes, [(None, -32700), (None, -32600), (None, -32600), (1, -32600), (2, -32600),
                                 (3, -32601), (4, -32602), (5, -32602), (6, -32602), (7, "ok")])
        self.assertEqual(res[6]["error"]["message"], "Unknown tool: darkroom_bogus")
        self.assertEqual(res[7]["error"]["message"], "arguments must be an object")     # verbatim (seal patch S3)
        self.assertEqual(res[8]["error"]["message"], "arguments must be an object")
        self.assertIn("sliders", res[9]["result"]["structuredContent"])

    def test_mcp_unexpected_error_is_32603(self):
        from darkroom_app.composition import build_facade
        from unittest import mock
        f = build_facade(self.presets)
        with mock.patch.object(f, "preset_flags", side_effect=RuntimeError("boom")):
            res = self.exchange(req(1, "tools/call", {"name": "darkroom_preset_flags", "arguments": {}}),
                                req(2, "ping"), facade=f)
        self.assertEqual(res[0]["error"]["code"], -32603)
        self.assertEqual(res[1]["result"], {})

    def test_mcp_missing_preset_folder_is_32603(self):  # seal patch S5
        from darkroom_app.mcp_server import serve
        missing = os.path.join(self.tmp, "no-such-presets")
        out = io.BytesIO()
        serve(io.BytesIO(lines(req(1, "tools/call", {"name": "darkroom_sliders", "arguments": {}}), req(2, "ping"))),
              out, preset_dir=missing)
        res = [json.loads(x) for x in out.getvalue().decode("utf-8").splitlines()]
        self.assertEqual(res[0]["error"], {"code": -32603, "message": f"Internal error: FileNotFoundError: "
                                                                      f"preset folder not found: {missing}"})
        self.assertEqual(res[1]["result"], {})

    def test_mcp_preview_image_and_defaults(self):
        from darkroom_app.composition import build_facade
        f = build_facade(self.presets)
        info = f.open_photo(self.photo)
        res = self.exchange(
            req(1, "tools/call", {"name": "darkroom_preview", "arguments": {"image_id": info["image_id"],
                                                                            "preset_id": "p-expo"}}),
            req(2, "tools/call", {"name": "darkroom_preview", "arguments": {"image_id": info["image_id"],
                                                                            "max_pixels": 1500000}}),
            req(3, "tools/call", {"name": "darkroom_preview", "arguments": {"image_id": info["image_id"],
                                                                            "strength": 250}}),
            req(4, "tools/call", {"name": "darkroom_photo_folder", "arguments": {"image_id": "nope"}}),
            req(5, "tools/call", {"name": "darkroom_open_photo", "arguments": {"path": self.photo}}),
            facade=f)
        r = res[0]["result"]
        self.assertEqual(list(r), ["content", "structuredContent"])
        self.assertEqual(r["content"][0]["type"], "image")
        self.assertEqual(r["content"][0]["mimeType"], "image/jpeg")
        img = cv2.imdecode(np.frombuffer(base64.b64decode(r["content"][0]["data"]), np.uint8), cv2.IMREAD_COLOR)
        sc = r["structuredContent"]
        self.assertEqual(list(sc), ["render_ms", "width", "height"])
        self.assertEqual(img.shape[:2], (sc["height"], sc["width"]))
        self.assertLessEqual(sc["width"] * sc["height"], 786432)          # MCP default max_pixels
        self.assertGreater(sc["width"] * sc["height"], 786432 * 0.99)
        self.assertEqual((res[1]["result"]["structuredContent"]["width"],
                          res[1]["result"]["structuredContent"]["height"]), (info["preview_width"], info["preview_height"]))
        self.assertTrue(res[2]["result"]["isError"])
        self.assertEqual(res[2]["result"]["structuredContent"],
                         {"kind": "invalid", "message": "strength must be within 0..200, got 250"})
        self.assertEqual(res[3]["result"]["content"][0]["text"], "unknown image_id")
        self.assertEqual(list(res[4]["result"]["structuredContent"]),
                         ["image_id", "width", "height", "preview_width", "preview_height"])

    def test_open_error_detail(self):
        bad = os.path.join(self.photos, "broken.jpg")
        with open(bad, "wb") as fh:
            fh.write(b"not an image")
        res = self.exchange(req(1, "tools/call", {"name": "darkroom_open_photo", "arguments": {"path": bad}}))
        sc = res[0]["result"]["structuredContent"]
        self.assertEqual(sc, {"kind": "invalid", "message": f"照片讀取失敗：broken.jpg：cannot decode image {bad}",
                              "reason": f"cannot decode image {bad}", "file_name": "broken.jpg", "path": bad})


class TestMcpSubprocess(McpCase):
    def test_mcp_stdout_clean_subprocess(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        p = subprocess.Popen([*_util.guarded_python(), "-m", "darkroom_app.mcp_server", "--preset-dir", self.presets],
                             cwd=_util.REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env)
        try:
            def send(m):
                p.stdin.write(lines(m))
                p.stdin.flush()

            def recv():
                line = p.stdout.readline()
                self.assertTrue(line.endswith(b"\n"), line)
                self.assertNotIn(b"\r", line)
                return json.loads(line)
            send(req(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                       "clientInfo": {"name": "t", "version": "1"}}))
            self.assertEqual(recv()["result"]["protocolVersion"], "2025-11-25")
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send(req(2, "tools/call", {"name": "darkroom_open_photo", "arguments": {"path": self.photo}}))
            iid = recv()["result"]["structuredContent"]["image_id"]
            send(req(3, "tools/call", {"name": "darkroom_preview", "arguments": {"image_id": iid,
                                                                                 "preset_id": "p-expo"}}))
            r = recv()
            self.assertEqual(r["id"], 3)
            self.assertEqual(r["result"]["content"][0]["type"], "image")
            send(req(4, "server/discover", meta=MODERN))
            self.assertEqual(recv()["result"]["resultType"], "complete")
            send(req(5, "tools/call", {"name": "darkroom_presets_list", "arguments": {"query": "測試"}}, meta=MODERN))
            r = recv()
            self.assertEqual(r["result"]["structuredContent"]["total"], 3)
            p.stdin.close()
            t0 = time.perf_counter()
            rc = p.wait(timeout=10)
            took = time.perf_counter() - t0
            rest = p.stdout.read()
            self.assertEqual(rest, b"")                  # nothing but the five answers on stdout
            self.assertEqual(rc, 0)
            self.assertLess(took, 2.0)
            self.assertIn(b"[darkroom-mcp]", p.stderr.read())
        finally:
            if p.poll() is None:
                p.kill()
            for s in (p.stdout, p.stderr):
                s.close()


if __name__ == "__main__":
    unittest.main()
