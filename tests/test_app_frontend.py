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


def css_rules(css):
    """[(enclosing at-rules, selector, declarations)] for every style rule, at any nesting depth."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []

    def walk(text, ctx):
        i = 0
        while True:
            j = text.find("{", i)
            if j < 0:
                return
            head = text[i:j].strip()
            depth, k = 1, j + 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if head.startswith("@"):
                walk(body, ctx + (" ".join(head.split()),))
            else:
                rules.append((ctx, head, body))
            i = k
    walk(css, ())
    return rules


def split_selectors(selector):
    """Split a selector list on top-level commas (not inside parentheses)."""
    out, depth, cur = [], 0, ""
    for ch in selector:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return [" ".join(s.split()) for s in out if s.strip()]


_LEN0 = r"0(?:\.0*)?(?:px|%|em|rem|vw|vh)?"
_HIDING = re.compile(
    r"(?:^|[;{\s])(?:"
    r"display\s*:\s*none"
    r"|visibility\s*:\s*(?:hidden|collapse)"
    r"|(?:max-)?(?:width|height)\s*:\s*(?:" + _LEN0 + r"|1px|0?\.\d+px)\s*(?:;|!|$)"
    r"|opacity\s*:\s*0(?:\.0*)?\s*(?:;|!|$)"
    r"|transform\s*:[^;]*scale[xy]?\(\s*0(?:\.0*)?\s*[,)]"
    r"|clip\s*:\s*rect\("
    r"|clip-path\s*:"
    r"|font-size\s*:\s*0(?:\.0*)?(?:px|em|rem|%)?\s*(?:;|!|$)"
    r"|text-indent\s*:\s*-\d{3,}"
    r"|(?:left|right|top)\s*:\s*-\d{3,}px"
    r")", re.I | re.M)


def hides(body):
    return bool(_HIDING.search(body))


class TestLogicJs(unittest.TestCase):
    def test_logic_suite(self):  # B13 / F3: the front-end suite must run; a missing node is a failure, not a skip
        self.assertIsNotNone(NODE, "node not found: the front-end tests (node --test) cannot be skipped")
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

    def test_narrow_windows_keep_function_buttons(self):  # F1 / R6 / N2 (H11): never hidden in a media query
        css = read("app.css")
        protected = ("#carry-hint", ".hint", "#reset-all", "#undo", "#redo", "#toggle-lib", "#toggle-sl",
                     "#prev", "#next", "#strength-100")
        checked = 0
        for ctx, selector, body in css_rules(css):
            if not any(c.startswith("@media") for c in ctx):          # any depth: @supports inside @media too
                continue
            if not hides(body):
                continue
            for item in split_selectors(selector):                     # judge every comma-separated item
                checked += 1
                # exception (R6 / H11): only the long-text child of a shrunk control may be clipped
                if item.endswith((".hint-text", ".btn-text")):
                    continue
                for p in protected:
                    if p in item:
                        self.fail(f"{p} hidden in a media query: {item} {{{body.strip()}}} in {ctx}")
        self.assertGreater(checked, 0)                                  # the clipped text children are seen
        html = read("index.html")
        for ident in ("reset-all", "undo", "redo", "toggle-lib", "toggle-sl", "prev", "next", "strength-100"):
            tag = re.search(r'<[a-z]+ id="%s"[^>]*>' % ident, html).group(0)
            self.assertNotRegex(tag, r"\shidden(?:[\s=>])", ident)
        self.assertRegex(html, r'<span id="carry-hint"[^>]*title="目前修改尚未儲存，切換照片會沿用"')
        self.assertRegex(html, r'<button id="reset-all"[^>]*title="[^"]+"')

    def test_app_changes_state_only_through_the_reducer(self):  # F2: the tested reducer is the only path
        js = read("app.js")
        self.assertEqual(len(re.findall(r"\bed = L\.reduce\(ed, ", js)), 1)
        # N1 / H10: the only assignments to `ed` are its declaration and the reducer step (no rebinding)
        assigns = [m.group(0).strip() for m in
                   re.finditer(r"(?:let |var |const )?(?<![\w.$])ed\s*(?:=(?![=>])|\+=|\|\|=|&&=|\?\?=)[^;\n]*", js)]
        self.assertEqual(assigns, ["let ed = L.initialEditor()", "ed = L.reduce(ed, action)"])
        self.assertNotRegex(js, r"Object\.assign\(\s*ed\b")
        self.assertNotRegex(js, r"(?<![\w.$])ed\s*\[[^\]]*\]\s*=[^=]")
        self.assertNotRegex(js, r"\bed\.(presetId|strength|tweaks|past|future)\s*=[^=]")
        self.assertNotRegex(js, r"\bed\.tweaks\[[^\]]+\]\s*=[^=]")
        self.assertNotRegex(js, r"delete\s+ed\.")
        self.assertNotRegex(js, r"\bst\.(presetId|strength|tweaks)\b")
        self.assertRegex(js, r"function selectPreset\(id\) \{ return dispatch\(\{type: 'selectPreset', id\}\); \}")
        self.assertNotIn("new L.History", js)

    def test_section_headers_are_buttons(self):  # R6
        js = read("app.js")
        self.assertIn("aria-expanded", js)
        self.assertRegex(js, r"<button class=\"ah\"")
        self.assertIn("treeKey", js)
        self.assertIn("tabIndex", js)


if __name__ == "__main__":
    unittest.main()
