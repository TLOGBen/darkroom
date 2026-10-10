"""sRGB <-> linear-light transfer functions (IEC 61966-2-1), float32 torch.

Layer: core library (`darkroom/`), used only by `_render`. Depends on torch alone.

Why it exists: Lightroom does its exposure / white balance style math on linear light (photon counts), while
most of its "look" controls (curves, HSL, split toning) act on a gamma-encoded, perceptual signal. The renderer
therefore hops between the two encodings; these helpers are the exact piecewise sRGB curve (a short linear toe
near black plus a 2.4 power segment), not the 2.2 gamma approximation, so a round trip is lossless within float32.
All inputs are clamped to 0..1 first because the curve is only defined there.
"""
import torch


def srgb_to_linear(x):
    """sRGB-encoded tensor in 0..1 -> linear light in 0..1 (same shape, same device)."""
    x = x.clamp(0.0, 1.0)
    return torch.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    """Linear light in 0..1 -> sRGB-encoded in 0..1 (same shape, same device).

    The inner clamp(min=0.0031308) keeps the power branch away from 0 so its gradient / value never becomes NaN
    for the elements that torch.where ends up discarding anyway.
    """
    x = x.clamp(0.0, 1.0)
    return torch.where(x <= 0.0031308, x * 12.92, 1.055 * x.clamp(min=0.0031308) ** (1 / 2.4) - 0.055)


def luma(x):
    """Rec.709 luma of a 1x3xHxW tensor (encoded or linear, depending on the input).

    Returns a 1x1xHxW tensor. The weights (0.2126 / 0.7152 / 0.0722) are the sRGB / Rec.709 primaries' share of
    luminance; applied to linear input this is true relative luminance, applied to encoded input it is the
    "luma" that tone controls use to decide shadows / midtones / highlights.
    """
    return 0.2126 * x[:, 0:1] + 0.7152 * x[:, 1:2] + 0.0722 * x[:, 2:3]
