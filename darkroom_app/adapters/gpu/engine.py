"""GPU side of the preview (layer: adapters/gpu; the core `darkroom` library + torch / cv2): open photos into preview-sized GPU tensors and render JPEG previews.

All GPU work runs on one worker thread (EXECUTOR) and on a dedicated high-priority CUDA stream (STREAM); only
that stream is synchronized (never the whole device), so other programs' kernels do not hold up a preview.
The rendered image stays on the GPU until the 8-bit result is copied once for JPEG encoding with cv2 on the
CPU (GPU JPEG encoding returned corrupt files while the GPU was busy).

Layer: adapters/gpu. Depends on the core library's public names (read_image, render, Params, Geometry), torch, cv2,
numpy, domain.formats and utils.imaging; never on services, the facade, composition or config. Services reach it
only through `services.EngineRef` and always call it on its executor (`services.on_gpu`).

Data flow: open() decodes a photo once (read-only), keeps a preview-sized float32 copy on the GPU (<= 1.5 MP) and,
for big photos, a larger 16-bit host copy used when the user zooms into a crop; preview() renders that resident
tensor with final Params and returns JPEG bytes; render_full() uploads a full-resolution image for an export and
returns the quantised host array. At most MAX_OPEN_IMAGES photos stay resident (least recently used evicted), which
bounds GPU memory while the user flips through a folder.

Contract codes: L5 = preview size rules; L6 = one GPU thread; B4 = the 1.5 MP preview limit; C17 / C19 / D6 = the
geometry in previews and exports, and the "detail base" for sharp crops; X3 / X11 / XP7 = export rendering, memory,
releasing the cache after a batch; H7 / KP11 = the photo extension table.
"""
import contextlib
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import torch

from darkroom import Geometry, Params, read_image, render

from ...domain.formats import PHOTO_EXT  # noqa: F401  the one extension table (CONTRACT-heic H7), torch-free (KP11)
from ...utils.imaging import PREVIEW_MAX_PIXELS, preview_size  # noqa: F401  B4, re-exported (engine.preview_size)

DETAIL_MAX_PIXELS = 4 * PREVIEW_MAX_PIXELS   # verbatim (CONTRACT-s3-crop D6(B)): the detail base, never above the photo
JPEG_QUALITY = 85
MAX_OPEN_IMAGES = 8


