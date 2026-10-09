"""`python -s -m darkroom_app.cli`: the agent's command line over the facade (CONTRACT-layering L9).

    presets list [--query Q] [--offset N] [--limit N]
    presets show <preset_id>
    presets flags
    sliders
    open <photo>
    folder <photo>                      (open, then list the folder, in this one process)
    preview <photo> [--preset ID] [--strength S] [--override KEY=VALUE]... [--max-pixels N]
    export <photo>... [--preset ID] [--strength S] [--override KEY=VALUE]... [--format jpeg|tiff] [--quality N]
                      [--dest-dir D]
    presets list ... [--favorites] | groups | rename <id> <name> | move <id> <group> | favorite <id> on|off
    presets import <path>... [--group G] | save --name N [--group G] [--preset ID] [--strength S] [--override K=V]...
    presets rebuild
    groups create <group> | rename <group> <new>          (CONTRACT-preset-library K16)

Every subcommand takes --json: stdout is then exactly one line {"ok":true,"result":...} or
{"ok":false,"error":{"kind":...,"message":...}} and stderr stays empty. Without --json a failure is one line
on stderr. Exit codes: 0 ok, 1 unexpected, 2 invalid / usage, 3 not_found, 4 conflict, 5 unavailable, 6 export or
presets import with at least one failed item (stdout still holds every result; CONTRACT-export XP11, preset library
KP5). What writes files goes through the facade: `export` (new files) and the preset library commands (the library
index, import/ and user/); `preview` without --json writes the JPEG bytes to stdout.
"""
import argparse
import base64
import json
import re
import sys

from . import config
from .errors import DarkroomError

EXIT = {"invalid": 2, "not_found": 3, "conflict": 4, "unavailable": 5}
EXIT_PARTIAL = 6                        # export: some photos failed (CONTRACT-export XP11)
EXPORTED = "已匯出：{output_path}"        # verbatim (XP3)
IMPORTED = "已匯入：{id}"                 # verbatim (KP5)
FAVORITE_WORDS = {"on": True, "off": False}   # presets favorite <id> on|off; anything else goes to the service (KP9)
UNEXPECTED = "未預期錯誤：{type_name}：{detail}"
TTY_REFUSAL = "預覽是 JPEG 位元組，請導向檔案（> out.jpg）或加 --json"
CONFIG_ERROR = "darkroom：{e}"


def _override(text):
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    try:
        return key, float(value)
    except ValueError:
        return key, value          # the service reports it ("override for KEY must be a finite number")


class _OneLineParser(argparse.ArgumentParser):
    """Usage errors are exactly one stderr line, exit 2 (L9): no usage block before the error."""

    def error(self, message):
        self.exit(2, f"{self.prog}: error: {' '.join(str(message).split())}\n")


def _lenient_int(text):
    try:
        return int(text)
    except ValueError:
        return text                # the service reports it (JPEG quality)


