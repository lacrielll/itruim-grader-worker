from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grader_worker.repository import RepositoryFailure, SnapshotLimits, validate_snapshot


class SnapshotValidationTests(unittest.TestCase):
    def test_accepts_small_source_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "solution.py").write_text("answer = 42\n", encoding="utf-8")
            self.assertEqual(validate_snapshot(root), {"files": 1, "bytes": 12})

    def test_rejects_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "model.ckpt").write_bytes(b"checkpoint")
            with self.assertRaisesRegex(RepositoryFailure, "model.ckpt") as raised:
                validate_snapshot(root)
            self.assertEqual(raised.exception.code, "FORBIDDEN_FILE_TYPE")

    def test_rejects_total_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "large.py").write_bytes(b"x" * 20)
            with self.assertRaises(RepositoryFailure) as raised:
                validate_snapshot(root, SnapshotLimits(total_bytes=10, single_file_bytes=100, file_count=10))
            self.assertEqual(raised.exception.code, "REPOSITORY_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()

