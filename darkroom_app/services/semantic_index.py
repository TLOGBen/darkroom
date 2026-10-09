"""The preset semantic index: Claude looks at what a preset does and writes tags (CONTRACT-semantic-index).

For every supported preset not yet indexed, the four public calibration photos are rendered with the preset at
100% (in memory, long edge 512, "original | preset" side by side), sent to Claude Haiku 5.5 through the Message
Batches API with a JSON schema for the answer, and the answer is kept in `<library root>/semantic.json` under the
preset's content hash (renaming or moving a file never costs a second call). Searching never needs a key: that is
`services/presets.py` reading the index through `Library.semantic()`.

What stays out of this module's reach, by construction:
* the API key lives only in a local variable of `build` and in the SDK client (`api_key=`); it is never stored,
  logged, written or put in a sentence (SI3). It is read with `op read <op://...>` - the only subprocess this
  module may start (CONTRACT-write-guard WG15) - or from DARKROOM_ANTHROPIC_API_KEY;
* only the four constant source files are ever read as images; no user photo, thumbnail or preset file is sent
  (SI4); rendering writes nothing;
* nothing is sent before the estimated cost is under the configured budget (SI8), and every finished batch's
  real usage is written down;
* torch / cv2 / anthropic are imported inside the functions that need them (status and listing stay light);
* every write goes through `safe_write` (root = the library root, `preset_dir=` the preset folder in use).

Tests inject a fake client (`client_factory`), a fake key reader, a fake renderer and a fake sleep.
"""
import json
import math
import msvcrt
import os
import secrets
import subprocess
import threading
import time

from .. import config
from .. import messages as M
from .. import preview as semantics
from .. import safe_write
from ..errors import DarkroomError
from ..presets import SEMANTIC_FIELDS, SEMANTIC_MODEL, SEMANTIC_NAME, valid_entry
from . import on_gpu

