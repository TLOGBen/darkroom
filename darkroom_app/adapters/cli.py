"""`python -s -m darkroom_app.cli`: the agent's command line over the facade (CONTRACT-layering L9).

    presets list [--query Q] [--offset N] [--limit N]
    presets show <preset_id>
    presets flags
    sliders
    open <photo>
    folder <photo>                      (open, then list the folder, in this one process)
    preview <photo> [--preset ID] [--strength S] [--override KEY=VALUE]... [--max-pixels N] [geometry] [--frame]
    export <photo>... [--preset ID] [--strength S] [--override KEY=VALUE]... [geometry] | --no-edit
                      [--format jpeg|png|tiff|webp] [--bit-depth 8|16] [--quality N] [--max-kb N]
                      [--resize MODE=VALUE] [--metadata all|copyright|none] [--remove-gps] [--sharpen TARGET=AMOUNT]
                      [--export-preset NAME] [--dest-dir D]
                      (no --preset / --strength / --override / --no-edit: each photo's saved edit, CONTRACT-s2 E15)
    export-presets list | save --name N [settings flags...] | delete <name>     (CONTRACT-s2-export-detect E26)
    presets files <id>... | presets export <id>... --dest-dir D | capabilities [--refresh]
    presets list ... [--favorites] | groups | rename <id> <name> | move <id> <group> | favorite <id> on|off
    presets import <path>... [--group G] | save --name N [--group G] [--preset ID] [--strength S] [--override K=V]...
    presets rebuild
    presets semantic build [--limit N] [--dry-run] [--wait-seconds S] | semantic status   (CONTRACT-semantic-index)
    groups create <group> | rename <group> <new>          (CONTRACT-preset-library K16)
    edit get <photo> | set <photo> [--preset ID] [--strength S] [--override KEY=VALUE]... [geometry] | clear <photo>
    edit paste --from <photo> <target>... [--with-geometry] | save-preset <photo> --name N [--group G] | restore <photo>
    [geometry] = --rotate 0|90|180|270 --flip --angle DEG --aspect original|free|W:H --crop L,T,R,B | --no-geometry
                 (CONTRACT-s3-crop C20: any of them = a new geometry from these flags; none = the photo's saved one)
    thumbnails <folder> [--offset N] [--limit N] | thumbnail <photo>      (CONTRACT-photo-library PL6)
    settings get | set KEY=VALUE... | export [--out FILE] | import FILE    (plan-v2 §3; VALUE is JSON when it parses,
                                                                          else text; null resets a key)
    version | --version

Every subcommand takes --json: stdout is then exactly one line {"ok":true,"result":...} or
{"ok":false,"error":{"kind":...,"message":...}} and stderr stays empty. Without --json a failure is one line
on stderr. Exit codes: 0 ok, 1 unexpected, 2 invalid / usage, 3 not_found, 4 conflict, 5 unavailable, 6 export,
presets import, edit paste, presets files or presets export with at least one failed item (stdout still holds every result; CONTRACT-export XP11,
preset library KP5, photo library PLP4). What writes files goes through the facade: `export` (new files), the preset
library commands (the library index, import/ and user/) and the photo library (edits, thumbnails and the thumbnail
index in --data-dir / the configured data folder; photos are only read), `settings set|import` (the settings file)
and `settings export --out` (a new file); `preview` and `thumbnail` without --json write the JPEG bytes to stdout.

Layer: adapters (plan-v2 §1). argparse -> facade -> exit code / --json envelope. Translation only: no rule decides
anything here (which parameters an export item carries is what the user typed; what "no parameters" means is the
export service's rule, E15), and no sentence is built here except the CLI's own usage / TTY / unexpected lines.
Depends on the facade, composition (to build it) and config (`ConfigError`); never on services or domain rules.
Without a configured preset folder only `settings ...` and `version` run (a first-time setup can write preset_dir);
every other command prints the configuration error as before.

Data flow of one invocation: argv -> argparse namespace (values parsed leniently: a number that does not parse is
passed on as text so the service, not argparse, words the refusal identically to HTTP and MCP) -> build_facade ->
`_run` picks the one facade operation -> result -> one JSON envelope line (--json) or human lines (`_human`) ->
exit code.

Contract codes: L9 = the subcommands, usage errors as one stderr line with exit 2, JPEG bytes refused on a
terminal; XP3 / XP11 = export output lines and exit 6 for partial failure; KP2 = where the library root comes from;
KP5 / KP9 / PLP4 = import / favorite / paste output; PL6 / PL13 = photo library commands and thumbnail bytes; PLP8
= the data folder is resolved on first use; E15 / E19 / E26 / IP9 = saved-edit export, relative folders, the S2
flags and lines, exit 6 for preset files; C20 = geometry flags; K16 = group commands.
"""
import argparse
import base64
import json
import os
import re
import sys

