"""CONTRACT-semantic-index SI1-SI12: the preset semantic index, with a fake Anthropic client, a fake key reader,
a fake renderer and a fake clock. No test talks to the API, starts `op`, or touches the GPU; the write guard is
armed throughout (every library lives in a fixture root)."""
import contextlib
import hashlib
import io
import json
import os
import random
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import cv2
import numpy as np

import _util
import _xmpgen
from darkroom_app import messages as M
from darkroom_app.errors import DarkroomError
from darkroom_app.services import semantic_index as S
from test_app_server import make_presets

SECRET = "sk-ant-TESTSECRET-do-not-leak-0123456789"
REF = "op://Personal/ClaudeAPIKey/credential"
NEED_PACKAGE = "需要 anthropic 套件：python -s -m pip install anthropic==1.13.0"                     # verbatim (SI2)
NEED_KEY = ("需要在 config.local.json 設定 anthropic_api_key_ref（1Password 參照，例如 op://<vault>/<item>/credential），"
            "或設定環境變數 DARKROOM_ANTHROPIC_API_KEY")                                              # verbatim (SI2)
NEED_SOURCES = "需要標準圖：{dir} 裡要有 real-portrait.jpg、real-landscape.jpg、real-night.jpg、real-fog.jpg"   # verbatim
OVER_BUDGET = "預估費用 {usd:.4f} 美元超過上限 {budget:.2f} 美元（設定鍵 semantic_index_budget_usd）"     # verbatim (SI8)
STATUS_KEYS = ["available", "reason", "model", "index_state", "indexed", "total", "pending", "in_flight",
               "budget_usd", "last_usage"]
BUILD_KEYS = ["state", "model", "planned", "estimated_usd", "budget_usd", "batch_ids", "collected", "failed",
              "errors", "indexed", "total", "pending", "usage"]
ENTRY = {"look_zh": "褪色的底片感，暖調低對比", "look_en": "faded film look, warm and low contrast",
         "tags_zh": ["底片", "暖調", "低對比", "褪色黑"], "tags_en": ["film", "warm", "faded", "matte"],
         "tone": "balanced", "contrast": "low", "saturation": "muted", "temperature": "warm",
         "good_for": ["人像", "日常"], "confidence": 0.8}


def make_sources(d, sizes=((40, 30), (50, 20), (24, 36), (30, 30))):
    """Four tiny JPEGs with the constant names (synthetic stand-ins for the public calibration photos)."""
    os.makedirs(d, exist_ok=True)
    for name, (w, h) in zip(S.SOURCE_NAMES, sizes):
        img = np.full((h, w, 3), 120, np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(buf.tobytes())
    return d


def sha_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def result_item(sha, entry=None, kind="succeeded", text=None, usage=(1000, 200)):
    if kind != "succeeded":
        return SimpleNamespace(custom_id=sha, result=SimpleNamespace(type=kind))
    body = json.dumps(entry, ensure_ascii=False) if text is None else text
    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=body)],
                          usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                                                cache_creation_input_tokens=0, cache_read_input_tokens=0))
    return SimpleNamespace(custom_id=sha, result=SimpleNamespace(type="succeeded", message=msg))


class FakeBatches:
    def __init__(self):
        self.created = []           # [(batch id, requests)]
        self.status = {}
        self.results_by_id = {}
        self.retrieved = []

    def create(self, requests):
        bid = f"msgbatch_{len(self.created) + 1:03d}"
        self.created.append((bid, list(requests)))
        self.status[bid] = "in_progress"
        return SimpleNamespace(id=bid, processing_status="in_progress")

    def retrieve(self, bid):
        self.retrieved.append(bid)
        return SimpleNamespace(id=bid, processing_status=self.status[bid])

    def results(self, bid):
        yield from self.results_by_id[bid]

    def finish(self, bid, items):
        self.status[bid] = "ended"
        self.results_by_id[bid] = items


