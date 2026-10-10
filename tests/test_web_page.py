"""The web page (web/, React) against the backend and the sealed contracts (plan-v2 §2, integration).

v1 had tests/test_app_frontend.py, which read darkroom_app/static/{index.html,app.js,logic.js} and ran
tests/js/test_logic.cjs with node. The v1 page is gone; its behaviour tests moved to web/'s vitest suite:

- tests/js/test_logic.cjs (46 cases)  -> web/src/domain/__tests__/logic.legacy.test.ts (45, same expected values,
  still driven by the shared tables in tests/cases/*.json) + web/src/hooks/__tests__/autosave.test.ts (C29, the
  case that ran app.js in a fake DOM, now through the real store and autosave queue).
- the structure checks of the v1 HTML / JS (element ids, regexes over app.js) have no meaning for React components;
  what they protected is now covered by the vitest suite (`npm test` in web/, run by CI's web job).

What stays here is what only Python can check: the sentences the page shows that must be word for word the same as
the CLI's / the services' (seal F5 / XP25, K19, PL15 / PLP9, PLP17), the shared case tables the vitest suite reads,
and that the build goes where the server looks for it.
"""
import json
import os
import re
import unittest

import _util

WEB = os.path.join(_util.REPO, "web")


def zh():
    with open(os.path.join(WEB, "src", "i18n", "locales", "zh-TW.json"), encoding="utf-8") as f:
        return json.load(f)


def at(tree, dotted):
    for part in dotted.split("."):
        tree = tree[part]
    return tree


def as_python(text):
    """i18next's {{name}} placeholders -> str.format's {name} (the backend's spelling)."""
    return re.sub(r"\{\{(\w+)\}\}", r"{\1}", text)


class TestSentencesSameAsBackend(unittest.TestCase):
    """The page shows these in zh-TW exactly as the CLI / services say them (the en-US file is a translation)."""

    def test_exported_and_imported_lines_same_in_cli_and_page(self):  # seal F5 / XP25, K19
        from darkroom_app import cli, messages
        t = zh()
        self.assertEqual(as_python(at(t, "export.done")), cli.EXPORTED.replace("{output_path}", "{path}"))
        self.assertEqual(cli.EXPORTED, "已匯出：{output_path}")
        self.assertEqual(as_python(at(t, "export.failed")),
                         messages.EXPORT_FAILED.replace("{file_name}", "{file}"))
        self.assertEqual(as_python(at(t, "presets.importedLine")), cli.IMPORTED)

    def test_library_sentences_same_as_contract(self):  # CONTRACT-preset-library K19 constants
        t = zh()
        self.assertEqual(at(t, "presets.saved"), "已存成 preset：{{name}}")
        self.assertEqual(at(t, "presets.importSummary"), "已匯入 {{ok}} 個，{{fail}} 個沒有匯入")
        self.assertEqual(at(t, "presets.favEmpty"), "還沒有最愛，按 preset 旁的 ☆ 加入")
        self.assertEqual(at(t, "presets.groupCreated"), "已建立群組：{{group}}")

    def test_photo_library_sentences_same_as_contract(self):  # CONTRACT-photo-library PL15 / PLP9 / PLP17
        t = zh()
        expected = {
            "editor.presetChanged": "preset 已變更，這份編輯用的是當時的 preset 快照",
            "editor.presetMissing": "preset 已不在庫裡，這份編輯用的是當時的 preset 快照",
            "grid.copied": "已複製 {{name}} 的編輯",
            "grid.pasteConfirm": "要用 {{name}} 的編輯取代 {{n}} 張照片的編輯嗎？",
            "grid.pasteDone": "已貼上 {{ok}} 張，失敗 {{failed}} 張",
            "grid.exportDone": "已匯出 {{ok}} 張，失敗 {{failed}} 張",
            "grid.count": "已選 {{n}}／{{total}} 張",
            "photo.saveEditFailed": "儲存編輯失敗：{{reason}}",
            "photo.loadEditFailed": "讀取編輯失敗：{{reason}}",
            "grid.loadFolderFailed": "讀取資料夾失敗：{{reason}}",
        }
        for key, sentence in expected.items():
            self.assertEqual(at(t, key), sentence, key)
        with open(os.path.join(WEB, "src", "domain", "library.ts"), encoding="utf-8") as f:
            self.assertIn("export const AUTOSAVE_MS = 500;", f.read())

    def test_locales_have_the_same_keys(self):  # every sentence exists in both languages
        def keys(tree, prefix=""):
            out = set()
            for k, v in tree.items():
                out |= keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {prefix + k}
            return out
        with open(os.path.join(WEB, "src", "i18n", "locales", "en-US.json"), encoding="utf-8") as f:
            en = json.load(f)
        self.assertEqual(keys(zh()), keys(en))


class TestWebProject(unittest.TestCase):
    def test_vitest_reads_the_shared_case_tables(self):  # CONTRACT-app-shell R7: one table, two implementations
        with open(os.path.join(WEB, "src", "domain", "__tests__", "logic.legacy.test.ts"), encoding="utf-8") as f:
            suite = f.read()
        for table in ("r3_slider_cases.json", "s2_resize_cases.json", "s3_geometry_cases.json",
                      "s3_geometry_actions.json"):
            self.assertTrue(os.path.isfile(os.path.join(_util.REPO, "tests", "cases", table)), table)
            self.assertIn(table, suite, table)

    def test_build_lands_where_the_server_looks(self):  # plan-v2 §2: npm run build -> web/dist, logo in web/static
        from darkroom_app.adapters.http import server
        with open(os.path.join(WEB, "vite.config.ts"), encoding="utf-8") as f:
            vite = f.read()
        self.assertIn("outDir: 'dist'", vite)
        self.assertIn("publicDir: 'static'", vite)
        self.assertEqual(server.WEB_DIST, os.path.join(WEB, "dist"))
        self.assertTrue(os.path.isfile(os.path.join(WEB, "static", "logo.svg")))
        self.assertFalse(os.path.exists(os.path.join(_util.REPO, "darkroom_app", "static")))   # the v1 page is gone


if __name__ == "__main__":
    unittest.main()