from .. import __version__, config
from ..domain import messages as M
from ..domain.errors import DarkroomError
from ..facade import KEEP

EXIT = {"invalid": 2, "not_found": 3, "conflict": 4, "unavailable": 5}
EXIT_PARTIAL = 6                        # export / import / paste: some items failed (CONTRACT-export XP11)
EXPORTED = "已匯出：{output_path}"        # verbatim (XP3)
PRESET_EXPORTED = "已匯出 preset：{output_path}"   # verbatim (S2 E26)
CAP_OK = "{name}\t可用"                  # verbatim (S2 E26)
CAP_OFF = "{name}\t關閉：{reason}"        # verbatim (S2 E26)
PRESET_FILE_LINE = "{file_name}\t{size}"  # verbatim (S2 E26)
IMPORTED = "已匯入：{id}"                 # verbatim (KP5)
PASTED = "已貼上：{target}"               # verbatim (CONTRACT-photo-library PLP4)
BYTES_COMMANDS = ("preview", "thumbnail")   # without --json these write JPEG bytes to stdout (L9, PL13)
FAVORITE_WORDS = {"on": True, "off": False}   # presets favorite <id> on|off; anything else goes to the service (KP9)
UNEXPECTED = "未預期錯誤：{type_name}：{detail}"
TTY_REFUSAL = "預覽是 JPEG 位元組，請導向檔案（> out.jpg）或加 --json"
CONFIG_ERROR = "darkroom：{e}"
NO_PRESET_COMMANDS = ("settings", "version")   # run without a configured preset folder (plan-v2 §3)


def _override(text):
    """--override KEY=VALUE -> (KEY, float) or (KEY, raw text) for the service to refuse; usage error without '='."""
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
    """int when the text is one, else the text itself (the service then says what is wrong, as over HTTP / MCP)."""
    try:
        return int(text)
    except ValueError:
        return text                # the service reports it (JPEG quality, semantic limit)


def _lenient_number(text):
    """int, else float, else the text itself (same reason as _lenient_int)."""
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text            # the service reports it (resize value)


def _pair(first, second):
    """MODE=VALUE / TARGET=AMOUNT -> {first: MODE, second: VALUE}; no '=' -> the raw text for the service to judge."""
    def parse(text):
        key, sep, value = text.partition("=")
        if not sep:
            return text
        return {first: key, second: _lenient_number(value) if second == "value" else value}
    return parse


GEOMETRY_FLAGS = ("rotate", "flip", "angle", "aspect", "crop")      # CONTRACT-s3-crop C20 (+ --no-geometry)


def _crop(text):
    """--crop L,T,R,B -> {left, top, right, bottom}; anything else is a usage error with the constant sentence."""
    parts = text.split(",")
    try:
        values = [float(x) for x in parts]
    except ValueError:
        values = None
    if values is None or len(values) != 4:
        raise argparse.ArgumentTypeError(M.CLI_BAD_CROP.format(value=text))
    return dict(zip(("left", "top", "right", "bottom"), values))


