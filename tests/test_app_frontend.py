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
             "#prev", "#next", "#strength-100", "#export-btn", "#xd-format", "#xd-quality",   # + X13 (XP33: in the dialog)
             ".fav", ".row-menu", "#import-btn", "#save-preset-btn",                             # + K19
             "#grid-btn", "#copy-edit-btn", "#paste-edit-btn", "#export-selected-btn",           # + PL15 / PLP9
             "#ab-btn", "#reset-original-btn", "#restore-previous-btn", "#grid-filter",          # + S18
             "#grid-reset-original-btn", "#grid-restore-btn", ".canvas-pick",
             # + S2 E29 / E30: the export dialog and every control in it, the capability status, the menus' new items
             "#export-dialog", "#export-backdrop", ".xd", "#xd-preset", "#xd-preset-save", "#xd-preset-delete", "#xd-bit-depth",
             "#xd-max-kb-on", "#xd-max-kb", "#xd-resize-mode", "#xd-resize-value", "#xd-metadata", "#xd-remove-gps",
             "#xd-sharpen-target", "#xd-sharpen-amount", "#xd-summary", "#xd-go", "#xd-cancel", "#cap-btn", "#cap-refresh",
             "#cap-detail", ".menu-pop")


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

    def test_photo_switch_hint(self):  # R5 constant as revised by S11 (CONTRACT-s1-experience)
        html = read("index.html")
        self.assertIn("沿用上一張的設定（還不是這張的編輯，會再沿用到下一張）", html)
        self.assertNotIn("目前修改尚未儲存", html)
        self.assertIn("const CARRY_HINT = '沿用上一張的設定（還不是這張的編輯，會再沿用到下一張）';", read("logic.js"))
        self.assertIn("$('#carry-hint').hidden = !L.carryHintVisible(ed, !!st.image, !!st.edit);", read("app.js"))

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

    def test_layout_820(self):  # S18: at 820 px the strength track keeps >= 200 px and the preview >= 400 px
        css = re.sub(r"/\*.*?\*/", "", read("app.css"), flags=re.S)
        self.assertRegex(css, r"\.strength-track \{[^}]*min-width: 200px;")
        narrow = [(ctx, sel, body) for ctx, sel, body in css_rules(css) if "@media (max-width: 960px)" in ctx]
        root = "".join(body for _, sel, body in narrow if sel == ":root")
        sl_w = int(re.search(r"--sl-w:\s*(\d+)px", root).group(1))
        grid = "".join(body for _, sel, body in narrow if sel == "#editor")
        self.assertIn("grid-template-columns: 0 minmax(0, 1fr) var(--sl-w);", grid)   # the preset column folds to 0
        self.assertGreaterEqual(820 - sl_w, 400)                                     # what is left is the preview
        # measured in a browser (S1 seal evidence): #strength 319 px, .pv-wrap 529 px, every S18 button in view

    def test_narrow_windows_keep_function_buttons(self):  # F1 / R6 / N2 (H11): never hidden in a media query
        found, checked = hidden_in_media(read("app.css"))
        self.assertEqual(found, [])
        self.assertGreater(checked, 0)                                  # the clipped text children are seen
        html = read("index.html")
        for ident in ("reset-all", "undo", "redo", "toggle-lib", "toggle-sl", "prev", "next", "strength-100",
                      "export-btn", "xd-format", "xd-quality",                                         # + X13 (XP33)
                      "import-btn", "save-preset-btn",                                                 # + K19
                      "grid-btn", "copy-edit-btn", "paste-edit-btn", "export-selected-btn",            # + PLP9
                      "ab-btn", "reset-original-btn", "restore-previous-btn", "grid-filter",            # + S18
                      "grid-reset-original-btn", "grid-restore-btn",
                      # + S2 E29 / E30
                      "export-dialog", "xd-preset", "xd-preset-save", "xd-preset-delete", "xd-bit-depth", "xd-max-kb-on",
                      "xd-max-kb", "xd-resize-mode", "xd-resize-value", "xd-metadata", "xd-remove-gps", "xd-sharpen-target",
                      "xd-sharpen-amount", "xd-summary", "xd-go", "xd-cancel", "cap-btn", "cap-refresh"):
            tag = re.search(r'<[a-z]+ id="%s"[^>]*>' % ident, html).group(0)
            self.assertNotRegex(tag, r"\shidden(?:[\s=>])", ident)
        self.assertRegex(html, r'<span id="carry-hint"[^>]*title="沿用上一張的設定（還不是這張的編輯，會再沿用到下一張）"')
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
        # XP33: the format menu and the quality input moved into the export dialog (#xd-format, #xd-quality)
        self.assertNotIn("export-format", html)
        self.assertNotIn("export-quality", html)
        dialog = html[html.index('<form id="export-dialog"'):html.index("</form>", html.index('<form id="export-dialog"'))]
        self.assertRegex(dialog, r'<select id="xd-format"[^>]*><option value="jpeg">JPEG</option><option value="png">PNG</option>'
                                 r'<option value="tiff">TIFF</option><option value="webp">WebP</option></select>')
        self.assertRegex(dialog, r'<input id="xd-quality" type="number" min="1" max="100" step="1" value="92"')
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
        self.assertIn("refreshDialog();", refresh)                    # XP33 / E29: the dialog decides what is disabled
        dlg = js[js.index("function refreshDialog"):js.index("function renderExportPresets")]
        self.assertIn("const ds = L.exportDialogState(s, st.caps);", dlg)
        self.assertIn("$('#xd-quality').disabled = ds.quality.disabled;", dlg)
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
        # S2 E29: the export presets' PUT is the only other one (putExportPreset); the edit's PUT is in sendSave only
        self.assertEqual(js.count("api('PUT'"), 2)
        self.assertEqual(js.count("api('PUT', '/api/edit'"), 1)
        put_xp = js[js.index("async function putExportPreset"):js.index("async function deleteExportPreset")]
        self.assertEqual(put_xp.count("api('PUT', '/api/export-presets'"), 1)
        send = js[js.index("async function sendSave"):js.index("async function flushSave")]
        self.assertIn("api('PUT', '/api/edit', body, {keepalive: true})", send)      # seal F3: survives unload
        self.assertIn("toast(L.saveEditFailed(L.explain(e.message)), true, e.message);", send)
        self.assertIn("window.addEventListener('beforeunload', () => { if (save.dirty) unloadSave(); });", js)
        self.assertIn("fetch(url, Object.assign({method, headers:", js)
        self.assertIn("save.timer = setTimeout(flushSave, L.AUTOSAVE_MS);", js)
        # restoring a saved edit goes through the reducer with {restore: true} and never schedules a save
        restore = js[js.index("function restore(res)"):js.index("async function loadEdit")]
        self.assertIn("dispatch({type: 'restoreEdit', edit: res.edit}, {restore: true});", restore)
        self.assertNotIn("scheduleSave", restore)
        self.assertNotRegex(restore, r"(?<![\w.$])ed\s*=(?!=)")
        load = js[js.index("async function loadEdit"):js.index("// ------------------------------------------------------------------ photo library: the grid")]
        self.assertNotIn("scheduleSave", load)                      # get_edit failed: never saved over
        self.assertIn("applyEditInfo({edit: null, preset_status: null}); toast(L.loadEditFailed(L.explain(e.message)), true, e.message);", load)
        self.assertIn("catch (e) { toast(L.loadFolderFailed(L.explain(e.message)), true, e.message); return; }", js)
        for raw in ("'儲存編輯失敗：'", "'讀取編輯失敗：'", "'讀取資料夾失敗：'"):   # seal F6: sentences live in logic.js
            self.assertNotIn(raw, js, raw)
        opened = js[js.index("async function openPhoto"):js.index("function openFailed")]
        self.assertLess(opened.index("await flushSave();"), opened.index("api('POST', '/api/open'"))
        self.assertLess(opened.index("await loadEdit(path, token);"), opened.index("requestPreview();"))

    def test_autosave_targets_the_photo_it_was_scheduled_for(self):  # CONTRACT-s1-experience S1 / S2
        js = read("app.js")
        sched = js[js.index("function scheduleSave"):js.index("async function sendSave")]
        # the path and the request body are fixed when the change is scheduled; nothing is scheduled while a
        # photo is loading (between the st.image swap and the restore of its saved edit)
        self.assertIn("if (!st.image || st.loading) return;", sched)
        self.assertIn("save.pending = {path, req: L.editRequest(ed, path, st.snapshots, st.fingerprint), retried: false};", sched)
        flush = js[js.index("async function flushSave"):js.index("function unloadSave")]
        self.assertNotIn("st.image", flush)                         # flushSave never reads the open photo
        self.assertIn("const job = save.pending; save.pending = null; save.dirty = false;", flush)
        send = js[js.index("async function sendSave"):js.index("async function flushSave")]
        self.assertIn("const {path, req} = job;", send)
        self.assertIn("if (req.method === 'PASTE') {", send)        # S2: the remembered snapshot goes through paste
        self.assertIn("api('POST', '/api/edit/paste', req.body, {keepalive: true})", send)
        paste = send[send.index("if (req.method === 'PASTE') {"):send.index("} else {")]
        # seal F5: after the paste the page re-reads the edit, so st.edit is the saved edit (no carry hint)
        self.assertIn("res = await (await api('GET', '/api/edit?path=' + encodeURIComponent(path))).json();", paste)
        self.assertNotRegex(paste, r"res\s*=\s*r\b")
        # seal F4 / S13 (g): a failed save is dirty again at once and kept for unload during its back-off
        self.assertIn("save.retries.set(path, Object.assign({}, job, {retried: true})); save.dirty = true;", send)
        self.assertIn("setTimeout(() => flushRetry(path), L.SAVE_RETRY_MS);", send)
        unload = js[js.index("function unloadSave"):js.index("function applyEditInfo")]
        self.assertIn("const jobs = L.unloadJobs(save.pending, [...save.retries.values()]);", unload)
        self.assertIn("for (const job of jobs) sendSave(job);", unload)
        flush = js[js.index("async function flushSave"):js.index("async function flushRetry")]
        self.assertIn("if (save.retries.size) save.dirty = true;", flush)
        # S13g'''' (seal H4): flushSave waits until nothing is in flight - every flush before a re-read rests on it
        self.assertEqual([l.strip() for l in flush.splitlines()[1:] if l.strip()][:-1], [
            "clearTimeout(save.timer); save.timer = null;",
            "while (save.pending || save.promise) {",
            "if (save.promise) { await save.promise; continue; }",
            "const job = save.pending; save.pending = null; save.dirty = false;",
            "if (save.retries.size) save.dirty = true;   // a failed save still waits for its retry: unload must send it",
            "save.promise = sendSave(job).finally(() => { save.promise = null; });",
            "}"])
        self.assertIn("save.retries.delete(path);", sched)
        # seal round 2 (N1 / N1b / N2): the retry really goes out - once, after other photos, never over newer
        retry = js[js.index("async function flushRetry"):js.index("async function flushRetries")]
        self.assertEqual([l.strip() for l in retry.splitlines()[1:] if l.strip()][:-1], [
            "const r = save.retries.get(path);",
            "if (!r) return;",
            "const due = L.retryDue(save.pending && save.pending.path, path);",
            "if (due === 'superseded') { save.retries.delete(path); return; }",
            "if (due === 'after') await flushSave();          // another photo's pending save goes first",
            "if (save.retries.get(path) !== r) return;          // superseded (or sent) meanwhile",
            "save.retries.delete(path);",
            "if (save.pending && save.pending.path === path) return;",
            "save.pending = r;",
            "await flushSave();"])
        retries = js[js.index("async function flushRetries"):js.index("function unloadSave")]
        self.assertIn("for (const path of [...save.retries.keys()]) await flushRetry(path);", retries)
        # S13g'''' (seal F2): a retry another caller already took is waited out before anything is read
        self.assertRegex(retries, r"await flushRetry\(path\);\n\s*await flushSave\(\);[^\n]*\n\}")
        op = js[js.index("async function openPhoto"):js.index("function openFailed")]
        self.assertLess(op.index("await flushSave();"), op.index("await flushRetries();"))   # N5: both settled
        self.assertLess(op.index("await flushRetries();"), op.index("api('POST', '/api/open'"))  # before re-read
        # S13g'''' (seal F2): the newest click wins even while the flushes wait - token first, checked after them
        self.assertLess(op.index("const token = ++openSeq;"), op.index("await flushSave();"))
        self.assertRegex(op, r"await flushRetries\(\);[^\n]*\n\s*if \(token !== openSeq\) return;\n\s*setStatus\('讀取照片中…'")
        # S13g'''' (seal F1 / F4): restore previous re-checks after the flushes - same photo, not loading, still no edit
        rp = js[js.index("async function restorePrevious"):js.index("function copyEdit")]
        guard = "if (!st.image || st.image.path !== path || st.loading || st.edit) return;"
        self.assertLess(rp.index("const path = st.image.path;"), rp.index("await flushSave();"))
        self.assertLess(rp.index("await flushRetries();"), rp.index(guard))
        self.assertLess(rp.index(guard), rp.index("api('POST', '/api/edit/restore'"))
        # N6 (seal re-verification 2): every user-level write or read of saved edits settles the retries first
        for start, end in (("async function openPhoto", "function openFailed"),
                           ("async function savePreset", "// ------------------------------------------------------------------ photo library: autosave"),
                           ("async function gridResetOriginal", "async function gridRestore"),
                           ("async function gridRestore", "async function resetOriginal"),
                           ("async function restorePrevious", "// ------------------------------------------------------------------ export (X13)"),
                           ("async function pasteEdit", "async function exportSelected"),
                           ("async function exportSelected", "// ------------------------------------------------------------------ export (X13)")):
            body = js[js.index(start):js.index(end, js.index(start))]
            i = body.index("await flushSave();")
            self.assertRegex(body[i:], r"^await flushSave\(\);[^\n]*\n\s*await flushRetries\(\);", start)
        self.assertIn("if (st.image && st.image.path === path) applyEditInfo(res);", send)
        opened = js[js.index("async function openPhoto"):js.index("function openFailed")]
        self.assertLess(opened.index("await flushSave();"), opened.index("st.loading = token;"))
        self.assertLess(opened.index("st.loading = token;"), opened.index("st.image = Object.assign(info, {path});"))
        self.assertIn("st.snapshots = {}; st.fingerprint = null; st.previous = false; st.editStatus = null;", opened)
        self.assertEqual(opened.count("if (token !== openSeq) return;"), 4)   # latest open wins, at every await
        self.assertLess(opened.index("await loadEdit(path, token);"), opened.index("st.loading = null;"))
        load = js[js.index("async function loadEdit"):js.index("// ------------------------------------------------------------------ photo library: the grid")]
        self.assertIn("if (!st.image || st.image.path !== path || (token !== undefined && token !== openSeq)) return;", load)
        apply = js[js.index("function applyEditInfo"):js.index("function restore(res)")]
        self.assertIn("if (res.edit && res.edit.preset) st.snapshots[res.edit.preset.id] = res.edit.preset;", apply)

    def test_export_commits_carried_state(self):  # S11: what the screen shows is what gets saved and exported
        js = read("app.js")
        body = js[js.index("async function exportPhoto"):js.index("function renderPosition")]
        self.assertLess(body.index("await commitCarried();"), body.index("api('POST', '/api/export'"))
        commit = js[js.index("async function commitCarried"):js.index("async function exportPhoto")]
        self.assertIn("if (!st.image || st.edit || !L.carryHintVisible(ed, true, false)) return;", commit)
        self.assertIn("scheduleSave();\n  await flushSave();", commit)

    def test_skip_detail_structure(self):  # S12: the full text opens over the preview, the toolbar stays one line
        html = read("index.html")
        wrap = html[html.index('<div class="pv-wrap" id="preview">'):html.index('<div class="strength">')]
        self.assertRegex(wrap, r'<div id="skip-detail" class="skip-detail" role="dialog"[^>]*\shidden>')
        self.assertRegex(html, r'<span id="skip-banner" class="warnbar" role="button" tabindex="0" hidden>')
        self.assertRegex(html, r'<span id="skip-note" class="skipnote" role="button" tabindex="0" hidden>')
        js = read("app.js")
        self.assertIn("renderSkipDetail(b, n);", js[js.index("async function loadPreset"):js.index("function selectPreset")])
        self.assertIn("if (e.key === 'Escape' && !$('#skip-detail').hidden) toggleSkipDetail(false);", js)
        css = read("app.css")
        self.assertRegex(css, r"\.skip-detail \{[^}]*position: absolute;[^}]*white-space: normal;")

    def test_front_end_housekeeping(self):  # S13 (a)-(h), (j)-(l)
        js, html, css = read("app.js"), read("index.html"), read("app.css")
        exp = js[js.index("async function exportSelected"):js.index("// ------------------------------------------------------------------ export (X13)")]
        self.assertIn("if (!paths.length || exp.busy) return;", exp)                           # (a)
        self.assertIn("btn.disabled = true; btn.textContent = L.EXPORT_BUSY;", exp)
        self.assertRegex(exp, r"finally \{\s*exp\.busy = false;")
        self.assertIn("showGridResult(L.exportSelectedDone(ok, fail), lines);", exp)           # (b)
        self.assertIn("lines.push(`${L.baseName(r.source)}：${L.explain(r.error)}`)", exp)
        self.assertIn('<div id="grid-result" class="import-result" role="status" hidden></div>', html)
        self.assertIn("!inField(e.target) && !e.repeat) step(-1);", js)                        # (c)
        self.assertIn("!inField(e.target) && !e.repeat) step(1);", js)
        self.assertIn("el.matches('input, select, textarea')", js)
        self.assertIn("window.addEventListener('blur', () => { if (st.holding) showOriginal(false); });", js)   # (d)
        self.assertIn("if (document.hidden && st.holding) showOriginal(false);", js)
        rel = js[js.index("function releaseGrid"):js.index("function renderGrid")]              # (e)
        self.assertIn("gridIO.unobserve(cell);", rel)
        self.assertIn("URL.revokeObjectURL(img.src);", rel)
        self.assertIn("img.onload = () => URL.revokeObjectURL(url);", js)
        self.assertIn("if (st.grid.folder !== null) return;", js[js.index("function showGrid"):js.index("async function loadGrid")])   # (f)
        self.assertIn("function unloadSave()", js)                                                # (g)
        self.assertIn("if (!job.retried) {", js)
        paste = js[js.index("async function pasteEdit"):js.index("async function exportSelected")]   # (h)
        self.assertLess(paste.index("await flushSave();"), paste.index("confirm(L.pasteConfirm("))
        self.assertIn("const GRID_EMPTY = '這個資料夾沒有支援的照片（JPEG／PNG／TIFF／HEIC）';", read("logic.js"))   # (j)
        self.assertIn("e.textContent = L.GRID_EMPTY;", js)
        self.assertRegex(css, r"#grid-count(?:, #grid-pending)? \{[^}]*white-space: nowrap;")    # (k)
        self.assertIn('<link rel="icon" href="/static/logo.svg" type="image/svg+xml">', html)    # (l)
        with open(os.path.join(STATIC, "logo.svg"), "rb") as f, \
                open(os.path.join(_util.REPO, "docs", "assets", "logo.svg"), "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_query_path_not_auto_opened(self):  # S15: ?path= only fills the box; lastPath still reopens
        js = read("app.js")
        init = js[js.index("async function init"):]
        self.assertIn("if (q) $('#photo-path').value = q;", init)
        self.assertIn("else if (last) { $('#photo-path').value = last; openPhoto(last); }", init)
        self.assertNotRegex(init, r"openPhoto\(q\)")
        self.assertNotRegex(init, r"openPhoto\(\s*(?:params|new URLSearchParams|location)")

    def test_ab_compare_structure(self):  # S7
        html, js, css = read("index.html"), read("app.js"), read("app.css")
        toolbar = html[html.index('<div class="pv-tools">'):html.index("</div>", html.index('<div class="pv-tools">'))]
        self.assertRegex(toolbar, r'<span class="seg"><button id="hold"[^>]*>按住看原圖</button><button id="ab-btn"[^>]*aria-pressed="false" disabled>對照</button></span>')
        wrap = html[html.index('<div class="pv-wrap" id="preview">'):html.index('<div class="strength">')]
        self.assertIn('<img id="ab-orig" alt="" aria-hidden="true">', wrap)
        self.assertRegex(wrap, r'<div id="ab-divider"><div id="ab-handle" tabindex="0" role="slider"[^>]*aria-valuemin="0" aria-valuemax="100" aria-valuenow="50">')
        self.assertIn('<span class="ab-tag" id="ab-tag-a">原圖</span><span class="ab-tag" id="ab-tag-b">編輯後</span>', wrap)
        self.assertRegex(css, r"#ab-orig \{[^}]*clip-path: inset\(0 calc\(100% - var\(--split, 50%\)\) 0 0\);")
        mod = js[js.index("const ab = {on: false, split: L.AB_DEFAULT_SPLIT};"):js.index("// ------------------------------------------------------------------ preset tree")]
        for banned in ("api(", "requestPreview", "dispatch(", "L.reduce", "/api/preview"):   # dragging never renders
            self.assertNotIn(banned, mod, banned)
        self.assertIn("abSetSplit((clientX - r.left) / r.width);", mod)
        self.assertIn("div.addEventListener('dblclick', () => abSetSplit(L.AB_DEFAULT_SPLIT));", mod)
        self.assertIn("const v = L.abStep(ab.split, e.key, e.shiftKey);", mod)
        self.assertIn("sessionStorage.setItem(L.AB_STORAGE_KEY, String(ab.split));", mod)
        self.assertIn("if (k === L.AB_KEY && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && !e.repeat) { abToggle(); return; }", js)
        self.assertNotIn("ab.", read("logic.js"))                              # not editor state (R5 reducer)
        self.assertIn("$('#preview-img').addEventListener('load', abRefresh);", js)

    def test_grid_badge_structure(self):  # S8
        html, js = read("index.html"), read("app.js")
        thumb = js[js.index("async function loadThumb"):js.index("function selectCell")]
        self.assertIn("JSON.parse(decodeURIComponent(r.headers.get('X-Edit')))", thumb)
        self.assertIn("cell.classList.toggle('stale', edited && L.stale(info));", thumb)
        self.assertIn("cell.querySelector('.mark').title = edited ? L.badgeTitle(info) : '';", thumb)
        self.assertIn('<span class="mark" aria-hidden="true"></span>', js)
        css = read("app.css")
        self.assertRegex(css, r"\.cell\.edited \.mark \{")
        self.assertRegex(css, r"\.cell\.edited\.stale \.mark \{")

    def test_grid_filter_structure(self):  # S9
        html, js = read("index.html"), read("app.js")
        self.assertRegex(html, r'<span id="grid-filter" class="seg" role="group" aria-label="篩選"><button data-filter="all" aria-pressed="true"[^>]*>全部</button><button data-filter="edited" aria-pressed="false"[^>]*>已編輯</button><button data-filter="plain" aria-pressed="false"[^>]*>未編輯</button></span>')
        self.assertIn('<span id="grid-pending" class="mute" hidden></span>', html)
        sel = js[js.index("function selectCell"):js.index("function renderGridSelection")]
        self.assertIn("st.grid.sel = L.onlyShown(r.sel, st.grid.shown);", sel)         # selection only among shown
        grid = js[js.index("function renderGrid"):js.index("async function loadThumb")]
        self.assertIn("st.grid.shown = shownSet;", grid)
        self.assertIn("st.grid.sel = L.onlyShown(st.grid.sel, shownSet);", grid)
        self.assertIn("const {shown, pending} = L.gridFilter(st.grid.items, st.grid.filter);", grid)
        self.assertIn("$('#grid-pending').textContent = pending ? L.gridPending(pending) : '';", grid)
        flt = js[js.index("async function setGridFilter"):js.index("function releaseGrid")]
        self.assertIn("if (st.grid.folder) await loadGrid(st.grid.folder); else renderGrid();", flt)   # re-read the listing
        self.assertIn("$('#grid-count').textContent = L.gridCount(st.grid.sel.size, cells.length);", js)

    def test_reset_original_structure(self):  # S10
        html, js = read("index.html"), read("app.js")
        self.assertRegex(html, r'<button id="reset-original-btn" title="[^"]+" disabled>.*還原成原圖.*</button>')
        self.assertRegex(html, r'<button id="restore-previous-btn" title="[^"]+" disabled>取回上一份</button>')
        self.assertRegex(html, r'<button id="grid-reset-original-btn" title="[^"]+" disabled>還原成原圖</button>')
        self.assertRegex(html, r'<button id="grid-restore-btn" title="[^"]+" disabled>取回上一份</button>')
        self.assertIn("await dispatch({type: 'resetToOriginal'});", js[js.index("async function resetOriginal"):js.index("async function restorePrevious")])
        rp = js[js.index("async function restorePrevious"):js.index("// ------------------------------------------------------------------ export (X13)")]
        self.assertIn("if (!st.image || st.edit || !st.previous) return;", rp)
        self.assertIn("api('POST', '/api/edit/restore', {path})", rp)
        self.assertIn("if (st.image && st.image.path === path) { restore(res); requestPreview(); toast(L.RESTORE_TOAST); }", rp)
        self.assertIn("$('#restore-previous-btn').disabled = !(st.image && !st.edit && st.previous);", js)
        g = js[js.index("async function gridResetOriginal"):js.index("async function resetOriginal")]
        self.assertIn("if (!confirm(L.resetConfirm(targets.length))) return;", g)
        self.assertIn("await gridEach('DELETE', '/api/edit', targets, L.resetDone, 'plain');", g)
        self.assertIn("await gridEach('POST', '/api/edit/restore', targets, L.restoreDone, 'edited');", g)
        self.assertIn("gridBatchDone(summaryFn, targets, results);", js)       # failures listed per photo

    def test_css_palette_is_neutral(self):  # S16: grey interface, four muted semantic colours on small marks only
        css = re.sub(r"/\*.*?\*/", "", read("app.css"), flags=re.S)
        root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
        for token in ("--bg0: #121212", "--bg1: #191919", "--bg2: #202020", "--bg3: #2a2a2a",
                      "--line: rgba(255,255,255,.07)", "--line-2: rgba(255,255,255,.12)",
                      "--text: #e6e6e6", "--text-2: #a9a9a9", "--text-3: #8a8a8a",
                      "--tweak: #d9a85b", "--clamp: #d27a7a", "--err: #e06b6b", "--ok: #8fbf93", "--canvas: #151515"):
            self.assertIn(token, root, token)
        self.assertIn('body[data-canvas="black"] { --canvas: #000000; }', css)
        self.assertIn('body[data-canvas="mid"] { --canvas: #4a4a4a; }', css)
        semantic = {"#d9a85b", "#d27a7a", "#e06b6b", "#8fbf93"}
        for m in re.finditer(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", css):
            h = m.group(1).lower()
            full = "".join(c * 2 for c in h) if len(h) == 3 else h
            if "#" + full in semantic:
                continue
            self.assertTrue(full[0:2] == full[2:4] == full[4:6], f"coloured hex {m.group(0)} in app.css")
        for m in re.finditer(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", css):
            r, g, b = (int(m.group(i)) for i in (1, 2, 3))
            self.assertEqual((r == g == b) or (r, g, b) == (217, 168, 91), True, m.group(0))
        for blue in ("#4a9eff", "#2f6fbf", "#29466b", "#3b82d6", "#33404f", "#8fb6df"):
            self.assertNotIn(blue, css, blue)
        self.assertIn(".tnode.preset.active { color: #ffffff; background: rgba(255,255,255,.07); border-left-color: #e6e6e6; }", css)
        self.assertIn('button.on, button[aria-pressed="true"], #grid-btn[aria-pressed="true"] { background: #e6e6e6; color: #141414; border-color: #e6e6e6; }', css)
        self.assertIn("#preview-img[hidden] { display: none; }", css)
        self.assertNotRegex(css, r"#preview-img[^{]*\{[^}]*transition")   # the preview image never animates
        self.assertIn("@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; } }", css)
        self.assertIn('--font: "Segoe UI Variable Text", "Segoe UI", "Noto Sans TC", "Microsoft JhengHei UI", system-ui, sans-serif;', css)
        self.assertIn('--num: "Bahnschrift", "Segoe UI Variable Small", "Segoe UI", system-ui, sans-serif;', css)
        self.assertNotIn("@import", css); self.assertNotIn("url(", css)     # no downloaded fonts or assets

    def test_slider_vars_structure(self):  # S17: drawn sliders, dial, hue dots, canvas, icons
        html, js, css = read("index.html"), read("app.js"), read("app.css")
        row = js[js.index("function updateRow"):js.index("function sliderRow")]
        self.assertIn("const vars = L.sliderVars(s, v);", row)
        self.assertIn("inp.style.setProperty('--base', vars.base); inp.style.setProperty('--lo', vars.lo); inp.style.setProperty('--hi', vars.hi);", row)
        self.assertIn("row.classList.toggle('at-min', v.clamped === 'min');", row)
        sr = js[js.index("function sliderRow"):js.index("function curveBox")]
        self.assertIn("row.className = 'sl' + (L.bipolar(s) ? ' bipolar' : '');", sr)
        self.assertIn("const dot = L.hueDot(s.key);", sr)
        st = js[js.index("function renderStrength"):js.index("function setCanvas")]
        self.assertIn("const vars = L.strengthVars(on ? ed.strength : 100);", st)
        self.assertIn("acc.querySelector('.tc').textContent = n ? `微調 ${n} 項` : '';", js)
        self.assertIn("setStatus('已更新', 'mute', `預覽已更新：後端 ${(+ms).toFixed(0)} ms，往返 ${rt.toFixed(0)} ms`);", js)
        self.assertIn("setCanvas(loadPref('canvas', 'dark'));", js)
        self.assertRegex(css, r"input\[type=range\] \{ -webkit-appearance: none; appearance: none;")
        self.assertIn("--lo: 50%; --hi: 50%; --base: 50%;", css)
        self.assertIn(".sl.bipolar input[type=range] {", css)
        self.assertIn(".sl.clamped input[type=range]::-webkit-slider-thumb { border-radius: 1px;", css)
        self.assertRegex(html, r'<div class="canvas-pick" role="group" aria-label="預覽底色">')
        for c in ("dark", "black", "mid"):
            self.assertRegex(html, r'<button class="c-%s" data-canvas="%s" title="[^"]+" aria-pressed="(true|false)"></button>' % (c, c))
        self.assertIn('<span class="ticks" aria-hidden="true"></span>', html)
        self.assertEqual(html.count('class="scale-num"'), 3)
        for ident in ("toggle-lib", "toggle-sl", "undo", "redo", "prev", "next"):   # inline SVG, no Unicode glyphs
            tag = re.search(r'<button id="%s"[^>]*>(.*?)</button>' % ident, html, re.S).group(1)
            self.assertIn("<svg", tag, ident)
        for glyph in ("☰", "⚙", "↶", "↷", "⟲", "▦", "◀", "▶"):
            self.assertNotIn(glyph, html, glyph)
        self.assertEqual(html.count('<span class="seg">'), 3)                 # browse, history, views

    def test_toasts_go_through_explain(self):  # S14: every toast shows the explained sentence
        js = read("app.js")
        self.assertIn("t.textContent = L.explain(msg); t.title = original || msg;", js[js.index("function toast"):js.index("function setStatus")])
        # seal patch S14a: the status line explains its error too; no error text reaches the screen another way
        self.assertIn("setStatus(L.explain('預覽失敗：' + e.message), 'err', e.message);", js)
        for m in re.finditer(r"setStatus\(([^;]*)\);", js):
            if "e.message" in m.group(1):
                self.assertTrue(m.group(1).startswith("L.explain("), m.group(0))
        for m in re.finditer(r"\.(?:textContent|innerHTML)\s*=\s*([^;]*)", js):
            if "e.message" in m.group(1) or "reason" in m.group(1):
                self.assertIn("L.explain(", m.group(1), m.group(0))

    def test_restore_uses_snapshot_values(self):  # CONTRACT-s1-experience S3
        js = read("app.js")
        lp = js[js.index("async function loadPreset"):js.index("function selectPreset")]
        self.assertIn("st.detail = st.snapshots[id] ? L.detailFromSnapshot(st.snapshots[id], detail) : detail;", lp)
        self.assertIn("catch (e) { if (!st.snapshots[id]) toast(", lp)     # missing preset with a snapshot: no error
        self.assertIn(": (st.byId[id] ? st.byId[id].name : (st.detail && st.detail.name) || id);", lp)
        self.assertNotRegex(lp, r"st\.byId\[id\]\.name(?!\s*:)")
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
        self.assertIn("gridBatchDone(L.pasteDone, targets, res.results);", grid_js)
        export_sel = grid_js[grid_js.index("async function exportSelected"):]
        self.assertIn("const items = paths.map((p) => ({path: p}));", export_sel)   # S2 E29 / E15 (replaces L.exportItems)
        self.assertNotIn("/api/edit", export_sel)                       # no per-photo read of the edit any more
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

    def test_export_dialog_structure(self):  # CONTRACT-s2-export-detect E29 (D3), XP33
        html, js, css = read("index.html"), read("app.js"), read("app.css")
        self.assertRegex(html, r'<form id="export-dialog" class="xd" role="dialog" aria-modal="true" aria-labelledby="xd-title"')
        self.assertIn('<span id="xd-title">匯出</span>', html)
        dialog = html[html.index('<form id="export-dialog"'):html.index("</form>", html.index('<form id="export-dialog"'))]
        order = ["xd-preset", "xd-preset-save", "xd-preset-delete", "xd-format", "xd-bit-depth", "xd-quality", "xd-max-kb-on",
                 "xd-max-kb", "xd-resize-mode", "xd-resize-value", "xd-metadata", "xd-remove-gps", "xd-sharpen-target",
                 "xd-sharpen-amount", "xd-summary", "xd-cancel", "xd-go"]
        at = [dialog.index(f'id="{i}"') for i in order]
        self.assertEqual(at, sorted(at))                              # the contract's order, top to bottom
        self.assertRegex(dialog, r'<select id="xd-preset"[^>]*><option value="">（自訂）</option></select>')
        self.assertRegex(dialog, r'<select id="xd-resize-mode"[^>]*><option value="">不縮放</option><option value="long_edge">長邊</option>'
                                 r'<option value="short_edge">短邊</option><option value="width">寬</option><option value="height">高</option>'
                                 r'<option value="megapixels">百萬像素</option><option value="percent">百分比</option></select>')
        self.assertRegex(dialog, r'<select id="xd-metadata"[^>]*><option value="all">全部中繼資料</option>'
                                 r'<option value="copyright">只留版權</option><option value="none">不含中繼資料</option></select>')
        self.assertRegex(dialog, r'<select id="xd-sharpen-target"[^>]*><option value="">不銳利化</option><option value="screen">螢幕</option>'
                                 r'<option value="matte">霧面紙</option><option value="glossy">光面紙</option></select>')
        self.assertRegex(dialog, r'<button id="xd-go" type="submit"[^>]*>匯出</button>')
        self.assertRegex(dialog, r'<button id="xd-cancel" type="button"[^>]*>取消</button>')
        self.assertRegex(html, r'<div id="export-backdrop" class="xd-backdrop" hidden>\s*<form id="export-dialog"')
        # both export buttons open the one dialog; Enter exports, Esc closes; nothing else exports
        self.assertIn("$('#export-btn').onclick = () => openExportDialog('photo');", js)
        self.assertIn("$('#export-selected-btn').onclick = () => openExportDialog('selected');", js)
        self.assertNotIn("onclick = exportPhoto", js)
        self.assertNotIn("onclick = exportSelected", js)
        init = js[js.index("function initExportDialog"):js.index("function step(delta)")]
        self.assertIn("if (e.key === 'Escape') { e.preventDefault(); closeExportDialog(); return; }", init)
        self.assertIn("e.preventDefault(); runExport(); return; }", init)
        self.assertIn("$('#export-dialog').addEventListener('submit', (e) => { e.preventDefault(); runExport(); });", init)
        self.assertIn("if (!$('#export-backdrop').hidden) return;          // S2 E29: the dialog has the keyboard", js)
        # disabled states only from the pure function; the last settings from localStorage, read and written in try/catch
        dlg = js[js.index("// ------------------------------------------------------------------ S2 export dialog"):js.index("function step(delta)")]
        self.assertEqual(dlg.count("L.exportDialogState("), 1)
        self.assertNotIn("exportDialogState", js.replace(dlg, ""))
        self.assertIn("try { stored = localStorage.getItem(L.EXPORT_SETTINGS_KEY); } catch (e) { stored = null; }", dlg)
        self.assertIn("fillDialog(L.exportSettingsFrom(stored));", dlg)
        self.assertIn("try { localStorage.setItem(L.EXPORT_SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* optional */ }", dlg)
        self.assertIn("const EXPORT_SETTINGS_KEY = 'darkroom.exportSettings';", read("logic.js"))
        self.assertIn("$('#xd-summary').textContent = L.exportSummary(s);", dlg)
        self.assertIn("go.textContent = exp.busy ? L.EXPORT_BUSY : '匯出';", dlg)
        self.assertIn("go.disabled = exp.busy || ds.go.disabled;", dlg)
        # export presets: replace with previous / delete, both with an undo button in the toast
        self.assertIn("toastUndo(L.exportPresetUpdated(res.name), async () => {", dlg)
        self.assertIn("try { await putExportPreset(res.name, res.previous); }", dlg)
        self.assertIn("toastUndo(L.exportPresetDeleted(res.name), async () => {", dlg)
        self.assertIn("try { await putExportPreset(res.name, res.settings); }", dlg)
        self.assertIn("const name = prompt(L.EXPORT_PRESET_NAME_PROMPT,", dlg)
        # the dialog never changes the edit and never names a folder (X13, XP16)
        for banned in ("dispatch(", "L.reduce", "History", "dest_dir", "scheduleSave"):
            self.assertNotIn(banned, dlg, banned)
        # seal F1 (E15a): the open photo always carries its shown parameters (never only its path), after the save
        # is flushed when the photo library is on
        cei = js[js.index("async function currentExportItems"):js.index("async function exportPhoto")]
        self.assertRegex(cei, r"if \(capReasonOf\('photo_library'\) === null\) \{\n\s*await flushSave\(\);\n"
                              r"\s*await flushRetries\(\);\n\s*\}\n\s*return \[currentRequest\(\)\];\n\}")
        self.assertNotIn("{path: st.image.path}", cei)
        self.assertEqual(cei.count("return "), 1)
        req = js[js.index("function currentRequest()"):js.index("function requestPreview()")]
        self.assertIn("return {image_id: st.image.image_id, preset_id: ed.presetId, strength: strengthNow(), overrides};",
                      req)
        # seal F3: the dialog's checkboxes are read as .checked on the real path, into the keys settingsFromForm uses
        fv = js[js.index("function formValues()"):js.index("const dialogSettings")]
        self.assertIn("max_kb_on: $('#xd-max-kb-on').checked", fv)
        self.assertIn("remove_gps: $('#xd-remove-gps').checked", fv)
        self.assertIn("metadata: $('#xd-metadata').value", fv)
        self.assertIn("const dialogSettings = () => L.settingsFromForm(formValues());", js)
        body = js[js.index("async function exportPhoto"):js.index("function renderPosition")]
        self.assertIn("api('POST', '/api/export', L.exportRequest(items, settings || dialogSettings()))", body)
        # 820 x 600: the dialog fits and scrolls inside
        self.assertRegex(css, r"\.xd \{[^}]*max-width: min\(560px, calc\(100vw - 32px\)\);[^}]*max-height: calc\(100vh - 32px\);")
        self.assertRegex(css, r"\.xd-body \{[^}]*overflow: auto;")

    def test_cap_status_structure(self):  # CONTRACT-s2-export-detect E22, E23, E30
        html, js, logic = read("index.html"), read("app.js"), read("logic.js")
        topbar = html[html.index('<header id="topbar">'):html.index("</header>")]
        self.assertRegex(topbar, r'<button id="cap-btn" class="quiet"[^>]*aria-haspopup="dialog"[^>]*>功能正常</button>')
        self.assertRegex(html, r'<div id="cap-detail" class="cap-detail" role="dialog" aria-labelledby="cap-title" hidden>')
        self.assertRegex(html, r'<button id="cap-refresh"[^>]*>重新偵測</button>')
        for const in ("const CAP_OK = '功能正常';", "const capStatus = (n) => `功能狀態：${n} 項關閉`;", "const CAP_REFRESH = '重新偵測';",
                      "const CAP_ORDER = ['gpu', 'heic', 'webp', 'photo_library', 'preset_library_writes', 'semantic_index', 'onepassword'];"):
            self.assertIn(const, logic)
        caps = js[js.index("async function loadCaps"):js.index("function toggleCapDetail")]
        self.assertIn("api('GET', '/api/capabilities' + (refresh ? '?refresh=1' : ''))", caps)   # through api(): X-Darkroom
        self.assertIn("b.textContent = L.capButtonText(st.caps);", caps)
        self.assertIn("li.textContent = L.capLine(k, f);", caps)
        self.assertIn("$('#cap-refresh').onclick = () => loadCaps(true);", js)
        self.assertIn("loadCaps(false);                      // S2 E22: after the page is ready; never waited for", js)
        # off = disabled with the reason as tooltip, never hidden (H11)
        gate = js[js.index("function capGate"):js.index("let capsShown")]
        self.assertIn("el.disabled = true; el.title = reason;", gate)
        self.assertNotIn("hidden", gate)
        self.assertNotIn("display", gate)
        # photo library off: nothing is saved or re-read, the grid's edit buttons are disabled, one status line
        sched = js[js.index("function scheduleSave"):js.index("async function sendSave")]
        self.assertIn("if (capReasonOf('photo_library') !== null) return;", sched)
        copy = js[js.index("function refreshCopy"):js.index("// S10: reset to original")]
        self.assertIn("for (const id of ['#copy-edit-btn', '#paste-edit-btn', '#grid-reset-original-btn', '#grid-restore-btn', '#export-selected-btn']) capGate($(id), off);", copy)
        self.assertIn("if (capReasonOf('photo_library') !== null) { applyEditInfo({edit: null, preset_status: null}); return; }", js)
        self.assertIn("if (!capsShown) {", caps)
        # preset library writes off: organising, importing and saving as a preset are disabled with the reason
        self.assertIn("capGate($('#save-preset-btn'), capReasonOf('preset_library_writes'));", js)
        self.assertIn("for (const id of ['#import-btn', '#new-group-btn']) {", js)
        self.assertIn("capGate(el.querySelector('.fav'), capReasonOf('preset_library_writes'));", js)
        self.assertIn("if (off != null) { b.disabled = true; b.title = off; }", js)

    def test_preset_download_structure(self):  # CONTRACT-s2-export-detect E16, E30 (D7: the page downloads, no zip)
        js, logic = read("app.js"), read("logic.js")
        self.assertIn("const DOWNLOAD_XMP = '下載 .xmp';", logic)
        self.assertIn("const DOWNLOAD_GROUP_XMP = '下載整個群組的 .xmp';", logic)
        self.assertIn("const PRESET_IDS_MAX = 500;", logic)
        self.assertIn("[L.DOWNLOAD_XMP, () => downloadPresets([p.id])],", js)
        self.assertIn("[L.DOWNLOAD_GROUP_XMP, () => downloadPresets(L.groupPresetIds(st.presets, path))],", js)
        dl = js[js.index("function saveBlob"):js.index("function readBase64")]
        self.assertIn("for (const batch of L.idBatches(ids)) {", dl)
        self.assertIn("if (ids.length > L.PRESET_IDS_MAX) { toast(L.downloadTooMany(ids.length), true); return; }",
                      dl)                                                    # seal F4: E30 "≤ 500"
        self.assertLess(dl.index("L.downloadTooMany"), dl.index("api('POST', '/api/preset-library/files'"))
        self.assertIn("api('POST', '/api/preset-library/files', {preset_ids: batch})", dl)
        self.assertIn("new Blob([bytes], {type: 'application/octet-stream'})", dl)
        self.assertIn("a.href = url; a.download = fileName;", dl)
        self.assertIn("const box = $('#import-result');", dl)               # failures listed one per preset
        self.assertIn("l.textContent = L.explain(rep.lines[i]);", dl)
        for banned in ("/api/preset-library/export", "dest_dir", "zip"):   # the server never writes, nothing is packed
            self.assertNotIn(banned, js, banned)

    def test_section_headers_are_buttons(self):  # R6
        js = read("app.js")
        self.assertIn("aria-expanded", js)
        self.assertRegex(js, r"<button class=\"ah\"")
        self.assertIn("treeKey", js)
        self.assertIn("tabIndex", js)


if __name__ == "__main__":
    unittest.main()
