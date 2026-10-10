"""Domain layer: business objects and rules, free of I/O (plan-v2 §1).

What lives here: the value objects every entry point shares (`Adjustment`, `Settings`, the edit object, the export
options), the error type and every sentence a service may raise, the slider table, the skipped-settings wording and
the photo extension table.

Dependency rule: domain may import `darkroom` (the core library) and `darkroom_app.utils`; it never imports
services, adapters, the facade, composition or config, and it never opens, writes or lists a file. Functions that
need to know whether a folder exists take the check as a parameter (see `settings.validate_changes`).

Data flow: an entry adapter's raw values (JSON, argparse, MCP arguments) are turned into these objects at the
facade boundary ("VO -> BO": value object in, business object out); a value that does not fit is
DarkroomError("invalid", <verbatim sentence>), so all three entry points refuse it with the same words.

Modules: adjustment (strength + overrides -> Adjustment, final render Params), edits (the photo library's edit
object), export_options (the 8 export settings), settings (the settings keys and their checks), presets (the preset
library's index / semantic schemas and the view), sliders (the slider table), skips (wording and level of settings
a preset cannot apply), formats (photo extensions), messages (every sentence), errors (DarkroomError),
sentinels (KEEP).
"""
