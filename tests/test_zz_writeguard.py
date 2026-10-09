"""CONTRACT-write-guard G5, G7: runs last (alphabetical) - no write-guard violation anywhere in the run, and the
protected folders (photo prototypes, the whole preset library, the real %LOCALAPPDATA%/darkroom) are byte-identical
to their snapshot taken when the guard was armed."""
import unittest

import _util  # noqa: F401  arms the guard
import _writeguard


class TestZzWriteGuard(unittest.TestCase):
    def test_zz_writeguard(self):
        table = _writeguard.violations()
        self.assertEqual([_writeguard.format_violation(v) for v in table], [])
        before = _writeguard.arm_snapshot()
        self.assertEqual(list(before), _writeguard.protected_folders())
        diff = _writeguard.snapshot_diff(before, _writeguard.snapshot())
        self.assertEqual(diff, [], "受保護資料夾內容改變：" + "、".join(diff))


if __name__ == "__main__":
    unittest.main()