def _geometry_flags(p):
    """C20: the geometry flags; raw values go to the service, which judges them (as XP17)."""
    p.add_argument("--rotate", type=_lenient_int, default=None, help="0, 90, 180 or 270 (clockwise)")
    p.add_argument("--flip", action="store_true", default=None, help="mirror horizontally (after --rotate)")
    p.add_argument("--angle", type=_lenient_number, default=None, help="straighten, -45..45 degrees (+ = clockwise)")
    p.add_argument("--aspect", default=None, help="original (default), free or W:H")
    p.add_argument("--crop", type=_crop, default=None, metavar="L,T,R,B",
                   help="the box in 0..1 of the turned frame (default: the largest box of --aspect)")
    p.add_argument("--no-geometry", action="store_true", help="no rotation, no crop (removes a saved one)")


def _geometry(a, parser):
    """KEEP (no flag: the photo's saved geometry), None (--no-geometry) or a geometry object of exactly the flags
    given (C20; a key left out takes its identity value in Geometry.from_dict - the CLI adds no default of its own)."""
    given = [k for k in GEOMETRY_FLAGS if getattr(a, k) is not None]
    if a.no_geometry:
        if given:
            parser.error(f"argument --no-geometry: not allowed with argument --{given[0]}")
        return None
    if not given:
        return KEEP
    return {k: getattr(a, k) for k in given}


def _settings_flags(p):
    """The export settings (CONTRACT-s2-export-detect E26): raw values go to the service, which judges them."""
    p.add_argument("--format", default=None, help="jpeg (default), png, tiff or webp")
    p.add_argument("--bit-depth", type=_lenient_int, default=None, help="8 or 16 (png / tiff)")
    p.add_argument("--quality", type=_lenient_int, default=None, help="JPEG / WebP quality 1..100 (default 92)")
    p.add_argument("--max-kb", type=_lenient_int, default=None, help="JPEG only: the whole file at most N KB")
    p.add_argument("--resize", type=_pair("mode", "value"), default=None, metavar="MODE=VALUE",
                   help="long_edge|short_edge|width|height|megapixels|percent=VALUE (never enlarged)")
    p.add_argument("--metadata", default=None, help="all (default), copyright or none")
    p.add_argument("--remove-gps", action="store_const", const=True, default=None, help="drop the GPS position")
    p.add_argument("--sharpen", type=_pair("target", "amount"), default=None, metavar="TARGET=AMOUNT",
                   help="screen|matte|glossy=low|standard|high")


def _settings(a):
    """The export settings flags of a namespace as the facade's keyword arguments (None = not given)."""
    return {"format": a.format, "bit_depth": a.bit_depth, "quality": a.quality, "max_kb": a.max_kb,
            "resize": a.resize, "metadata": a.metadata, "remove_gps": a.remove_gps, "sharpen": a.sharpen}


def _setting(text):
    """KEY=VALUE -> (KEY, VALUE): VALUE as JSON when it parses (3, true, null, "x"), else the text itself
    (en-US, D:/photos). Whether the value is acceptable is the settings service's judgement."""
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    try:
        return key, json.loads(value)
    except ValueError:
        return key, value


def _lenient_float(text):
    """float when the text is one, else the text itself."""
    try:
        return float(text)
    except ValueError:
        return text                # the service reports it (semantic wait_seconds)


