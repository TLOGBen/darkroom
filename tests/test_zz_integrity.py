"""A15: runs last (alphabetical) - preset originals unchanged after every other test and `scan`."""
import unittest

import _util

EXPECTED_HASH = "15C015CC0C080FF9"


class TestPresetIntegrity(unittest.TestCase):
    def test_presets_untouched_hash(self):
        rc, out, err = _util.run_cli("scan", _util.preset_dir())  # scan runs in this session before the check
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(_util.preset_files()), 1466)
        self.assertEqual(_util.presets_hash(), EXPECTED_HASH)


if __name__ == "__main__":
    unittest.main()