class Engine:
    """The GPU state of the process: open photos, the single GPU executor and the CUDA stream."""

    def __init__(self, device=None):
        """device: "cuda" / "cpu" / a torch device, default CUDA when available (CPU works, slowly).

        The stream gets the highest priority CUDA offers so interactive previews are scheduled ahead of other
        programs' background kernels on the same GPU."""
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="darkroom-gpu")
        self.stream = None
        if self.device.type == "cuda":
            lo, hi = torch.cuda.Stream.priority_range()  # (lowest, greatest); greatest is the most negative
            self.stream = torch.cuda.Stream(device=self.device, priority=hi)
        self.images = OrderedDict()   # image_id -> {"path", "width", "height", "tensor", "detail"}
        self._lock = threading.Lock()
        self._detail = None           # (image_id, device tensor): the detail base of the photo cropped last (S3 D6)

    # ------------------------------------------------------------------ helpers
    def _on_stream(self):
        """Context manager: run the enclosed torch work on this Engine's stream (no-op on CPU)."""
        return torch.cuda.stream(self.stream) if self.stream is not None else contextlib.nullcontext()

    def _sync(self):
        """Wait for this Engine's stream only (never a device-wide sync, which would wait for other programs)."""
        if self.stream is not None:
            self.stream.synchronize()

    def shutdown(self):
        """Stop the GPU thread (pending work cancelled) and drop every open photo; used when the server stops."""
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.images.clear()

    # ------------------------------------------------------------------ work (call on the executor)
    def open(self, path):
        """Read a photo (read-only), keep a preview-sized copy on the device, return its description.

        Returns {image_id, width, height, preview_width, preview_height}. Raises ValueError for an unsupported
        extension or an undecodable file, OSError when it cannot be read. Must run on the executor."""
        ext = os.path.splitext(path)[1].lower()
        if ext not in PHOTO_EXT:
            raise ValueError(f"unsupported photo format {ext or '(none)'} (JPEG/PNG/TIFF/HEIC)")
        full = read_image(path)
        h, w = full.shape[:2]
        pw, ph = preview_size(w, h)
        small = full if (pw, ph) == (w, h) else cv2.resize(full, (pw, ph), interpolation=cv2.INTER_AREA)
        detail = None                 # S3 D6(B): a bigger host copy (16-bit) for crops, when the photo is bigger
        if (pw, ph) != (w, h):
            dw, dh = preview_size(w, h, DETAIL_MAX_PIXELS)
            d = full if (dw, dh) == (w, h) else cv2.resize(full, (dw, dh), interpolation=cv2.INTER_AREA)
            detail = (np.clip(d, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
            del d
        del full
        host = torch.from_numpy(np.ascontiguousarray(small, dtype=np.float32)).permute(2, 0, 1)[None]
        with self._on_stream():
            t = host.to(self.device, non_blocking=False).contiguous()
        self._sync()
        image_id = uuid.uuid4().hex
        with self._lock:
            self.images[image_id] = {"path": os.path.abspath(path), "width": w, "height": h, "tensor": t,
                                     "detail": detail}
            while len(self.images) > MAX_OPEN_IMAGES:
                self.images.popitem(last=False)
        return {"image_id": image_id, "width": w, "height": h, "preview_width": pw, "preview_height": ph}

    def get(self, image_id):
        """The record of an open photo (path, size, GPU tensor, detail copy), marked most recently used; KeyError
        when it is not open (never opened, or evicted)."""
        with self._lock:
            info = self.images[image_id]
            self.images.move_to_end(image_id)
            return info

    def preview_target(self, image_id, geometry=None, frame=False, max_pixels=None):
        """(width, height) of the preview of `geometry` (CONTRACT-s3-crop C17): preview_size(output size, max_pixels
        or 1500000); frame=True: of the whole straightened frame W' x H'. No geometry: as before (L5)."""
        info = self.get(image_id)
        t = info["tensor"]
        if geometry is None or geometry.identity:
            w, h = int(t.shape[-1]), int(t.shape[-2])
            return (w, h) if max_pixels is None else preview_size(w, h, max_pixels)
        W, H = info["width"], info["height"]
        tw, th = geometry.frame_size(W, H) if frame else geometry.output_size(W, H)
        return preview_size(tw, th, PREVIEW_MAX_PIXELS if max_pixels is None else max_pixels)

    def _base(self, image_id, info, geometry, frame, pw, ph):
        """The image the preview samples from (D6(B)): the preview base, or the detail base when the cropped area
        of the preview base has fewer pixels than the preview needs."""
        t = info["tensor"]
        if frame or info.get("detail") is None:
            return t
        r = geometry.resolve(info["width"], info["height"])
        s = t.shape[-1] / info["width"]
        if r["width"] * s >= pw * 0.999 and r["height"] * s >= ph * 0.999:
            return t
        if self._detail is None or self._detail[0] != image_id:
            self._detail = None
            host = torch.from_numpy(info["detail"].astype(np.float32) * np.float32(1 / 65535)).permute(2, 0, 1)[None]
            self._detail = (image_id, host.to(self.device, non_blocking=False).contiguous())
        return self._detail[1]

    def preview(self, image_id, params, max_pixels=None, geometry=None, frame=False):
        """Render `params` (already at their final values: strength 1) -> (JPEG bytes, milliseconds).

        max_pixels (optional): shrink the rendered preview on the device to preview_size(w, h, max_pixels).
        geometry (a darkroom.Geometry, optional; CONTRACT-s3-crop C17): the picture is cropped / turned first, at
        preview_target's size; frame=True shows the whole straightened frame (the crop mode).
        """
        if not isinstance(params, Params):
            raise TypeError("params must be a darkroom.Params")
        info = self.get(image_id)
        t = info["tensor"]
        t0 = time.perf_counter()
        if geometry is not None and not geometry.identity:
            pw, ph = self.preview_target(image_id, geometry, frame, max_pixels)
            with self._on_stream():
                base = self._base(image_id, info, geometry, frame, pw, ph)
                out = render(base, params, strength=1.0,
                             geometry=geometry.bound(info["width"], info["height"], pw, ph, frame))
                u8 = (out[0].clamp(0, 1) * 255.0 + 0.5).to(torch.uint8)
                host = u8.flip(0).permute(1, 2, 0).contiguous().cpu()
            self._sync()
            ok, buf = cv2.imencode(".jpg", host.numpy(), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                raise RuntimeError("JPEG encoding failed")
            return buf.tobytes(), (time.perf_counter() - t0) * 1000.0
        with self._on_stream():
            out = render(t, params, strength=1.0)                       # stays on the device
            if max_pixels is not None:
                h, w = out.shape[-2:]
                pw, ph = preview_size(w, h, max_pixels)
                if (pw, ph) != (w, h):
                    out = torch.nn.functional.interpolate(out, size=(ph, pw), mode="area")
            u8 = (out[0].clamp(0, 1) * 255.0 + 0.5).to(torch.uint8)    # 3xHxW RGB
            bgr = u8.flip(0).permute(1, 2, 0).contiguous()
            host = bgr.cpu()                                            # the one copy, for the JPEG encoder
        self._sync()
        ok, buf = cv2.imencode(".jpg", host.numpy(), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return buf.tobytes(), (time.perf_counter() - t0) * 1000.0

    def render_full(self, image, params, bits, geometry=None):
        """Export render (CONTRACT-export X3, X11): a full-resolution HxWx3 float32 host image at `params` (final
        values, strength 1) -> host array: bits 8 -> HxWx3 uint8 in BGR order (for cv2.imencode), bits 16 ->
        HxWx3 uint16 RGB. Same stream as the preview; only that stream is synchronized. geometry (CONTRACT-s3-crop
        C19): the output picture is cropped / turned first (its size is the output size)."""
        if not isinstance(params, Params):
            raise TypeError("params must be a darkroom.Params")
        host = torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32)).permute(2, 0, 1)[None]
        with self._on_stream():
            t = host.to(self.device, non_blocking=False)
            out = render(t, params, strength=1.0, geometry=geometry)    # stays on the device
            del t
            x = out[0].clamp(0, 1)
            del out
            if bits == 8:
                q = (x * 255.0 + 0.5).to(torch.uint8).flip(0).permute(1, 2, 0).contiguous()
            else:
                q = (x * 65535.0 + 0.5).to(torch.int32).permute(1, 2, 0).contiguous()
            del x
            res = q.cpu()
            del q
        self._sync()
        arr = res.numpy()
        return arr if bits == 8 else arr.astype(np.uint16)

    def release_cached_memory(self):
        """After an export batch (XP7): hand the cached full-resolution blocks back (no device synchronize)."""
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def warm_up(self):
        """Run the heavy pipeline once at preview size so the first real preview is fast.

        The first CUDA kernels of each kind are compiled / loaded lazily, which would otherwise make the user's
        first slider drag stutter. Random pixels and a preset touching the expensive stages; nothing is kept."""
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