def _parser():
    """The whole argparse tree (subcommands as in the module docstring; every leaf has --json)."""
    ap = _OneLineParser(prog="python -m darkroom_app.cli",
                                 description="darkroom for agents: presets, sliders, open and preview photos "
                                             "(read-only), export photos as new files")
    ap.add_argument("--version", action="version", version=f"darkroom {__version__}")   # needs no configuration
    ap.add_argument("--preset-dir", default=None, help="default: from LOCALLLMS_ROOT or config.local.json")
    ap.add_argument("--data-dir", default=None, help="photo library folder (default: config data_dir or "
                                                     "%%LOCALAPPDATA%%/darkroom)")
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
    p = leaf(psub, "files", "the presets' .xmp as Lightroom reads them (reads only; --json for the bytes)")
    p.add_argument("preset_id", nargs="*")
    p = leaf(psub, "export", "write the presets' .xmp into an existing folder (never overwrites)")
    p.add_argument("preset_id", nargs="*")
    p.add_argument("--dest-dir", default=None, help="existing absolute folder outside the preset library")
    # CONTRACT-semantic-index SI11
    semantic = psub.add_parser("semantic", help="the semantic index (Claude-written style tags)")
    ssub = semantic.add_subparsers(dest="semantic_command", required=True, metavar="SUBCOMMAND")
    p = leaf(ssub, "build", "send the presets not yet indexed to Claude (costs money; checked against the budget)")
    p.add_argument("--limit", type=_lenient_int, default=None, help="at most this many presets this run")
    p.add_argument("--dry-run", action="store_true", help="only count and estimate the cost; send nothing")
    p.add_argument("--wait-seconds", type=_lenient_float, default=None,
                   help="how long to wait for the batch (default 3600; 0 = return after submitting)")
    leaf(ssub, "status", "how much of the library is indexed, and whether building is available")
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
    _geometry_flags(p)
    p.add_argument("--frame", action="store_true", help="the whole straightened frame, crop ignored (C17)")
    p = leaf(sub, "export", "export photos at full resolution as new files (never overwrites); without --preset / "
                            "--strength / --override each photo's saved edit is used")
    p.add_argument("photo", nargs="*")
    params = p.add_mutually_exclusive_group()
    params.add_argument("--preset", default=None, help="preset id")
    params.add_argument("--no-edit", action="store_true", help="the photos as they are (not their saved edits)")
    p.add_argument("--strength", type=float, default=None, help="percent, 0..200 (default 100)")
    p.add_argument("--override", type=_override, action="append", default=None, metavar="KEY=VALUE",
                   help="slider difference added after strength (repeatable)")
    _geometry_flags(p)
    _settings_flags(p)
    p.add_argument("--export-preset", default=None, metavar="NAME", help="saved export settings (flags win)")
    p.add_argument("--dest-dir", default=None, help="existing absolute folder (default: <photo folder>/darkroom 匯出)")
    xp = sub.add_parser("export-presets", help="saved export settings (CONTRACT-s2-export-detect E13)")
    xsub = xp.add_subparsers(dest="xp_command", required=True, metavar="SUBCOMMAND")
    leaf(xsub, "list", "the saved export presets")
    p = leaf(xsub, "save", "save export settings under a name (the same name is replaced)")
    p.add_argument("--name", default=None)
    _settings_flags(p)
    p = leaf(xsub, "delete", "delete a saved export preset")
    p.add_argument("name")
    p = leaf(sub, "capabilities", "what works on this machine and why not")
    p.add_argument("--refresh", action="store_true", help="measure again")
    # CONTRACT-photo-library PL6 / PLP6
    edit = sub.add_parser("edit", help="the photo library: the edit kept for each photo")
    esub = edit.add_subparsers(dest="edit_command", required=True, metavar="SUBCOMMAND")
    p = leaf(esub, "get", "the edit kept for a photo")
    p.add_argument("photo")
    p = leaf(esub, "set", "replace a photo's edit (preset snapshot, strength, overrides, geometry); nothing chosen "
                          "removes it; no geometry flag keeps the saved geometry")
    p.add_argument("photo")
    p.add_argument("--preset", default=None, help="preset id")
    p.add_argument("--strength", type=float, default=100, help="percent, 0..200 (default 100)")
    p.add_argument("--override", type=_override, action="append", default=None, metavar="KEY=VALUE",
                   help="slider difference added after strength (repeatable)")
    _geometry_flags(p)
    p = leaf(esub, "clear", "remove a photo's edit")
    p.add_argument("photo")
    p = leaf(esub, "paste", "copy one photo's edit onto other photos (their colours are replaced; each keeps its "
                            "own crop / rotation unless --with-geometry)")
    p.add_argument("--from", dest="source", required=True, metavar="PHOTO", help="the photo whose edit is copied")
    p.add_argument("target", nargs="*")
    p.add_argument("--with-geometry", action="store_true", help="also paste the crop / rotation (C14)")
    p = leaf(esub, "save-preset", "save a photo's edit (its preset snapshot x strength + overrides) as a user preset")
    p.add_argument("photo")
    p.add_argument("--name", default=None)
    p.add_argument("--group", default=None, help="default: 自存 preset")
    p = leaf(esub, "restore", "bring back the edit kept when this photo's edit was last cleared")   # S4
    p.add_argument("photo")
    p = leaf(sub, "thumbnails", "the photos of a folder for the thumbnail grid (thumbnails are made in the background)")
    p.add_argument("folder")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=None)
    p = leaf(sub, "thumbnail", "a JPEG thumbnail of a photo")
    p.add_argument("photo")
    # plan-v2 §3: settings and version
    st = sub.add_parser("settings", help="darkroom's settings (the settings file)")
    stsub = st.add_subparsers(dest="settings_command", required=True, metavar="SUBCOMMAND")
    leaf(stsub, "get", "the settings in use, their defaults and where each comes from")
    p = leaf(stsub, "set", "change settings (all checked first; null resets a key)")
    p.add_argument("pair", nargs="+", type=_setting, metavar="KEY=VALUE")
    p = leaf(stsub, "export", "the settings as a document (with --out: also written to a new file)")
    p.add_argument("--out", default=None, metavar="FILE", help="a new file (never overwritten)")
    p = leaf(stsub, "import", "apply a settings document made by `settings export`")
    p.add_argument("file")
    leaf(sub, "version", "darkroom's version and what it runs on")
    return ap


