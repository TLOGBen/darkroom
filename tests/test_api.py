"""A1/A2: public API surface."""
import os
import re
import unittest

import _util


class TestPublicApi(unittest.TestCase):
    def test_all_is_exactly_the_five_names(self):
        import darkroom
        self.assertEqual(sorted(darkroom.__all__),
                         sorted(["load_preset", "Params", "render", "SCHEMA_VERSION", "UnsupportedPresetError"]))
        for name in darkroom.__all__:
            self.assertTrue(hasattr(darkroom, name), name)

    def test_schema_version_constant(self):
        import darkroom
        self.assertEqual(darkroom.SCHEMA_VERSION, "darkroom-params/1")

    def test_no_private_imports_outside_tests(self):
        """Code outside darkroom/ and tests/ must not reach into darkroom._* or private names."""
        bad = re.compile(r"(from\s+darkroom\.?_\w*|import\s+darkroom\._|from\s+darkroom\s+import\s+_)")
        offenders = []
        for root, dirs, files in os.walk(_util.REPO):
            rel = os.path.relpath(root, _util.REPO).replace("\\", "/")
            if rel.split("/")[0] in (".git", "tests", "darkroom", ".claude", ".strategic-advance"):
                dirs[:] = []
                continue
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(root, f), "rb") as fh:
                        if bad.search(fh.read().decode("utf-8", "replace")):
                            offenders.append(os.path.join(rel, f))
        self.assertEqual(offenders, [])

    def test_package_modules_are_private(self):
        """Only the five names are public; implementation modules are underscore-prefixed."""
        pkg = os.path.join(_util.REPO, "darkroom")
        for f in os.listdir(pkg):
            if f.endswith(".py") and f not in ("__init__.py", "__main__.py"):
                self.assertTrue(f.startswith("_"), f)


if __name__ == "__main__":
    unittest.main()
