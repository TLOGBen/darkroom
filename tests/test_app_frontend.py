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
    """[(enclosing at-rules, selector, declarations)] for every style rule, at any nesting depth.

    Native CSS nesting counts too (H11 / seal round 2 N1): a style rule inside a style rule is recorded with
    the combined selector ("outer inner", or "&" replaced by the outer item), and an at-rule inside a style
    rule keeps the outer selector for its declarations."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []

    def compose(parents, head):
        items = split_selectors(head)
        if not parents:
            return items
        return [c.replace("&", p) if "&" in c else f"{p} {c}" for p in parents for c in items]

    def walk(text, ctx, parents):
        """Records the nested rules of `text`; returns its own declarations (text outside nested blocks)."""
        decls, i = [], 0
        while True:
            j = text.find("{", i)
            if j < 0:
                decls.append(text[i:])
                return "".join(decls)
            seg = text[i:j]
            cut = max(seg.rfind(";"), seg.rfind("}"))
            decls.append(seg[:cut + 1])
            head = seg[cut + 1:].strip()
            depth, k = 1, j + 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if head.startswith("@"):
                at = ctx + (" ".join(head.split()),)
                inner = walk(body, at, parents)
                if parents:
                    rules.append((at, ", ".join(parents), inner))
            else:
                sel = compose(parents, head)
                rules.append((ctx, ", ".join(sel), walk(body, ctx, sel)))
            i = k
    walk(css, (), None)
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


PROTECTED = ("#carry-hint", ".hint", "#reset-all", "#undo", "#redo", "#toggle-lib", "#toggle-sl",
             "#prev", "#next", "#strength-100", "#export-btn", "#export-format", "#export-quality")   # + X13


def hidden_in_media(css):
    """(protected controls hidden inside any @media, number of hiding selector items judged) - H11."""
    found, checked = [], 0
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
            found += [f"{p} hidden in a media query: {item} {{{body.strip()}}} in {ctx}" for p in PROTECTED if p in item]
    return found, checked


class TestHidingJudge(unittest.TestCase):
    """Seal round 2 N1: the H11 judge itself must see native CSS nesting, not only at-rule nesting."""

    def test_native_nesting_is_seen(self):
        for css in ("@media (max-width: 960px) { #topbar { #undo { display: none; } } }",
                    "@media (max-width: 960px) { #topbar { & #undo { visibility: hidden; } } }",
                    "@media (max-width: 960px) { #topbar { color: red; .x, #redo { opacity: 0; } } }",
                    "#topbar { @media (max-width: 960px) { #prev { display: none; } } }",
                    "#undo { @media (max-width: 960px) { display: none; } }"):
            found, _ = hidden_in_media(css)
            self.assertTrue(found, css)

    def test_allowed_and_unrelated_rules_pass(self):
        for css in ("@media (max-width: 960px) { #reset-all { .btn-text { display: none; } } }",
                    "@media (max-width: 960px) { #topbar { #undo { color: red; } } }",
                    "#topbar { #undo { display: none; } }"):              # not in a media query (R6 scope)
            found, _ = hidden_in_media(css)
            self.assertEqual(found, [], css)

    def test_outer_declarations_kept_apart_from_nested_ones(self):
        rules = css_rules("@media (max-width: 1px) { #a { color: red; #b { display: none; } margin: 0; } }")
        self.assertIn((("@media (max-width: 1px)",), "#a #b", " display: none; "), rules)
        outer = [r for r in rules if r[1] == "#a"][0]
        self.assertNotIn("display", outer[2])
        self.assertIn("margin: 0", outer[2])


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

    def test_photo_path_hint_lists_heic(self):  # H7 / seal round 2 N2: the on-screen format hint lists HEIC
        self.assertRegex(read("index.html"), r'id="photo-path" placeholder="照片路徑（JPEG／PNG／TIFF／HEIC），')

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
        found, checked = hidden_in_media(read("app.css"))
        self.assertEqual(found, [])
        self.assertGreater(checked, 0)                                  # the clipped text children are seen
        html = read("index.html")
        for ident in ("reset-all", "undo", "redo", "toggle-lib", "toggle-sl", "prev", "next", "strength-100",
                      "export-btn", "export-format", "export-quality"):                                # + X13
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

    def test_export_controls(self):  # CONTRACT-export X13
        html = read("index.html")
        start = html.index('<div class="pv-tools">')
        toolbar = html[start:html.index("</div>", start)]
        self.assertRegex(toolbar, r'<button id="export-btn"[^>]*\sdisabled>匯出</button>')     # no photo yet: disabled
        self.assertRegex(toolbar, r'<select id="export-format"[^>]*><option value="jpeg" selected>JPEG</option>'
                                  r'<option value="tiff">TIFF</option></select>')
        self.assertRegex(toolbar, r'<input id="export-quality" type="number" min="1" max="100" step="1" value="92"')
        js = read("app.js")
        body = js[js.index("async function exportPhoto"):js.index("function renderPosition")]
        self.assertIn("api('POST', '/api/export'", body)
        self.assertIn("L.EXPORT_BUSY", js)
        self.assertIn("$('#export-quality').disabled = $('#export-format').value !== 'jpeg'", js)
        self.assertIn("b.disabled = !st.image || exp.busy", js)
        for banned in ("dispatch(", "ed =", "ed.", "History", "requestPreview", "dest_dir"):   # never changes the edit
            self.assertNotIn(banned, body, banned)

    def test_section_headers_are_buttons(self):  # R6
        js = read("app.js")
        self.assertIn("aria-expanded", js)
        self.assertRegex(js, r"<button class=\"ah\"")
        self.assertIn("treeKey", js)
        self.assertIn("tabIndex", js)


if __name__ == "__main__":
    unittest.main()