def _run(a, facade, parser=None):
    """Dispatch one parsed command to exactly one facade operation (two for `folder` / `preview`, which open the
    photo first in this same process) and return its result. DarkroomError propagates to main."""
    cmd = a.command
    parser = parser or _parser()
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
        if sc == "files":             # CONTRACT-s2-export-detect E16
            return facade.preset_files(a.preset_id)
        if sc == "export":            # E17
            return facade.export_preset_files(a.preset_id, a.dest_dir)
        if sc == "semantic":          # CONTRACT-semantic-index SI11
            if a.semantic_command == "build":
                return facade.semantic_build(a.limit, a.dry_run, a.wait_seconds)
            return facade.semantic_status()
        return facade.preset_flags()
    if cmd == "groups":
        if a.groups_command == "create":
            return facade.create_group(a.group)
        return facade.rename_group(a.group, a.new)
    if cmd == "sliders":
        return facade.slider_table()
    if cmd == "export":           # every photo is a path item with the flags given; nothing is opened first
        geometry = _geometry(a, parser)
        if a.no_edit and (geometry is not KEEP or a.no_geometry):
            flag = "--no-geometry" if a.no_geometry else "--" + next(k for k in GEOMETRY_FLAGS
                                                                     if getattr(a, k) is not None)
            parser.error(f"argument --no-edit: not allowed with argument {flag}")
        # the item carries exactly what was typed; what an item without parameters means (the saved edit, E15) and
        # the default strength are the export service's rules. --no-edit is "no preset, no geometry" (XP35).
        given = {"preset_id": a.preset, "strength": a.strength,
                 "overrides": dict(a.override) if a.override else None}
        item = {k: v for k, v in given.items() if v is not None}
        if a.no_edit:
            item.update(preset_id=None, geometry=None)
        elif geometry is not KEEP:
            item["geometry"] = geometry
        items = [{"path": p, **item} for p in a.photo]
        s = _settings(a)
        return facade.export(items, s["format"], s["quality"], a.dest_dir, bit_depth=s["bit_depth"],
                             max_kb=s["max_kb"], resize=s["resize"], metadata=s["metadata"],
                             remove_gps=s["remove_gps"], sharpen=s["sharpen"], export_preset=a.export_preset)
    if cmd == "export-presets":   # E13
        if a.xp_command == "list":
            return facade.list_export_presets()
        if a.xp_command == "save":
            return facade.save_export_preset(a.name, {k: v for k, v in _settings(a).items() if v is not None})
        return facade.delete_export_preset(a.name)
    if cmd == "capabilities":     # E22
        return facade.capabilities(a.refresh)
    if cmd == "edit":             # CONTRACT-photo-library PL6: photos are only read, edits live in data_dir
        sc = a.edit_command
        if sc == "get":
            return facade.get_edit(a.photo)
        if sc == "set":
            overrides = dict(a.override) if a.override else None
            return facade.set_edit(a.photo, a.preset, a.strength, overrides, geometry=_geometry(a, parser))
        if sc == "clear":
            return facade.clear_edit(a.photo)
        if sc == "paste":
            if a.with_geometry:
                return facade.paste_edit(a.target, a.source, None, with_geometry=True)
            return facade.paste_edit(a.target, a.source, None)
        if sc == "restore":
            return facade.restore_edit(a.photo)
        return facade.save_edit_as_preset(a.photo, a.name, a.group)
    if cmd == "settings":         # plan-v2 §3
        sc = a.settings_command
        if sc == "get":
            return facade.get_settings()
        if sc == "set":
            return facade.set_settings(dict(a.pair))
        if sc == "export":
            return facade.export_settings(os.path.abspath(a.out) if a.out else None)
        return facade.import_settings(None, os.path.abspath(a.file))
    if cmd == "version":
        return facade.version()
    if cmd == "thumbnails":
        return facade.folder_thumbnails(a.folder, a.offset, a.limit)
    if cmd == "thumbnail":
        return facade.thumbnail(a.photo)
    geometry = _geometry(a, parser) if cmd == "preview" else KEEP     # usage errors before the photo is read
    info = facade.open_photo(a.photo)
    if cmd == "open":
        return info
    if cmd == "folder":
        return facade.list_folder(info["image_id"])
    overrides = dict(a.override) if a.override else None
    extra = {} if geometry is KEEP else {"geometry": geometry}
    if a.frame:
        extra["frame"] = True
    return facade.preview(info["image_id"], a.preset, a.strength, overrides, a.max_pixels, **extra)


