"""Hatchling build hook: put the built web front end into the wheel when it exists.

Why a hook and not `[tool.hatch.build.targets.wheel.force-include]`: a static force-include fails the whole build
when the source path is missing, and `web/dist` only exists after `npm run build` in `web/`. CI's release job builds
the web first, so the release wheel always carries the page; a developer building a wheel from a fresh checkout (or
the Python CI job, which never builds the web) still gets a working wheel, just without `web_dist`.

Where it lands: `darkroom_app/web_dist/` inside the wheel (the same folder layout as `web/dist`, i.e.
`darkroom_app/web_dist/index.html`, `darkroom_app/web_dist/assets/...`). The server looks there when it runs from an
installed wheel, and at `<repo>/web/dist` when it runs from a source checkout.

Referenced from pyproject.toml ([tool.hatch.build.targets.wheel.hooks.custom] path = ...).
"""
from __future__ import annotations

import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# Path inside the wheel (and therefore inside site-packages) that receives web/dist.
WEB_DIST_TARGET = "darkroom_app/web_dist"


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        # self.root is the project root (the folder holding pyproject.toml), whatever the hook file's location.
        dist = os.path.join(self.root, "web", "dist")
        if os.path.isfile(os.path.join(dist, "index.html")):
            # force_include maps an absolute source path to a path inside the wheel; a folder is copied recursively.
            build_data["force_include"][dist] = WEB_DIST_TARGET
            self.app.display_info(f"darkroom: including web/dist as {WEB_DIST_TARGET}/")
        else:
            self.app.display_warning("darkroom: web/dist not built; the wheel has no web front end "
                                     "(run `npm run build` in web/ first for a release wheel)")