MODEL = SEMANTIC_MODEL                              # verbatim (SI5): claude-haiku-5-5
PRICE_INPUT_USD_PER_M, PRICE_OUTPUT_USD_PER_M = 0.10, 0.50    # verbatim (S2, SI8): Haiku 5.5 list prices
BATCH_DISCOUNT = 0.5                                # verbatim (SI8)
MAX_TOKENS = 2048                                   # verbatim (SI5)
EFFORT = "low"                                      # verbatim (SI5)
BATCH_MAX = 500                                     # verbatim (SI9): requests per batch
POLL_S = 15                                         # verbatim (SI9)
WAIT_DEFAULT_S = 3600                               # verbatim (SI9): when wait_seconds is None (the CLI)
OP_TIMEOUT_S = 30                                   # verbatim (SI3)
LOCK_WAIT_S, LOCK_POLL_S = 5.0, 0.02                # as KP8
LONG_EDGE = 512                                     # verbatim (SI4)
JPEG_QUALITY = 85                                   # verbatim (SI4)
IMAGE_TOKEN_DIVISOR = 750                           # verbatim (SI8): ceil(w*h/750)
TEXT_CHARS_PER_TOKEN = 3                            # verbatim (SI8): ceil(len/3)
SOURCE_NAMES = ("real-portrait.jpg", "real-landscape.jpg", "real-night.jpg", "real-fog.jpg")   # verbatim (SI2/SI4)
SOURCE_LABELS = ("人像（portrait）", "風景（landscape）", "夜景（night）", "霧景（fog）")
SCHEMA = {  # verbatim (SI5)
    "type": "object",
    "properties": {
        "look_zh": {"type": "string"}, "look_en": {"type": "string"},
        "tags_zh": {"type": "array", "items": {"type": "string"}},
        "tags_en": {"type": "array", "items": {"type": "string"}},
        "tone": {"type": "string", "enum": ["dark", "balanced", "bright"]},
        "contrast": {"type": "string", "enum": ["low", "medium", "high"]},
        "saturation": {"type": "string", "enum": ["muted", "natural", "vivid", "monochrome"]},
        "temperature": {"type": "string", "enum": ["cool", "neutral", "warm"]},
        "good_for": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": list(SEMANTIC_FIELDS),
    "additionalProperties": False,
}
SYSTEM_PROMPT = (
    "你是資深調色師。使用者會給你 4 張並排比較圖：每張左半是原圖、右半是套用同一個 Lightroom preset（強度 100%）"
    "之後的結果。四張分別是人像、風景、夜景、霧景。只看右半相對左半的變化，描述這個 preset 的「風格」，"
    "不要描述照片內容。\n"
    "輸出 JSON：look_zh／look_en 各一句（20 字以內／15 words 以內）描述整體感覺；tags_zh／tags_en 各 3～8 個關鍵字，"
    "用攝影師搜尋時會打的詞，例如 底片、電影感、暖調、冷調、低對比、高對比、褪色黑、日系、韓系、黑白、復古、清透、"
    "濃郁、青橙、柔和、奶油、莫蘭迪、藍調、綠調、粉調、通透、灰調 / film, cinematic, warm, cool, faded, matte, "
    "moody, pastel, teal-orange, vintage, clean, muted, vivid, bw；tone＝整體明暗傾向（dark／balanced／bright）；"
    "contrast＝low／medium／high；saturation＝muted／natural／vivid／monochrome；temperature＝cool／neutral／warm；"
    "good_for＝最適合的題材（例如 人像、風景、夜景、街拍、旅行、日常、美食），1～4 個；confidence＝0～1，"
    "四張圖變化很小或互相矛盾時給低一點。繁體中文用台灣用語。"
)
USER_TEXT = "請依系統指示，根據這 4 張比較圖描述這個 preset 的風格，只回 JSON。"
_CONFIG = object()          # "resolve from the configuration when needed"


def composite_size(width, height):
    """(w, h) of one 'original | preset' composite: each half scaled so the long edge is 512 (never upscaled)."""
    s = min(1.0, LONG_EDGE / max(width, height))
    hw, hh = max(1, round(width * s)), max(1, round(height * s))
    return 2 * hw, hh


def image_tokens(width, height):
    return math.ceil(width * height / IMAGE_TOKEN_DIVISOR)


def text_tokens():
    return math.ceil(len(SYSTEM_PROMPT + USER_TEXT) / TEXT_CHARS_PER_TOKEN)


def estimate_usd(sizes, count):
    """SI8: count x ((image tokens + text tokens) x input price + MAX_TOKENS x output price) / 1e6 x discount."""
    tokens = sum(image_tokens(w, h) for w, h in sizes) + text_tokens()
    per = (tokens * PRICE_INPUT_USD_PER_M + MAX_TOKENS * PRICE_OUTPUT_USD_PER_M) / 1e6 * BATCH_DISCOUNT
    return per * count


def cost_usd(input_tokens, output_tokens):
    return (input_tokens * PRICE_INPUT_USD_PER_M + output_tokens * PRICE_OUTPUT_USD_PER_M) / 1e6 * BATCH_DISCOUNT


def request_params(jpegs):
    """The Messages params of one batch request (SI5): 4 labelled composites, the system prompt, JSON schema."""
    content = []
    for label, data in zip(SOURCE_LABELS, jpegs):
        content.append({"type": "text", "text": label + "：左原圖、右套 preset"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text": USER_TEXT})
    return {"model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT,
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": content}]}


def _one_line(e):
    return " ".join(str(e).split()) or type(e).__name__


class _KeyUnavailable(Exception):
    pass


def op_read(ref):
    """`op read <ref>` -> the secret (stripped). The only subprocess this module starts (WG15 shape)."""
    try:
        r = subprocess.run(["op", "read", ref], capture_output=True, timeout=OP_TIMEOUT_S)
    except FileNotFoundError:
        raise _KeyUnavailable(M.SEM_KEY_NO_OP) from None
    except subprocess.TimeoutExpired:
        raise _KeyUnavailable(M.SEM_KEY_OP_TIMEOUT) from None
    if r.returncode != 0:
        raise _KeyUnavailable(M.SEM_KEY_OP_EXIT.format(code=r.returncode))   # never op's stdout / stderr
    secret = r.stdout.decode("utf-8", "replace").strip()
    if not secret:
        raise _KeyUnavailable(M.SEM_KEY_OP_EMPTY)
    return secret


def _have_anthropic():
    import importlib.util
    return importlib.util.find_spec("anthropic") is not None


def _client(api_key):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _api_errors():
    try:
        import anthropic
    except ImportError:
        return ()
    return (anthropic.APIError,)


def source_sizes(sources_dir):
    """[(w, h)] of the 4 source JPEGs from their headers (no decode; the photo library's JPEG header reader)."""
    from .photo_library import _jpeg_size
    out = []
    for name in SOURCE_NAMES:
        with open(os.path.join(sources_dir, name), "rb") as fh:
            out.append(_jpeg_size(fh.read()))
    return out


def render_composites(sources_dir, engine_ref, jobs):
    """{sha: [4 JPEG bytes]} for jobs [(sha, Params)]: GPU rendering on the darkroom-gpu thread, nothing written."""
    import base64

    import cv2
    import numpy as np

    from darkroom import read_image
    eng = engine_ref.get()

    def work():
        halves = []
        for name in SOURCE_NAMES:
            full = read_image(os.path.join(sources_dir, name))
            h, w = full.shape[:2]
            cw, ch = composite_size(w, h)
            hw = cw // 2
            small = full if (hw, ch) == (w, h) else cv2.resize(full, (hw, ch), interpolation=cv2.INTER_AREA)
            del full
            orig_bgr = np.ascontiguousarray((small[..., ::-1] * 255.0 + 0.5).astype(np.uint8))
            halves.append((np.ascontiguousarray(small, dtype=np.float32), orig_bgr))
        out = {}
        for sha, params in jobs:
            final = semantics.effective_params(params, 1.0, {})
            jpegs = []
            for small, orig_bgr in halves:
                bgr = eng.render_full(small, final, 8)
                comp = np.concatenate([orig_bgr, bgr], axis=1)
                ok, buf = cv2.imencode(".jpg", comp, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                jpegs.append(base64.b64encode(buf.tobytes()).decode("ascii"))
            out[sha] = jpegs
        return out
    return on_gpu(eng, work)


class SemanticIndexService:
    def __init__(self, library, preset_dir, engine_ref, *, key_ref=_CONFIG, env_key=_CONFIG, sources_dir=_CONFIG,
                 budget_usd=_CONFIG, have_anthropic=_have_anthropic, client_factory=_client, key_reader=op_read,
                 renderer=render_composites, sleep=time.sleep, monotonic=time.monotonic, clock=time.time):
        self.library = library
        self.preset_dir = preset_dir
        self.engine_ref = engine_ref
        self.key_ref, self.env_key, self.sources_dir, self.budget_usd = key_ref, env_key, sources_dir, budget_usd
        self.have_anthropic, self.client_factory, self.key_reader = have_anthropic, client_factory, key_reader
        self.renderer, self.sleep, self.monotonic, self.clock = renderer, sleep, monotonic, clock
        self._tlock = threading.Lock()

    # ------------------------------------------------------------------ settings (resolved when needed)
    def _key_ref(self):
        ref = config.anthropic_api_key_ref() if self.key_ref is _CONFIG else self.key_ref
        return ref.strip() if isinstance(ref, str) and ref.strip() else None

    def _env_key(self):
        v = os.environ.get(config.ENV_API_KEY) if self.env_key is _CONFIG else self.env_key
        return v if isinstance(v, str) and v.strip() else None

    def _sources_dir(self):
        return config.calibration_sources_dir() if self.sources_dir is _CONFIG else self.sources_dir

    def _budget(self):
        return config.semantic_index_budget_usd() if self.budget_usd is _CONFIG else self.budget_usd

    def capability(self):
        """(available, reason): SI2 - package, then a key source, then the four source photos."""
        if not self.have_anthropic():
            return False, M.SEM_NEED_PACKAGE
        if not self._key_ref() and not self._env_key():
            return False, M.SEM_NEED_KEY
        d = self._sources_dir()
        if not d or not all(os.path.isfile(os.path.join(d, n)) for n in SOURCE_NAMES):
            return False, M.SEM_NEED_SOURCES.format(dir=d)
        return True, None

    # ------------------------------------------------------------------ the index on disk (safe_write only)
    @property
    def root(self):
        return self.library.root

    def _sw(self, fn, *args):
        return fn(*args, preset_dir=self.preset_dir)

    def _acquire(self):
        lock = os.path.join(self.root, SEMANTIC_NAME + ".lock")
        try:
            fd = self._sw(safe_write.open_lock, lock, self.root)
        except OSError as e:
            raise DarkroomError("unavailable", M.SEM_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise DarkroomError("conflict", M.LIB_BUSY) from None
                time.sleep(LOCK_POLL_S)

    @staticmethod
    def _release(fd):
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

    def _write(self, index):
        tmp = os.path.join(self.root, f"{SEMANTIC_NAME}.tmp-{os.getpid()}-{secrets.token_hex(6)}")
        data = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self._sw(safe_write.create_new, tmp, self.root, data)
        except OSError as e:
            raise DarkroomError("unavailable", M.SEM_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        try:
            for attempt in range(200):
                try:
                    self._sw(safe_write.replace_into, tmp, self.library.semantic_path, self.root)
                    return
                except PermissionError as e:          # a reader has the file open (KP21)
                    if attempt == 199:
                        raise DarkroomError("unavailable",
                                            M.SEM_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
                    time.sleep(0.01)
                except OSError as e:
                    raise DarkroomError("unavailable", M.SEM_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        finally:
            if os.path.exists(tmp):
                self._sw(safe_write.remove, tmp, self.root)

    def _mutate(self, change):
        """Lock -> the index on disk -> change(index) -> atomic write (only when change returns True)."""
        with self._tlock:
            fd = self._acquire()
            try:
                try:
                    index, _ = self.library.read_semantic()
                except PermissionError as e:
                    raise DarkroomError("unavailable", M.SEM_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
                if change(index):
                    self._write(index)
                return index
            finally:
                self._release(fd)

    # ------------------------------------------------------------------ counting
    def _supported(self):
        """[(pid, sha)] of the supported presets in the view's order (B3)."""
        files, params = self.library.files(), self.library.params
        return [(e["id"], files[e["id"]].sha256) for e in self.library.entries
                if e["id"] in params and e["id"] in files]

    @staticmethod
    def _in_flight(index):
        return {sha for b in index["batches"].values() for sha in b["items"]}

    def _counts(self, index):
        rows = self._supported()
        entries, flying = index["entries"], self._in_flight(index)
        indexed = sum(1 for _, sha in rows if sha in entries)
        pending = [(pid, sha) for pid, sha in rows if sha not in entries and sha not in flying]
        return len(rows), indexed, pending

    # ------------------------------------------------------------------ operations
    def semantic_status(self):
        available, reason = self.capability()
        index = self.library.semantic()
        total, indexed, pending = self._counts(index)
        return {"available": available, "reason": reason, "model": MODEL,
                "index_state": self.library.semantic_state(), "indexed": indexed, "total": total,
                "pending": len(pending), "in_flight": sorted(index["batches"]), "budget_usd": self._budget(),
                "last_usage": index["usage"][-1] if index["usage"] else None}

    def semantic_build(self, limit=None, dry_run=False, wait_seconds=None):
        available, reason = self.capability()
        if not available:
            raise DarkroomError("unavailable", reason)
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise DarkroomError("invalid", M.SEM_LIMIT_INVALID)
        if wait_seconds is not None and (isinstance(wait_seconds, bool) or not isinstance(wait_seconds, (int, float))
                                         or not wait_seconds >= 0):
            raise DarkroomError("invalid", M.SEM_WAIT_INVALID)
        wait = WAIT_DEFAULT_S if wait_seconds is None else float(wait_seconds)
        budget = self._budget()
        sources = self._sources_dir()
        index = self.library.semantic()
        total, indexed, pending = self._counts(index)
        planned = pending if limit is None else pending[:limit]
        sizes = [composite_size(w, h) for w, h in source_sizes(sources)]
        estimated = estimate_usd(sizes, len(planned))
        result = {"state": "dry_run", "model": MODEL, "planned": len(planned), "estimated_usd": estimated,
                  "budget_usd": budget, "batch_ids": [], "collected": 0, "failed": 0, "errors": [],
                  "indexed": indexed, "total": total, "pending": len(pending), "usage": None}
        if dry_run:
            return result
        if estimated > budget:
            raise DarkroomError("invalid", M.SEM_OVER_BUDGET.format(usd=estimated, budget=budget))
        client = self.client_factory(self._secret())        # the key goes to the SDK and nowhere else (SI3)
        errors = _api_errors()
        try:
            self._collect(client, result)                    # batches that ended since the last run
            if planned:
                self._submit(client, sources, planned, result)
                self._wait(client, wait, result)
        except errors as e:
            raise DarkroomError("unavailable", M.SEM_API_ERROR.format(detail=_one_line(e))) from None
        index = self.library.semantic()
        total, indexed, pending = self._counts(index)
        result.update(indexed=indexed, total=total, pending=len(pending))
        flying = self._in_flight(index)
        result["state"] = "nothing" if not planned and not result["collected"] and not result["failed"] else (
            "submitted" if any(sha in flying for _, sha in planned) else "done")
        return result

    def _secret(self):
        ref = self._key_ref()
        if ref:
            try:
                return self.key_reader(ref)
            except _KeyUnavailable as e:
                raise DarkroomError("unavailable", M.SEM_KEY_FAILED.format(reason=str(e))) from None
        return self._env_key()

    # ------------------------------------------------------------------ batches
    def _submit(self, client, sources, planned, result):
        params = self.library.params
        jobs = [(sha, params[pid]) for pid, sha in planned]
        jpegs = self.renderer(sources, self.engine_ref, jobs)
        for start in range(0, len(planned), BATCH_MAX):
            chunk = planned[start:start + BATCH_MAX]
            requests = [{"custom_id": sha, "params": request_params(jpegs[sha])} for _, sha in chunk]
            batch = client.messages.batches.create(requests=requests)
            created = {"created": int(self.clock()), "items": {sha: pid for pid, sha in chunk}}

            def change(index, bid=batch.id, created=created):
                index["batches"][bid] = created
                return True
            self._mutate(change)
            result["batch_ids"].append(batch.id)

    def _wait(self, client, wait, result):
        deadline = self.monotonic() + wait
        while self._collect(client, result):                  # ids still in flight after this pass
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return
            self.sleep(min(POLL_S, remaining))

    def _collect(self, client, result):
        """Fold every ended batch into the index; returns the ids still processing."""
        still = []
        for bid in list(self.library.semantic()["batches"]):
            batch = client.messages.batches.retrieve(bid)
            if batch.processing_status != "ended":
                still.append(bid)
                continue
            self._fold(client, bid, result)
        return still

    def _fold(self, client, bid, result):
        now = int(self.clock())
        got, errors, usage = {}, [], {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
                                      "cache_read_input_tokens": 0}
        for item in client.messages.batches.results(bid):
            sha, r = item.custom_id, item.result
            if r.type != "succeeded":
                errors.append((sha, M.SEM_BATCH_RESULT.format(result_type=r.type)))
                continue
            msg = r.message
            for k in usage:
                usage[k] += int(getattr(msg.usage, k, 0) or 0)
            try:
                text = next(b.text for b in msg.content if b.type == "text")
                entry = json.loads(text)
            except (StopIteration, ValueError, AttributeError) as e:
                errors.append((sha, M.SEM_BAD_RESPONSE.format(reason=_one_line(e))))
                continue
            bad = valid_entry(entry)
            if bad is not None:
                errors.append((sha, M.SEM_BAD_RESPONSE.format(reason=bad)))
                continue
            got[sha] = {**{k: entry[k] for k in SEMANTIC_FIELDS}, "at": now}
        record = {"batch": bid, "at": now, **usage, "cost_usd": cost_usd(usage["input_tokens"], usage["output_tokens"]),
                  "succeeded": len(got), "failed": len(errors)}

        def change(index):
            items = index["batches"].pop(bid, {}).get("items", {})
            for sha, e in got.items():
                index["entries"][sha] = e
            index["usage"].append(record)
            result["errors"] += [{"sha256": sha, "preset_id": items.get(sha), "error": err} for sha, err in errors]
            return True
        self._mutate(change)
        result["collected"] += len(got)
        result["failed"] += len(errors)
        u = result["usage"] or {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        result["usage"] = {"input_tokens": u["input_tokens"] + usage["input_tokens"],
                           "output_tokens": u["output_tokens"] + usage["output_tokens"],
                           "cost_usd": u["cost_usd"] + record["cost_usd"]}
