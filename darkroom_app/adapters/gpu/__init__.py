"""GPU adapter: the torch / CUDA `Engine` (plan-v2 §1: adapters/gpu/engine.py).

Imported only when an operation first touches the GPU (`services.EngineRef.get()`), so listing presets, sliders,
settings and the edit commands never load torch or cv2 (L9).
"""
