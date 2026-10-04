"""GPU side of the preview: open photos into preview-sized GPU tensors and render JPEG previews.

All GPU work runs on one worker thread (EXECUTOR) and on a dedicated high-priority CUDA stream (STREAM); only
that stream is synchronized (never the whole device), so other programs' kernels do not hold up a preview.
The rendered image stays on the GPU until the 8-bit result is copied once for JPEG encoding with cv2 on the
CPU (GPU JPEG encoding returned corrupt files while the GPU was busy).
"""
import contextlib
import math
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import torch

from darkroom import Params, read_image, render

PREVIEW_MAX_PIXELS = 1500000  # verbatim constant (B4)
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif")   # CONTRACT-heic H7
JPEG_QUALITY = 85
MAX_OPEN_IMAGES = 8


def preview_size(width, height, limit=PREVIEW_MAX_PIXELS):
    """Largest size with the photo's aspect ratio and width * height <= limit (never upscaled)."""
    if width * height <= limit:
        return width, height
    s = math.sqrt(limit / (width * height))
    pw = max(1, int(width * s))
    ph = max(1, round(pw * height / width))
    while pw * ph > limit:
        pw -= 1
        ph = max(1, round(pw * height / width))
    return pw, ph


class Engine:
    def __init__(self, device=None):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="darkroom-gpu")
        self.stream = None
        if self.device.type == "cuda":
            lo, hi = torch.cuda.Stream.priority_range()  # (lowest, greatest); greatest is the most negative
            self.stream = torch.cuda.Stream(device=self.device, priority=hi)
        self.images = OrderedDict()   # image_id -> {"path", "width", "height", "tensor"}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _on_stream(self):
        return torch.cuda.stream(self.stream) if self.stream is not None else contextlib.nullcontext()

    def _sync(self):
        if self.stream is not None:
            self.stream.synchronize()

    def shutdown(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.images.clear()

    # ------------------------------------------------------------------ work (call on the executor)
    def open(self, path):
        """Read a photo (read-only), keep a preview-sized copy on the device, return its description."""
        ext = os.path.splitext(path)[1].lower()
        if ext not in PHOTO_EXT:
            raise ValueError(f"unsupported photo format {ext or '(none)'} (JPEG/PNG/TIFF/HEIC)")
        full = read_image(path)
        h, w = full.shape[:2]
        pw, ph = preview_size(w, h)
        small = full if (pw, ph) == (w, h) else cv2.resize(full, (pw, ph), interpolation=cv2.INTER_AREA)
        del full
        host = torch.from_numpy(np.ascontiguousarray(small, dtype=np.float32)).permute(2, 0, 1)[None]
        with self._on_stream():
            t = host.to(self.device, non_blocking=False).contiguous()
        self._sync()
        image_id = uuid.uuid4().hex
        with self._lock:
            self.images[image_id] = {"path": os.path.abspath(path), "width": w, "height": h, "tensor": t}
            while len(self.images) > MAX_OPEN_IMAGES:
                self.images.popitem(last=False)
        return {"image_id": image_id, "width": w, "height": h, "preview_width": pw, "preview_height": ph}

    def get(self, image_id):
        with self._lock:
            info = self.images[image_id]
            self.images.move_to_end(image_id)
            return info

    def preview(self, image_id, params):
        """Render `params` (already at their final values: strength 1) -> (JPEG bytes, milliseconds)."""
        if not isinstance(params, Params):
            raise TypeError("params must be a darkroom.Params")
        t = self.get(image_id)["tensor"]
        t0 = time.perf_counter()
        with self._on_stream():
            out = render(t, params, strength=1.0)                       # stays on the device
            u8 = (out[0].clamp(0, 1) * 255.0 + 0.5).to(torch.uint8)    # 3xHxW RGB
            bgr = u8.flip(0).permute(1, 2, 0).contiguous()
            host = bgr.cpu()                                            # the one copy, for the JPEG encoder
        self._sync()
        ok, buf = cv2.imencode(".jpg", host.numpy(), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return buf.tobytes(), (time.perf_counter() - t0) * 1000.0

    def warm_up(self):
        """Run the heavy pipeline once at preview size so the first real preview is fast."""
        if self.device.type != "cuda":
            return
        img = np.random.default_rng(0).random((1000, 1500, 3), dtype=np.float32)
        with self._on_stream():
            t = torch.from_numpy(img).permute(2, 0, 1)[None].to(self.device)
            p = Params(values={"Exposure2012": 0.3, "Clarity2012": 20.0, "Texture": 10.0, "Highlights2012": -20.0,
                               "Shadows2012": 20.0, "Dehaze": 10.0, "SaturationAdjustmentRed": 10.0,
                               "Sharpness": 30.0, "GrainAmount": 5.0, "PostCropVignetteAmount": -10.0})
            render(t, p)
        self._sync()