class FakeClient:
    """Like the SDK client: the batches live server-side, so every client of one harness sees the same store."""

    def __init__(self, api_key, store=None):
        self.api_key = api_key
        self.messages = SimpleNamespace(batches=FakeBatches() if store is None else store)


class Harness:
    """A synthetic library in a fixture root, a facade whose semantic service has every outside contact faked."""

    def __init__(self, test, budget=5.0, key_ref=REF, env_key=None, have_anthropic=True, sources=True):
        from darkroom_app.composition import build_facade
        self.tmp = _util.tmpdir(test)
        self.pd = os.path.join(self.tmp, "xmp")
        os.makedirs(self.pd)
        make_presets(self.pd)
        self.src = make_sources(os.path.join(self.tmp, "sources")) if sources else os.path.join(self.tmp, "nope")
        self.clients, self.reads, self.rendered, self.sleeps = [], [], [], []
        self.now = [1000.0]
        self.store = FakeBatches()

        def factory(api_key):
            c = FakeClient(api_key, self.store)
            self.clients.append(c)
            return c

        def reader(ref):
            self.reads.append(ref)
            return SECRET

        def renderer(sources_dir, engine_ref, jobs):
            self.rendered.append((sources_dir, [sha for sha, _ in jobs]))
            return {sha: ["QUJD"] * 4 for sha, _ in jobs}

        def sleep(s):
            self.sleeps.append(s)
            self.now[0] += s
        self.f = build_facade(self.pd, semantic=dict(
            key_ref=key_ref, env_key=env_key, sources_dir=self.src, budget_usd=budget,
            have_anthropic=lambda: have_anthropic, client_factory=factory, key_reader=reader, renderer=renderer,
            sleep=sleep, monotonic=lambda: self.now[0], clock=lambda: 1700000000 + self.now[0]))
        self.lib = self.f._presets.library
        self.semantic_path = os.path.join(self.tmp, "semantic.json")

    @property
    def batches(self):
        return self.store

    def sha(self, pid):
        return sha_of(os.path.join(self.pd, pid + ".xmp"))

    def supported(self):
        return [e["id"] for e in self.lib.entries if e["id"] in self.lib.params]

    def index(self):
        with open(self.semantic_path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))


class TestCapability(unittest.TestCase):  # SI2
    def test_reasons_in_order(self):
        h = Harness(self, have_anthropic=False, key_ref=None, sources=False)
        st = h.f.semantic_status()
        self.assertEqual(list(st), STATUS_KEYS)
        self.assertEqual((st["available"], st["reason"]), (False, NEED_PACKAGE))
        h = Harness(self, key_ref=None, sources=False)
        self.assertEqual(h.f.semantic_status()["reason"], NEED_KEY)
        h = Harness(self, key_ref="  ", env_key="", sources=False)
        self.assertEqual(h.f.semantic_status()["reason"], NEED_KEY)
        h = Harness(self, sources=False)
        self.assertEqual(h.f.semantic_status()["reason"], NEED_SOURCES.format(dir=h.src))
        os.remove(os.path.join(Harness(self).src, "real-fog.jpg"))     # three of four is not enough
        h = Harness(self, env_key="sk-ant-env", key_ref=None)
        self.assertEqual((h.f.semantic_status()["available"], h.f.semantic_status()["reason"]), (True, None))
        self.assertEqual(h.f.semantic_status()["model"], "claude-haiku-5-5")
        self.assertEqual(h.f.semantic_status()["budget_usd"], 5.0)

    def test_build_refused_with_the_same_sentence(self):
        for kw, reason in ((dict(have_anthropic=False), NEED_PACKAGE), (dict(key_ref=None), NEED_KEY),
                           (dict(sources=False), None)):
            h = Harness(self, **kw)
            want = reason or NEED_SOURCES.format(dir=h.src)
            with self.assertRaises(DarkroomError) as cm:
                h.f.semantic_build()
            self.assertEqual((cm.exception.kind, cm.exception.message), ("unavailable", want))
            self.assertEqual((h.clients, h.reads, h.rendered), ([], [], []))
            self.assertFalse(os.path.exists(h.semantic_path))

    def test_status_reads_only(self):  # SI2: no key, no network, no GPU, no file
        h = Harness(self)
        before = sorted(os.listdir(h.tmp))
        h.f.semantic_status()
        self.assertEqual(sorted(os.listdir(h.tmp)), before)
        self.assertEqual((h.clients, h.reads, h.rendered), ([], [], []))
        self.assertIsNone(h.f._photos.engine_ref.peek())

    def test_config_defaults(self):
        from darkroom_app import config
        cfg = os.path.join(_util.tmpdir(self), "c.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"localllms_root": "E:/x", "semantic_index_budget_usd": -3, "anthropic_api_key_ref": " "}, fh)
        self.assertIsNone(config.anthropic_api_key_ref(cfg))
        self.assertEqual(config.semantic_index_budget_usd(cfg), 5.0)
        self.assertEqual(config.calibration_sources_dir(cfg, {}),
                         os.path.join("E:/x", "scratch", "lr-calibration", "sources"))
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"semantic_index_budget_usd": 2.5, "anthropic_api_key_ref": REF,
                       "calibration_sources_dir": "D:/cal"}, fh)
        self.assertEqual((config.anthropic_api_key_ref(cfg), config.semantic_index_budget_usd(cfg),
                          config.calibration_sources_dir(cfg, {})), (REF, 2.5, "D:/cal"))
        self.assertIsNone(config.calibration_sources_dir(os.path.join(cfg + ".none"), {}))


