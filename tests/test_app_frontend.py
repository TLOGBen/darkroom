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
             "#prev", "#next", "#strength-100", "#export-btn", "#export-format", "#export-quality",   # + X13
             ".fav", ".row-menu", "#import-btn", "#save-preset-btn",                             # + K19
             "#grid-btn", "#copy-edit-btn", "#paste-edit-btn", "#export-selected-btn")           # + PL15 / PLP9


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
                      "export-btn", "export-format", "export-quality",                                 # + X13
                      "import-btn", "save-preset-btn",                                                 # + K19
                      "grid-btn", "copy-edit-btn", "paste-edit-btn", "export-selected-btn"):           # + PLP9
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
        # seal F3: the real call path, exactly - success / failure entry, request failure, busy text
        self.assertEqual(re.findall(r"toast\([^;]*\);", body),
                         ["toast(L.exportMessage(r), !r.ok);", "toast(L.exportFailed(name, e.message), true);"])
        self.assertIn("const r = res.results[0];", body)
        self.assertIn("const name = L.baseName(st.image.path);", body)
        refresh = js[js.index("function refreshExport"):js.index("async function exportPhoto")]
        self.assertIn("b.textContent = exp.busy ? L.EXPORT_BUSY : '匯出';", refresh)
        self.assertIn("$('#export-quality').disabled = $('#export-format').value !== 'jpeg'", refresh)
        self.assertIn("b.disabled = !st.image || exp.busy", refresh)
        self.assertRegex(body, r"exp\.busy = true;\s*refreshExport\(\);")
        self.assertRegex(body, r"finally \{\s*exp\.busy = false;\s*refreshExport\(\);")
        for banned in ("dispatch(", "ed =", "ed.", "History", "requestPreview", "dest_dir"):   # never changes the edit
            self.assertNotIn(banned, body, banned)

    def test_exported_sentence_same_in_cli_and_page(self):  # seal F5 / XP25: one sentence, two languages
        from darkroom_app import cli
        logic = read("logic.js")
        m = re.search(r"const exportDone = \(outputPath\) => `([^`]*)`;", logic)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).replace("${outputPath}", "{output_path}"), cli.EXPORTED)
        self.assertEqual(cli.EXPORTED, "已匯出：{output_path}")
        m = re.search(r"const exportFailed = \(fileName, reason\) => `([^`]*)`;", logic)
        from darkroom_app import messages
        self.assertEqual(m.group(1).replace("${fileName}", "{file_name}").replace("${reason}", "{reason}"),
                         messages.EXPORT_FAILED)

    def test_preset_library_controls(self):  # CONTRACT-preset-library K19 / KP4
        html = read("index.html")
        start = html.index('<div class="pv-tools">')
        toolbar = html[start:html.index("</div>", start)]
        self.assertRegex(toolbar, r'<button id="save-preset-btn"[^>]*\sdisabled>存成 preset</button>')
        lib = html[html.index('<section class="col" id="col-lib">'):html.index('<section class="col" id="col-pv">')]
        self.assertRegex(lib, r'<button id="import-btn"[^>]*>匯入</button>')
        self.assertRegex(lib, r'<input type="file" id="import-file" multiple accept="\.xmp" hidden>')
        js = read("app.js")
        # favorites first in the tree, toggles carry aria-pressed, rows get an action menu
        render = js[js.index("function renderTree"):js.index("function focusRow")]
        self.assertLess(render.index("★ 最愛"), render.index("buildTree()"))
        self.assertIn("L.FAV_EMPTY", render)
        self.assertIn('aria-pressed="${!!p.favorite}"', js)
        self.assertIn("presetMenu(p, e.currentTarget)", js)
        self.assertIn("groupMenu(path, e.currentTarget)", js)
        for label in ("'改名…'", "'搬到…'", "'新群組…'", "'群組改名…'"):
            self.assertIn(label, js)
        # import: uploaded bytes in batches, never a path; one line per file
        imp = js[js.index("async function importFiles"):js.index("function refreshSavePreset")]
        self.assertIn("{files: batch}", imp)
        self.assertIn("L.uploadBatches(files)", imp)
        self.assertIn("L.importReport(results)", imp)
        self.assertNotIn("paths", imp)
        # save as preset never changes the edit (no dispatch, no undo step) and is disabled without anything to save
        save = js[js.index("function refreshSavePreset"):js.index("// ------------------------------------------------------------------ photos")]
        self.assertIn("$('#save-preset-btn').disabled = !L.canSavePreset(ed);", save)
        self.assertIn("L.presetSaved(r.name)", save)
        for banned in ("dispatch(", "History", "requestPreview"):
            self.assertNotIn(banned, save, banned)
        self.assertNotRegex(save, r"(?<![\w.$])ed\s*=(?!=)")
        self.assertIn("refreshSavePreset();\n  const sameState", js)

    def test_library_sentences_same_in_page_and_contract(self):  # K19 constants
        logic = read("logic.js")
        self.assertIn("const presetSaved = (name) => `已存成 preset：${name}`;", logic)
        self.assertIn("const importSummary = (ok, fail) => `已匯入 ${ok} 個，${fail} 個沒有匯入`;", logic)
        self.assertIn("const FAV_EMPTY = '還沒有最愛，按 preset 旁的 ☆ 加入';", logic)
        self.assertIn("const groupCreated = (group) => `已建立群組：${group}`;", logic)       # seal F4
        self.assertIn("(r) => L.groupCreated(r.group));", read("app.js"))
        from darkroom_app import cli
        m = __import__("re").search(r"const importedLine = \(id\) => `([^`]*)`;", logic)
        self.assertEqual(m.group(1).replace("${id}", "{id}"), cli.IMPORTED)

    def test_photo_library_controls(self):  # CONTRACT-photo-library PL15 / PLP9
        html = read("index.html")
        self.assertRegex(html, r'<button id="grid-btn"[^>]*>.*縮圖格.*</button>')
        grid = html[html.index('<main id="grid" hidden>'):html.index("</main>", html.index('<main id="grid"'))]
        for ident in ("grid-path", "grid-load", "grid-count", "grid-cells"):
            self.assertIn(f'id="{ident}"', grid, ident)
        self.assertRegex(grid, r'<button id="copy-edit-btn"[^>]*\sdisabled>複製編輯</button>')
        self.assertRegex(grid, r'<button id="paste-edit-btn"[^>]*\sdisabled>貼上編輯</button>')
        self.assertRegex(grid, r'<button id="export-selected-btn"[^>]*\sdisabled>匯出所選</button>')
        toolbar = html[html.index('<div class="pv-tools">'):html.index("</div>", html.index('<div class="pv-tools">'))]
        self.assertIn('id="edit-status"', toolbar)
        js = read("app.js")
        # autosave: every change goes through dispatch -> scheduleSave; the PUT lives in sendSave only
        self.assertIn("if (!(opts && opts.restore)) scheduleSave();", js)
        self.assertEqual(js.count("api('PUT'"), 1)
        send = js[js.index("async function sendSave"):js.index("async function flushSave")]
        self.assertIn("api('PUT', '/api/edit', body, {keepalive: true})", send)      # seal F3: survives unload
        self.assertIn("toast(L.saveEditFailed(e.message), true);", send)
        self.assertIn("window.addEventListener('beforeunload', () => { if (save.dirty) flushSave(); });", js)
        self.assertIn("fetch(url, Object.assign({method, headers:", js)
        self.assertIn("save.timer = setTimeout(flushSave, L.AUTOSAVE_MS);", js)
        # restoring a saved edit goes through the reducer with {restore: true} and never schedules a save
        restore = js[js.index("function restore(res)"):js.index("async function loadEdit")]
        self.assertIn("dispatch({type: 'restoreEdit', edit: res.edit}, {restore: true});", restore)
        self.assertNotIn("scheduleSave", restore)
        self.assertNotRegex(restore, r"(?<![\w.$])ed\s*=(?!=)")
        load = js[js.index("async function loadEdit"):js.index("// ------------------------------------------------------------------ photo library: the grid")]
        self.assertNotIn("scheduleSave", load)                      # get_edit failed: never saved over
        self.assertIn("applyEditInfo({edit: null, preset_status: null}); toast(L.loadEditFailed(e.message), true);", load)
        self.assertIn("catch (e) { toast(L.loadFolderFailed(e.message), true); return; }", js)
        for raw in ("'儲存編輯失敗：'", "'讀取編輯失敗：'", "'讀取資料夾失敗：'"):   # seal F6: sentences live in logic.js
            self.assertNotIn(raw, js, raw)
        opened = js[js.index("async function openPhoto"):js.index("// ------------------------------------------------------------------ photo library: autosave")]
        self.assertLess(opened.index("await flushSave();"), opened.index("api('POST', '/api/open'"))
        self.assertLess(opened.index("await loadEdit(path);"), opened.index("requestPreview();"))
        # the grid: thumbnails through api() once visible, selection through L.gridSelect
        grid_js = js[js.index("// ------------------------------------------------------------------ photo library: the grid"):js.index("// ------------------------------------------------------------------ export (X13)")]
        self.assertIn("api('GET', '/api/thumbnail?path=' + encodeURIComponent(cell.dataset.path))", grid_js)
        self.assertIn("r.headers.get('X-Edited') === '1'", grid_js)
        self.assertIn("IntersectionObserver", grid_js)
        self.assertIn("L.gridSelect(st.grid.sel, i, mods, st.grid.anchor)", grid_js)
        self.assertIn("$('#copy-edit-btn').disabled = !st.edit;", grid_js)
        self.assertIn("$('#paste-edit-btn').disabled = !(st.clipboard && st.grid.sel.size > 0);", grid_js)
        self.assertIn("$('#export-selected-btn').disabled = !(st.grid.sel.size > 0);", grid_js)
        self.assertIn("confirm(L.pasteConfirm(st.clipboard.name, targets.length))", grid_js)
        self.assertIn("api('POST', '/api/edit/paste', {targets, edit: st.clipboard.edit})", grid_js)
        self.assertIn("toast(L.copied(st.clipboard.name));", grid_js)
        self.assertIn("toast(L.pasteDone(ok, res.results.length - ok)", grid_js)
        export_sel = grid_js[grid_js.index("async function exportSelected"):]
        self.assertIn("L.exportItems(paths, edits)", export_sel)
        self.assertIn("api('POST', '/api/export', body)", export_sel)
        self.assertIn("toast(L.exportSelectedDone(ok, fail)", export_sel)
        for banned in ("dest_dir", "dispatch(", "History"):
            self.assertNotIn(banned, export_sel, banned)
        # save as preset: with a photo open, the photo library's edit is the source (PLP6)
        save = js[js.index("async function savePreset"):js.index("// ------------------------------------------------------------------ photo library: autosave")]
        self.assertIn("api('POST', '/api/edit/save-preset', {path: st.image.path, name, group: group || L.USER_GROUP})", save)
        self.assertLess(save.index("await flushSave();"), save.index("/api/edit/save-preset"))
        # seal F4: a carried-over state that was never changed has no edit; the library flow saves it instead
        self.assertIn("if (st.image && st.edit) {", save)
        self.assertLess(save.index("/api/edit/save-preset"), save.index("libraryCall('save', L.saveBody(req, name, group)"))

    def test_photo_library_sentences_same_in_page_and_contract(self):  # PL15 / PLP9 constants
        logic = read("logic.js")
        self.assertIn("const AUTOSAVE_MS = 500;", logic)
        self.assertIn("const PRESET_CHANGED = 'preset 已變更，這份編輯用的是當時的 preset 快照';", logic)
        self.assertIn("const PRESET_MISSING = 'preset 已不在庫裡，這份編輯用的是當時的 preset 快照';", logic)
        self.assertIn("const copied = (sourceName) => `已複製 ${sourceName} 的編輯`;", logic)
        self.assertIn("const pasteConfirm = (sourceName, n) => `要用 ${sourceName} 的編輯取代 ${n} 張照片的編輯嗎？`;", logic)
        self.assertIn("const pasteDone = (ok, failed) => `已貼上 ${ok} 張，失敗 ${failed} 張`;", logic)
        self.assertIn("const exportSelectedDone = (ok, failed) => `已匯出 ${ok} 張，失敗 ${failed} 張`;", logic)
        self.assertIn("const gridCount = (n, total) => `已選 ${n}／${total} 張`;", logic)
        self.assertIn("const saveEditFailed = (reason) => `儲存編輯失敗：${reason}`;", logic)          # PLP17
        self.assertIn("const loadEditFailed = (reason) => `讀取編輯失敗：${reason}`;", logic)
        self.assertIn("const loadFolderFailed = (reason) => `讀取資料夾失敗：${reason}`;", logic)

    def test_section_headers_are_buttons(self):  # R6
        js = read("app.js")
        self.assertIn("aria-expanded", js)
        self.assertRegex(js, r"<button class=\"ah\"")
        self.assertIn("treeKey", js)
        self.assertIn("tabIndex", js)


if __name__ == "__main__":
    unittest.main()
