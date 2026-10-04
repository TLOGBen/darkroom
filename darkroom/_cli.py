"""Command line: `python -m darkroom apply ...` and `python -m darkroom scan <preset_dir>`."""
import argparse
import os
import sys

from ._errors import UnsupportedPresetError

MSG_OK = "已套用：{preset_name}（強度 {strength}%）→ {output_path}"
MSG_SKIP = "略過：{items}"
MSG_SCAN = "已解析 {ok}／{total}，不支援 {unsupported}，失敗 {failed}"
MSG_PV = "不支援的 preset 版本：ProcessVersion {pv}（{file_name}）"
MSG_EXISTS = "輸出檔已存在或與輸入相同：{output_path}（要覆寫請加 --overwrite）"
USAGE_APPLY = "python -m darkroom apply --preset <xmp> [--strength 0..200] [--overwrite] <input> <output>"
USAGE_SCAN = "python -m darkroom scan <preset_dir>"


def _err(msg):
    print(msg, file=sys.stderr)


def _same_file(a, b):
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.abspath(p)))
    return norm(a) == norm(b)


def _fmt_strength(v):
    return f"{v:g}"


def cmd_apply(a):
    from . import _io, _xmp
    if not (0.0 <= a.strength <= 200.0):
        _err(f"強度要在 0～200 之間：{_fmt_strength(a.strength)}")
        return 2
    if _same_file(a.input, a.output) or (os.path.exists(a.output) and not a.overwrite):
        _err(MSG_EXISTS.format(output_path=a.output))
        return 2
    try:
        params, name = _xmp.read_preset(a.preset)
    except UnsupportedPresetError as e:
        _err(MSG_PV.format(pv=e.process_version, file_name=os.path.basename(a.preset)))
        return 2
    except (OSError, ValueError) as e:
        _err(f"preset 讀取失敗：{os.path.basename(a.preset)}：{e}")
        return 2
    try:
        img = _io.read_image(a.input)
    except (OSError, ValueError) as e:
        _err(f"照片讀取失敗：{a.input}：{e}")
        return 2
    ext = os.path.splitext(a.output)[1].lower()
    if ext not in _io.WRITE_EXT:
        _err(f"不支援的輸出格式：{ext or a.output}（可用 .png、.tif、.tiff 16-bit 或 .jpg 8-bit）")
        return 2
    from ._render import render
    out = render(img, params, strength=a.strength / 100.0)
    _io.write_image(a.output, out)
    print(MSG_OK.format(preset_name=name, strength=_fmt_strength(a.strength), output_path=a.output))
    if params.skipped:
        print(MSG_SKIP.format(items="、".join(params.skipped)))
    return 0


def cmd_scan(a):
    from ._xmp import read_preset
    if not os.path.isdir(a.preset_dir):
        _err(f"找不到資料夾：{a.preset_dir}")
        return 2
    files = []
    for root, _, names in os.walk(a.preset_dir):
        files += [os.path.join(root, n) for n in names if n.lower().endswith(".xmp")]
    ok = unsupported = failed = 0
    for path in sorted(files):
        try:
            read_preset(path)
            ok += 1
        except UnsupportedPresetError:
            unsupported += 1
        except (OSError, ValueError) as e:
            failed += 1
            _err(f"解析失敗：{os.path.basename(path)}：{e}")
    print(MSG_SCAN.format(ok=ok, total=len(files), unsupported=unsupported, failed=failed))
    return 0 if failed == 0 else 1


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m darkroom", description="Apply Lightroom xmp presets locally.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply", usage=USAGE_APPLY, help="apply a preset to a JPEG/PNG/TIFF")
    p.add_argument("--preset", required=True)
    p.add_argument("--strength", type=float, default=100.0)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("input")
    p.add_argument("output")
    s = sub.add_parser("scan", usage=USAGE_SCAN, help="parse every .xmp in a folder and report")
    s.add_argument("preset_dir")
    a = ap.parse_args(argv)
    return cmd_apply(a) if a.cmd == "apply" else cmd_scan(a)
