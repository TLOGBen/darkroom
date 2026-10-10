"""Versions of what is running, for GET /api/version, `cli version` and MCP darkroom_version (plan-v2 §3).

Layer: utils. Standard library only. torch is never imported here (importing it takes seconds and loads CUDA): its
version comes from the installed package's metadata, and the CUDA version from torch itself only when something else
already imported it, else from the wheel's local version label (`2.14.0+cu130` -> "13.0"). A machine without torch
answers null for both.
"""
import importlib.metadata
import platform as _platform
import re
import sys

_CU = re.compile(r"\+cu(\d+)(\d)$")       # +cu130 -> ("13", "0"); +cu128 -> ("12", "8")


def torch_versions():
    """(torch version or None, CUDA version or None) without importing torch."""
    mod = sys.modules.get("torch")
    if mod is not None:
        cuda = getattr(getattr(mod, "version", None), "cuda", None)
        return getattr(mod, "__version__", None), cuda
    try:
        v = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        return None, None
    m = _CU.search(v)
    return v, (f"{m.group(1)}.{m.group(2)}" if m else None)


def version_info(app_version):
    """{version, python, torch, cuda, platform}: the app's version (darkroom_app.__version__, the one source) and
    what it runs on."""
    torch_v, cuda = torch_versions()
    return {"version": app_version, "python": _platform.python_version(), "torch": torch_v, "cuda": cuda,
            "platform": f"{_platform.system()}-{_platform.release()}-{_platform.machine()}"}