def _is_import(a):
    """`presets import`?"""
    return a.command == "presets" and a.presets_command == "import"


def _is_paste(a):
    """`edit paste`?"""
    return a.command == "edit" and a.edit_command == "paste"


def _is_preset_files(a):
    """`presets files`?"""
    return a.command == "presets" and a.presets_command == "files"


def _is_preset_export(a):
    """`presets export`?"""
    return a.command == "presets" and a.presets_command == "export"


def _is_batch(a):
    """Operations whose result is {"results": [...]} with per-item ok (exit 6 when any failed)."""
    return a.command == "export" or _is_import(a) or _is_paste(a) or _is_preset_export(a)


def _items(a, result):
    """The per-item list of a batch result (presets files names it "files")."""
    return result["files"] if _is_preset_files(a) else result["results"]


def _line(text, stream):
    """Write one line and flush (agents read the output as it comes)."""
    stream.write(text + "\n")
    stream.flush()


def _human(a, result):
    """The output without --json: one line per item for batch commands, a tab-separated table for presets list,
    one line per capability, otherwise the result as indented JSON."""
    if a.command == "export":
        return "\n".join(EXPORTED.format(output_path=r["output"]) if r["ok"] else r["error"]
                         for r in result["results"])
    if _is_import(a):
        return "\n".join(IMPORTED.format(id=r["id"]) if r["ok"] else r["error"] for r in result["results"])
    if _is_paste(a):
        return "\n".join(PASTED.format(target=r["target"]) if r["ok"] else r["error"] for r in result["results"])
    if _is_preset_export(a):
        return "\n".join(PRESET_EXPORTED.format(output_path=r["output"]) if r["ok"] else r["error"]
                         for r in result["results"])
    if _is_preset_files(a):
        return "\n".join(PRESET_FILE_LINE.format(file_name=r["file_name"],
                                                 size=len(base64.b64decode(r["data_base64"])))
                         if r["ok"] else r["error"] for r in result["files"])
    if a.command == "capabilities":
        return "\n".join(CAP_OK.format(name=k) if v["available"] else CAP_OFF.format(name=k, reason=v["reason"])
                         for k, v in result["features"].items())
    if a.command == "presets" and a.presets_command == "list":
        lines = [f"{r['id']}\t{r['group']}\t{r['name']}" + ("" if r["supported"] else "\t(unsupported)")
                 + ("\t" + "、".join(r["tags"]) if r.get("tags") else "")
                 for r in result["items"]]
        more = "" if result["next_offset"] is None else f"; next --offset {result['next_offset']}"
        lines.append(f"# {len(result['items'])} of {result['total']}{more}")
        return "\n".join(lines)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _reconfigure():
    """UTF-8 and "\\n" line ends on stdout / stderr (Windows consoles default to a legacy code page and CRLF)."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", newline="\n")   # one line means "\n", never "\r\n"
        except (AttributeError, ValueError):
            pass


def main(argv=None, facade=None):
    """Run one CLI command; returns the exit code (see the module docstring). facade: tests inject a fake.

    Side effects are those of the operation run (see the module docstring); `preview` / `thumbnail` without --json
    write JPEG bytes to stdout and refuse to do so on a terminal."""
    _reconfigure()
    parser = _parser()
    a = parser.parse_args(argv)             # usage errors: argparse exits with 2
    # S2 E19: relative folders are made absolute against the working directory before anything uses them
    a.preset_dir = os.path.abspath(a.preset_dir) if a.preset_dir else a.preset_dir
    a.data_dir = os.path.abspath(a.data_dir) if a.data_dir else a.data_dir
    preview_bytes = a.command in BYTES_COMMANDS and not a.json
    if preview_bytes and sys.stdout.isatty():
        _line(TTY_REFUSAL, sys.stderr)
        return 2
    if facade is None:
        from ..composition import build_facade
        try:
            # KP2: without --preset-dir both the preset folder and the library root come from the configuration;
            # settings / version need no preset folder (a first-time setup writes it)
            facade = build_facade(a.preset_dir, data_dir=a.data_dir,
                                  allow_unconfigured=a.command in NO_PRESET_COMMANDS)
        except (config.ConfigError, FileNotFoundError) as e:
            _line(CONFIG_ERROR.format(e=e), sys.stderr)
            return 2
    try:
        result = _run(a, facade, parser)
    except config.ConfigError as e:         # the data folder is resolved on first use (PLP8): same line, exit 2
        _line(CONFIG_ERROR.format(e=e), sys.stderr)
        return 2
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
    if a.command in BYTES_COMMANDS:
        if a.json:
            if a.command == "preview":
                result = {"render_ms": result.render_ms, "width": result.width, "height": result.height,
                          "jpeg_base64": base64.b64encode(result.jpeg).decode("ascii")}
            else:
                result = {"fingerprint": result.fingerprint, "edited": result.edited, "width": result.width,
                          "height": result.height, "jpeg_base64": base64.b64encode(result.jpeg).decode("ascii")}
        else:
            sys.stdout.flush()
            sys.stdout.buffer.write(result.jpeg)
            sys.stdout.buffer.flush()
            return 0
    if a.json:
        _line(json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")), sys.stdout)
    else:
        _line(_human(a, result), sys.stdout)
    if (_is_batch(a) or _is_preset_files(a)) and not all(r["ok"] for r in _items(a, result)):
        return EXIT_PARTIAL                 # presets files too (S2 IP9)
    return 0


if __name__ == "__main__":
    sys.exit(main())