class TestEstimate(unittest.TestCase):  # SI8
    def test_estimate_formula(self):
        self.assertEqual(S.composite_size(8256, 5504), (1024, 341))
        self.assertEqual(S.composite_size(4340, 2893), (1024, 341))
        self.assertEqual(S.composite_size(300, 100), (600, 100))                  # never upscaled
        sizes = [(1024, 341), (1024, 262), (1024, 341), (1024, 341)]
        img = sum(-(-w * h // 750) for w, h in sizes)
        text = -(-len(S.SYSTEM_PROMPT + S.USER_TEXT) // 3)
        per = ((img + text) * 0.10 + 2048 * 0.50) / 1e6 * 0.5
        self.assertAlmostEqual(S.estimate_usd(sizes, 1466), per * 1466)
        self.assertLess(S.estimate_usd(sizes, 1466), 5.0)                         # the whole library fits the default
        self.assertEqual(S.estimate_usd(sizes, 0), 0.0)
        self.assertAlmostEqual(S.cost_usd(2000, 300), (2000 * 0.10 + 300 * 0.50) / 1e6 * 0.5)

    def test_request_params_shape(self):  # SI5
        p = S.request_params(["AAAA", "BBBB", "CCCC", "DDDD"])
        self.assertEqual(list(p), ["model", "max_tokens", "system", "output_config", "messages"])
        self.assertEqual((p["model"], p["max_tokens"], p["system"]), ("claude-haiku-5-5", 2048, S.SYSTEM_PROMPT))
        self.assertEqual(p["output_config"], {"effort": "low", "format": {"type": "json_schema", "schema": S.SCHEMA}})
        self.assertNotIn("thinking", p)
        self.assertEqual([m["role"] for m in p["messages"]], ["user"])          # no assistant prefill
        content = p["messages"][0]["content"]
        images = [c for c in content if c["type"] == "image"]
        self.assertEqual([c["source"]["data"] for c in images], ["AAAA", "BBBB", "CCCC", "DDDD"])
        self.assertTrue(all(c["source"] == {"type": "base64", "media_type": "image/jpeg", "data": c["source"]["data"]}
                            for c in images))
        self.assertEqual(S.SCHEMA["required"], ["look_zh", "look_en", "tags_zh", "tags_en", "tone", "contrast",
                                                "saturation", "temperature", "good_for", "confidence"])
        self.assertIs(S.SCHEMA["additionalProperties"], False)

    def test_over_budget_refused(self):
        h = Harness(self, budget=0.00001)
        with self.assertRaises(DarkroomError) as cm:
            h.f.semantic_build()
        est = S.estimate_usd([S.composite_size(w, h2) for w, h2 in S.source_sizes(h.src)], 5)
        self.assertEqual((cm.exception.kind, cm.exception.message),
                         ("invalid", OVER_BUDGET.format(usd=est, budget=0.00001)))
        self.assertEqual((h.clients, h.reads, h.rendered), ([], [], []))      # nothing sent, no key read
        self.assertFalse(os.path.exists(h.semantic_path))
        r = h.f.semantic_build(dry_run=True)                                    # dry run reports, never refuses
        self.assertEqual((r["state"], r["planned"], r["estimated_usd"], r["budget_usd"]), ("dry_run", 5, est, 0.00001))


class TestBuild(unittest.TestCase):  # SI3, SI6, SI7, SI9, SI10
    def test_dry_run_has_no_side_effects(self):
        h = Harness(self)
        before = sorted(os.listdir(h.tmp))
        r = h.f.semantic_build(dry_run=True)
        self.assertEqual(list(r), BUILD_KEYS)
        self.assertEqual((r["state"], r["planned"], r["indexed"], r["total"], r["pending"]), ("dry_run", 5, 0, 5, 5))
        self.assertEqual(r["estimated_usd"], S.estimate_usd([S.composite_size(w, hh) for w, hh in
                                                             S.source_sizes(h.src)], 5))
        self.assertEqual((h.clients, h.reads, h.rendered, h.sleeps), ([], [], [], []))
        self.assertEqual(sorted(os.listdir(h.tmp)), before)
        self.assertEqual(h.f.semantic_build(limit=2, dry_run=True)["planned"], 2)
        for bad in (0, -1, "x", True, 1.5):
            with self.assertRaises(DarkroomError) as cm:
                h.f.semantic_build(limit=bad, dry_run=True)
            self.assertEqual((cm.exception.kind, cm.exception.message), ("invalid", "limit 必須是 1 以上的整數"))
        for bad in (-1, "x", True):
            with self.assertRaises(DarkroomError) as cm:
                h.f.semantic_build(wait_seconds=bad, dry_run=True)
            self.assertEqual((cm.exception.kind, cm.exception.message), ("invalid", "wait_seconds 必須是 0 以上的數"))

    def test_submit_then_collect(self):
        h = Harness(self)
        r = h.f.semantic_build(limit=3, wait_seconds=0)
        self.assertEqual(r["state"], "submitted")
        self.assertEqual((r["planned"], r["collected"], r["failed"], r["pending"], r["indexed"]), (3, 0, 0, 2, 0))
        self.assertEqual(h.reads, [REF])
        self.assertEqual(h.clients[0].api_key, SECRET)                           # the key went to the SDK only
        self.assertEqual(h.rendered, [(h.src, [h.sha(p) for p in h.supported()[:3]])])
        (bid, requests), = h.batches.created
        self.assertEqual(r["batch_ids"], [bid])
        self.assertEqual([q["custom_id"] for q in requests], [h.sha(p) for p in h.supported()[:3]])
        self.assertEqual(requests[0]["params"], S.request_params(["QUJD"] * 4))
        idx = h.index()
        self.assertEqual(list(idx), ["schema", "model", "entries", "batches", "usage"])
        self.assertEqual((idx["schema"], idx["model"], idx["entries"], idx["usage"]),
                         ("darkroom-semantic-index/1", "claude-haiku-5-5", {}, []))
        self.assertEqual(idx["batches"][bid]["items"], {h.sha(p): p for p in h.supported()[:3]})
        st = h.f.semantic_status()
        self.assertEqual((st["indexed"], st["total"], st["pending"], st["in_flight"], st["index_state"]),
                         (0, 5, 2, [bid], "ok"))
        # a second build while the batch runs sends the two remaining, never the in-flight ones
        r2 = h.f.semantic_build(wait_seconds=0)
        self.assertEqual((r2["state"], r2["planned"], len(h.batches.created)), ("submitted", 2, 2))
        # the results come back in a random order with one malformed answer and one errored request
        shas = [h.sha(p) for p in h.supported()[:3]]
        items = [result_item(shas[0], ENTRY, usage=(1100, 210)),
                 result_item(shas[1], text='{"look_zh": "x"}', usage=(900, 50)),
                 result_item(shas[2], kind="errored")]
        random.Random(7).shuffle(items)
        h.batches.finish(bid, items)
        r3 = h.f.semantic_build(wait_seconds=0)
        self.assertEqual((r3["state"], r3["planned"], r3["collected"], r3["failed"]), ("done", 0, 1, 2))
        self.assertEqual(r3["usage"], {"input_tokens": 2000, "output_tokens": 260,
                                       "cost_usd": (2000 * 0.10 + 260 * 0.50) / 1e6 * 0.5})
        self.assertEqual(sorted(e["sha256"] for e in r3["errors"]), sorted(shas[1:]))
        by = {e["sha256"]: e for e in r3["errors"]}
        self.assertEqual(by[shas[1]]["error"], "回應不合格式：fields must be exactly " + ", ".join(S.SEMANTIC_FIELDS))
        self.assertEqual(by[shas[2]]["error"], "批次結果：errored")
        self.assertEqual(by[shas[2]]["preset_id"], h.supported()[2])
        idx = h.index()
        self.assertEqual(list(idx["entries"]), [shas[0]])
        self.assertEqual({k: v for k, v in idx["entries"][shas[0]].items() if k != "at"}, ENTRY)
        self.assertEqual(list(idx["batches"]), [h.batches.created[1][0]])
        self.assertEqual(idx["usage"][0]["batch"], bid)
        self.assertEqual((idx["usage"][0]["succeeded"], idx["usage"][0]["failed"]), (1, 2))
        st = h.f.semantic_status()
        self.assertEqual((st["indexed"], st["pending"], st["in_flight"], st["last_usage"]["cost_usd"]),
                         (1, 2, [h.batches.created[1][0]], r3["usage"]["cost_usd"]))
        self.assertEqual(sorted(os.listdir(h.tmp)), ["semantic.json", "semantic.json.lock", "sources", "xmp"])
        # search: the tagged preset is found by its Chinese and English tags and by the look sentence
        pid = h.supported()[0]
        for q in ("底片", "FILM", "褪色黑", "matte", "日常", "低對比"):
            self.assertEqual([x["id"] for x in h.f.list_presets(q)["items"]], [pid], q)
        self.assertEqual(h.f.list_presets("黑白")["total"], 0)
        row = next(x for x in h.f.list_presets()["items"] if x["id"] == pid)
        self.assertEqual(list(row), ["id", "group", "name", "supported", "skipped", "favorite", "tags"])
        self.assertEqual(row["tags"], ["底片", "暖調", "低對比", "褪色黑", "film", "warm", "faded", "matte"])
        self.assertTrue(all(x["tags"] == [] for x in h.f.list_presets()["items"] if x["id"] != pid))
        self.assertEqual(h.f.rename_preset(pid, "改名")["tags"], row["tags"])         # every row has 7 columns

    def test_wait_polls_until_ended(self):
        h = Harness(self)
        sha = h.sha(h.supported()[0])
        polls = []
        real = FakeBatches.retrieve

        def retrieve(self_, bid):
            polls.append(bid)
            if len(polls) == 3:
                self_.finish(bid, [result_item(sha, ENTRY)])
            return real(self_, bid)
        FakeBatches.retrieve = retrieve
        self.addCleanup(setattr, FakeBatches, "retrieve", real)
        r = h.f.semantic_build(limit=1, wait_seconds=600)
        self.assertEqual((r["state"], r["collected"], r["batch_ids"]), ("done", 1, ["msgbatch_001"]))
        self.assertEqual(h.sleeps, [15, 15])                                        # POLL_S between retrieves
        r = h.f.semantic_build(limit=1, wait_seconds=20)
        self.assertEqual((r["state"], r["planned"], h.sleeps), ("submitted", 1, [15, 15, 15, 5]))   # gave up at 20 s
        r = h.f.semantic_build(limit=1, wait_seconds=0)
        self.assertEqual((r["state"], r["planned"]), ("submitted", 1))
        self.assertEqual(len(h.batches.created), 3)
        h.batches.finish("msgbatch_002", [])
        h.batches.finish("msgbatch_003", [])
        r = h.f.semantic_build(wait_seconds=0)
        self.assertEqual((r["state"], r["planned"], r["collected"], r["failed"]), ("submitted", 2, 0, 0))

    def test_nothing_to_do(self):
        h = Harness(self)
        for pid in h.supported():
            pass
        h.f.semantic_build(wait_seconds=0)
        h.batches.finish("msgbatch_001", [result_item(h.sha(p), ENTRY) for p in h.supported()])
        self.assertEqual(h.f.semantic_build(wait_seconds=0)["state"], "done")
        r = h.f.semantic_build(wait_seconds=0)
        self.assertEqual((r["state"], r["planned"], r["indexed"], r["pending"]), ("nothing", 0, 5, 0))
        self.assertEqual(len(h.batches.created), 1)

    def test_index_key_is_content_hash(self):  # SI6
        h = Harness(self)
        h.f.semantic_build(wait_seconds=0)
        h.batches.finish("msgbatch_001", [result_item(h.sha(p), ENTRY) for p in h.supported()])
        self.assertEqual(h.f.semantic_build(wait_seconds=0)["indexed"], 5)
        os.rename(os.path.join(h.pd, "p-expo.xmp"), os.path.join(h.pd, "renamed.xmp"))   # a move keeps the entry
        h.f.rebuild_library()
        st = h.f.semantic_status()
        self.assertEqual((st["indexed"], st["pending"]), (5, 0))
        self.assertEqual(next(x for x in h.f.list_presets()["items"] if x["id"] == "renamed")["tags"][:2], ["底片", "暖調"])
        _xmpgen.write(h.pd, "renamed.xmp", _xmpgen.xmp_text({"Exposure2012": "+0.33"}, name="改了內容"))
        h.f.rebuild_library()
        st = h.f.semantic_status()
        self.assertEqual((st["indexed"], st["pending"]), (4, 1))                  # new content = new work
        self.assertEqual(h.f.semantic_build(dry_run=True)["planned"], 1)

    def test_bad_index_is_treated_as_empty(self):  # SI6
        h = Harness(self)
        with open(h.semantic_path, "wb") as fh:
            fh.write(b"{not json")
        st = h.f.semantic_status()
        self.assertEqual((st["index_state"], st["indexed"], st["pending"]), ("bad", 0, 5))
        with open(h.semantic_path, "wb") as fh:
            fh.write(json.dumps({"schema": "other/9", "model": "x", "entries": {}, "batches": {}, "usage": []}).encode())
        self.assertEqual(h.f.semantic_status()["index_state"], "bad")
        self.assertEqual(h.f.list_presets("底片")["total"], 0)
        h.f.semantic_build(wait_seconds=0)
        self.assertEqual(h.f.semantic_status()["index_state"], "ok")

    def test_key_never_leaks(self):  # SI3
        from darkroom_app import cli
        from darkroom_app.mcp_server import serve
        h = Harness(self)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["presets", "semantic", "build", "--wait-seconds", "0", "--json"], facade=h.f)
        self.assertEqual((rc, err.getvalue()), (0, ""))
        texts = [out.getvalue()]
        h.batches.finish("msgbatch_001", [result_item(h.sha(p), ENTRY) for p in h.supported()])
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "darkroom_semantic_build", "arguments": {}}}).encode() + b"\n"
        mcp_out = io.BytesIO()
        serve(io.BytesIO(line), mcp_out, facade=h.f)
        texts.append(mcp_out.getvalue().decode("utf-8"))
        with open(h.semantic_path, "rb") as fh:
            texts.append(fh.read().decode("utf-8"))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(["presets", "semantic", "status"], facade=h.f)
            cli.main(["presets", "list", "--query", "底片"], facade=h.f)
        texts += [out.getvalue(), err.getvalue()]
        # the service's own state never holds the key either
        texts.append(repr(vars(h.f._semantic)))
        for t in texts:
            self.assertNotIn(SECRET, t)
            self.assertNotIn(SECRET[7:20], t)
        self.assertEqual(h.reads, [REF, REF])                                       # once per build, never kept

    def test_key_failures_are_fixed_sentences(self):  # SI3
        h = Harness(self)
        for reason in ("找不到 op（1Password CLI）", "op read 結束碼 1", "op read 逾時", "op read 回傳空值"):
            def reader(ref, reason=reason):
                raise S._KeyUnavailable(reason)
            h.f._semantic.key_reader = reader
            with self.assertRaises(DarkroomError) as cm:
                h.f.semantic_build(wait_seconds=0)
            self.assertEqual((cm.exception.kind, cm.exception.message), ("unavailable", "無法取得 Anthropic 金鑰：" + reason))
        self.assertEqual(h.clients, [])
        self.assertFalse(os.path.exists(h.semantic_path))
        h.f._semantic.key_reader = lambda ref: SECRET
        h.f._semantic.key_ref = None
        h.f._semantic.env_key = "sk-ant-ENVSECRET"
        h.f.semantic_build(wait_seconds=0)
        self.assertEqual(h.clients[0].api_key, "sk-ant-ENVSECRET")                 # env var when there is no ref

    def test_op_read_shape_and_errors(self):  # SI3 / WG15: the subprocess call is exactly op read <ref>
        import subprocess
        from unittest import mock
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            return SimpleNamespace(returncode=0, stdout=b"  " + SECRET.encode() + b"\n", stderr=b"")
        with mock.patch.object(subprocess, "run", fake_run):
            self.assertEqual(S.op_read(REF), SECRET)
        self.assertEqual(calls, [(["op", "read", REF], {"capture_output": True, "timeout": 30})])
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(S._KeyUnavailable) as cm:
                S.op_read(REF)
            self.assertEqual(str(cm.exception), "找不到 op（1Password CLI）")
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("op", 30)):
            with self.assertRaises(S._KeyUnavailable) as cm:
                S.op_read(REF)
            self.assertEqual(str(cm.exception), "op read 逾時")
        with mock.patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=6, stdout=b"",
                                                                                stderr=b"[ERROR] secret-ish")):
            with self.assertRaises(S._KeyUnavailable) as cm:
                S.op_read(REF)
            self.assertEqual(str(cm.exception), "op read 結束碼 6")                # never op's stderr
        with mock.patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b" \n", stderr=b"")):
            with self.assertRaises(S._KeyUnavailable) as cm:
                S.op_read(REF)
            self.assertEqual(str(cm.exception), "op read 回傳空值")

    def test_api_errors_become_unavailable(self):  # SI9
        import anthropic
        import httpx2
        h = Harness(self)

        def boom(requests):
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/x"))
        h.f.semantic_build(dry_run=True)
        orig = FakeBatches.create
        FakeBatches.create = lambda self_, requests: boom(requests)
        self.addCleanup(setattr, FakeBatches, "create", orig)
        with self.assertRaises(DarkroomError) as cm:
            h.f.semantic_build(wait_seconds=0)
        self.assertEqual(cm.exception.kind, "unavailable")
        self.assertEqual(cm.exception.message, "Anthropic API 錯誤：Connection error.")
        self.assertNotIn(SECRET, cm.exception.message)
        self.assertFalse(os.path.exists(h.semantic_path))                          # nothing registered

    def test_index_atomic_and_safe_write(self):  # SI6
        from darkroom_app import safe_write
        h = Harness(self)
        h.f.semantic_build(wait_seconds=0)
        self.assertEqual([n for n in os.listdir(h.tmp) if ".tmp-" in n], [])
        # every write names the preset folder in use, so a library root inside it is refused (KP1 analogue)
        inside = os.path.join(h.pd, "sub")
        os.makedirs(inside)
        from darkroom_app.composition import build_facade
        g = build_facade(h.pd, library_dir=inside, semantic=dict(
            key_ref=REF, env_key=None, sources_dir=h.src, budget_usd=5.0, have_anthropic=lambda: True,
            client_factory=FakeClient, key_reader=lambda ref: SECRET,
            renderer=lambda s, e, jobs: {sha: ["QUJD"] * 4 for sha, _ in jobs}, sleep=lambda s: None))
        with self.assertRaises(safe_write.SafeWriteRefused):
            g.semantic_build(wait_seconds=0)
        self.assertEqual(os.listdir(inside), [])