def _parser():
    ap = _OneLineParser(prog="python -m darkroom_app.cli",
                                 description="darkroom for agents: presets, sliders, open and preview photos "
                                             "(read-only), export photos as new files")
    ap.add_argument("--preset-dir", default=None, help="default: from LOCALLLMS_ROOT or config.local.json")
    sub = ap.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def leaf(parent, name, help_text):
        p = parent.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--json", action="store_true", help="one-line JSON envelope on stdout")
        return p

    presets = sub.add_parser("presets", help="the preset library")
    psub = presets.add_subparsers(dest="presets_command", required=True, metavar="SUBCOMMAND")
    p = leaf(psub, "list", "list presets (sorted by group and name)")
    p.add_argument("--query", default=None, help="substring of the name or group (case-insensitive)")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--favorites", action="store_true", help="only the favorite presets")
    p = leaf(psub, "show", "one preset in detail")
    p.add_argument("preset_id")
    leaf(psub, "flags", "presets with skipped settings")
    leaf(psub, "groups", "the preset group tree")
    p = leaf(psub, "rename", "change a preset's display name (the file is never changed)")
    p.add_argument("preset_id")
    p.add_argument("name")
    p = leaf(psub, "move", "move a preset to a group ('A - B' for a sub-group)")
    p.add_argument("preset_id")
    p.add_argument("group")
    p = leaf(psub, "favorite", "mark (on) or unmark (off) a favorite")
    p.add_argument("preset_id")
    p.add_argument("state", metavar="on|off")
    p = leaf(psub, "import", "copy .xmp presets (files or folders) into the library; the sources are never changed")
    p.add_argument("path", nargs="*")
    p.add_argument("--group", default=None, help="group for every imported preset")
    p = leaf(psub, "save", "save a preset x strength + overrides as a new user preset (never overwrites)")
    p.add_argument("--name", default=None)
    p.add_argument("--group", default=None, help="default: 自存 preset")
    p.add_argument("--preset", default=None, help="preset id")
    p.add_argument("--strength", type=float, default=100, help="percent, 0..200 (default 100)")
    p.add_argument("--override", type=_override, action="append", default=None, metavar="KEY=VALUE",
                   help="slider difference added after strength (repeatable)")
    leaf(psub, "rebuild", "rebuild the library index from the preset folders")
    groups = sub.add_parser("groups", help="preset groups")
    gsub = groups.add_subparsers(dest="groups_command", required=True, metavar="SUBCOMMAND")
    p = leaf(gsub, "create", "create an empty group")
    p.add_argument("group")
    p = leaf(gsub, "rename", "rename a group and its sub-groups (new is the full new path)")
    p.add_argument("group")
    p.add_argument("new")
    leaf(sub, "sliders", "the editor's sliders")
    p = leaf(sub, "open", "open a photo and describe it")
    p.add_argument("photo")
    p = leaf(sub, "folder", "the photos in a photo's folder")
    p.add_argument("photo")
    p = leaf(sub, "preview", "render a JPEG preview of a photo")
    p.add_argument("photo")
    p.add_argument("--preset", default=None, help="preset id")
    p.add_argument("--strength", type=float, default=100, help="percent, 0..200 (default 100)")
    p.add_argument("--override", type=_override, action="append", default=None, metavar="KEY=VALUE",
                   help="slider difference added after strength (repeatable)")
    p.add_argument("--max-pixels", type=int, default=None, help="limit the preview to N pixels")
    p = leaf(sub, "export", "export photos at full resolution as new files (never overwrites)")
    p.add_argument("photo", nargs="*")
    p.add_argument("--preset", default=None, help="preset id")
    p.add_argument("--strength", type=float, default=100, help="percent, 0..200 (default 100)")
    p.add_argument("--override", type=_override, action="append", default=None, metavar="KEY=VALUE",
                   help="slider difference added after strength (repeatable)")
    p.add_argument("--format", default="jpeg", help="jpeg (default) or tiff")
    p.add_argument("--quality", type=_lenient_int, default=None, help="JPEG quality 1..100 (default 92)")
    p.add_argument("--dest-dir", default=None, help="existing absolute folder (default: <photo folder>/darkroom 匯出)")
    return ap


