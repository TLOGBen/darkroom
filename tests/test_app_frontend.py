"""Front end: runs the node:test suite for static/logic.js (R3, R5, R6) and checks the page structure."""
import os
import re
import shutil
import subprocess
import unittest

import _util

NODE = shutil.which("node")
STATIC = os.path.join(_util.REPO, "darkroom_app", "static")


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(NODE, "needs node (built-in node:test, nothing installed)")
class TestLogicJs(unittest.TestCase):
    def test_logic_suite(self):
        r = subprocess.run([NODE, "--test", "--test-reporter=tap", os.path.join(_util.REPO, "tests", "js", "test_logic.cjs")],
                           capture_output=True, cwd=_util.REPO, timeout=120)
        out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out)
        self.assertRegex(out, r"# fail 0")


class TestPageStructure(unittest.TestCase):
    def test_three_columns_and_logic_loaded(self):  # B9
        html = read("index.html")
        for ident in ("preset-tree", "preview", "sliders", "strength"):
            self.assertIn(f'id="{ident}"', html)
        self.assertLess(html.index("logic.js"), html.index("app.js"))

    def test_banner_lives_in_the_toolbar(self):  # R4: appearing or vanishing must not push the preview down
        html = read("index.html")
        start = html.index('<div class="pv-tools">')
        toolbar = html[start:html.index("</div>", start)]
        self.assertIn('id="skip-banner"', toolbar)          # an inline element inside the one-line toolbar

    def test_photo_switch_hint(self):  # R5 constant
        self.assertIn("目前修改尚未儲存，切換照片會沿用", read("index.html"))

    def test_strength_reset_is_a_button_and_values_are_text(self):  # R6
        html = read("index.html")
        self.assertRegex(html, r'<button[^>]*id="strength-100"[^>]*>↺ 100%</button>')
        self.assertNotRegex(html, r'<button[^>]*id="strength-value"')

    def test_narrow_layout_rules(self):  # R6: 820 px wide window
        css = read("app.css")
        self.assertRegex(css, r"@media \(max-width: *9\d\dpx\)")
        self.assertIn("lib-collapsed", css)
        # columns sit on fixed grid tracks, so hiding one never drops the preview into a zero-width track
        for col, n in (("col-lib", 1), ("col-pv", 2), ("col-sl", 3)):
            self.assertRegex(css, r"#%s \{ grid-column: %d;" % (col, n))

    def test_section_headers_are_buttons(self):  # R6
        js = read("app.js")
        self.assertIn("aria-expanded", js)
        self.assertRegex(js, r"<button class=\"ah\"")
        self.assertIn("treeKey", js)
        self.assertIn("tabIndex", js)


if __name__ == "__main__":
    unittest.main()