class _FakeEngine:
    """Stands in for Engine.render_full: returns the input half as BGR bytes (no torch)."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="darkroom-gpu")
        self.calls = []

    def render_full(self, image, params, bits):
        self.calls.append((image.shape, bits, params.values.get("Exposure2012")))
        return np.ascontiguousarray((image[..., ::-1] * 255.0 + 0.5).astype(np.uint8))


class TestRenderer(unittest.TestCase):  # SI4: in-memory composites from the four constant sources only
    def test_only_calibration_sources_are_sent(self):
        from darkroom import load_preset
        tmp = _util.tmpdir(self)
        src = make_sources(os.path.join(tmp, "sources"), sizes=((40, 30), (600, 300), (24, 36), (30, 30)))
        with open(os.path.join(src, "real-portrait.jpg"), "rb") as fh:
            portrait = fh.read()
        with open(os.path.join(src, "secret-user-photo.jpg"), "wb") as fh:    # a stray file is never read
            fh.write(portrait)
        os.makedirs(os.path.join(tmp, "xmp"))
        pd = make_presets(os.path.join(tmp, "xmp"))
        eng = _FakeEngine()
        self.addCleanup(eng.executor.shutdown)
        ref = SimpleNamespace(get=lambda: eng)
        jobs = [("a" * 64, load_preset(os.path.join(pd, "p-expo.xmp"))), ("b" * 64, load_preset(os.path.join(pd, "p-strong.xmp")))]
        before = sorted(os.listdir(tmp)), sorted(os.listdir(src))
        out = S.render_composites(src, ref, jobs)
        self.assertEqual((sorted(os.listdir(tmp)), sorted(os.listdir(src))), before)     # nothing written
        self.assertEqual(sorted(out), ["a" * 64, "b" * 64])
        self.assertEqual([len(v) for v in out.values()], [4, 4])
        import base64
        sizes = []
        for data in out["a" * 64]:
            arr = cv2.imdecode(np.frombuffer(base64.b64decode(data), np.uint8), cv2.IMREAD_COLOR)
            sizes.append((arr.shape[1], arr.shape[0]))
        self.assertEqual(sizes, [(80, 30), (1024, 256), (48, 36), (60, 30)])    # 2 x half, long edge 512
        self.assertEqual([c[0] for c in eng.calls][:4], [(30, 40, 3), (256, 512, 3), (36, 24, 3), (30, 30, 3)])
        self.assertEqual(len(eng.calls), 8)
        self.assertEqual({c[1] for c in eng.calls}, {8})
        self.assertEqual([c[2] for c in eng.calls[:4]], [1.0] * 4)              # the preset at 100%
        self.assertEqual([c[2] for c in eng.calls[4:]], [4.5] * 4)
        self.assertEqual(S.source_sizes(src), [(40, 30), (600, 300), (24, 36), (30, 30)])


if __name__ == "__main__":
    unittest.main()