def _run(a, facade):
    cmd = a.command
    if cmd == "presets":
        sc = a.presets_command
        if sc == "list":
            return facade.list_presets(a.query, a.offset, a.limit, a.favorites)
        if sc == "show":
            return facade.preset_detail(a.preset_id)
        if sc == "groups":
            return facade.preset_groups()
        if sc == "rename":
            return facade.rename_preset(a.preset_id, a.name)
        if sc == "move":
            return facade.move_preset(a.preset_id, a.group)
        if sc == "favorite":
            return facade.set_favorite(a.preset_id, FAVORITE_WORDS.get(a.state, a.state))
        if sc == "import":
            return facade.import_presets(a.path, a.group, None)
        if sc == "save":
            overrides = dict(a.override) if a.override else None
            return facade.save_user_preset(a.name, a.group, a.preset, a.strength, overrides)
        if sc == "rebuild":
            return facade.rebuild_library()
        return facade.preset_flags()
    if cmd == "groups":
        if a.groups_command == "create":
            return facade.create_group(a.group)
        return facade.rename_group(a.group, a.new)
    if cmd == "sliders":
        return facade.slider_table()
    if cmd == "export":           # every photo is a path item with the same parameters; nothing is opened first
        overrides = dict(a.override) if a.override else None
        items = [{"path": p, "preset_id": a.preset, "strength": a.strength, "overrides": overrides}
                 for p in a.photo]
        return facade.export(items, a.format, a.quality, a.dest_dir)
    info = facade.open_photo(a.photo)
    if cmd == "open":
        return info
    if cmd == "folder":
        return facade.list_folder(info["image_id"])
    overrides = dict(a.override) if a.override else None
    return facade.preview(info["image_id"], a.preset, a.strength, overrides, a.max_pixels)


def _is_import(a):
    return a.command == "presets" and a.presets_command == "import"


def _line(text, stream):
    stream.write(text + "\n")
    stream.flush()


def _human(a, result):
    if a.command == "export":
        return "\n".join(EXPORTED.format(output_path=r["output"]) if r["ok"] else r["error"]
                         for r in result["results"])
    if _is_import(a):
        return "\n".join(IMPORTED.format(id=r["id"]) if r["ok"] else r["error"] for r in result["results"])
    if a.command == "presets" and a.presets_command == "list":
        lines = [f"{r['id']}\t{r['group']}\t{r['name']}" + ("" if r["supported"] else "\t(unsupported)")
                 for r in result["items"]]
        more = "" if result["next_offset"] is None else f"; next --offset {result['next_offset']}"
        lines.append(f"# {len(result['items'])} of {result['total']}{more}")
        return "\n".join(lines)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _reconfigure():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", newline="\n")   # one line means "\n", never "\r\n"
        except (AttributeError, ValueError):
            pass


def main(argv=None, facade=None):
    _reconfigure()
    a = _parser().parse_args(argv)          # usage errors: argparse exits with 2
    preview_bytes = a.command == "preview" and not a.json
    if preview_bytes and sys.stdout.isatty():
        _line(TTY_REFUSAL, sys.stderr)
        return 2
    if facade is None:
        from .composition import build_facade
        try:
            facade = build_facade(a.preset_dir if a.preset_dir else config.preset_dir())
        except (config.ConfigError, FileNotFoundError) as e:
            _line(CONFIG_ERROR.format(e=e), sys.stderr)
            return 2
    try:
        result = _run(a, facade)
    except DarkroomError as e:
        if a.json:
            _line(json.dumps({"ok": False, "error": {"kind": e.kind, "message": e.message}},
                             ensure_ascii=False, separators=(",", ":")), sys.stdout)
        else:
            _line(e.message, sys.stderr)
        return EXIT[e.kind]
    except Exception as e:
        detail = re.sub(r"\r\n|\r|\n", " ", str(e))
        _line(UNEXPECTED.format(type_name=type(e).__name__, detail=detail), sys.stderr)
        return 1
    if a.command == "preview":
        if a.json:
            result = {"render_ms": result.render_ms, "width": result.width, "height": result.height,
                      "jpeg_base64": base64.b64encode(result.jpeg).decode("ascii")}
        else:
            sys.stdout.flush()
            sys.stdout.buffer.write(result.jpeg)
            sys.stdout.buffer.flush()
            return 0
    if a.json:
        _line(json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")), sys.stdout)
    else:
        _line(_human(a, result), sys.stdout)
    if (a.command == "export" or _is_import(a)) and not all(r["ok"] for r in result["results"]):
        return EXIT_PARTIAL
    return 0


if __name__ == "__main__":
    sys.exit(main())
