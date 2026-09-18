from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from grader_worker.datasets import DatasetError, DatasetMount, DatasetRegistry


class DatasetRegistryTests(unittest.TestCase):
    def test_ingests_and_resolves_content_addressed_immutable_dataset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "rows.csv").write_text("x,y\n1,2\n", encoding="utf-8")
            registry = DatasetRegistry(root / "store")
            descriptor = registry.ingest("course/sample", "v1", source)
            resolved, data = registry.resolve(DatasetMount("train", "course/sample", "v1", descriptor.digest))
            self.assertEqual(resolved, descriptor)
            self.assertEqual((data / "rows.csv").read_text(), "x,y\n1,2\n")
            self.assertEqual((data / "rows.csv").stat().st_mode & 0o222, 0)

            (source / "rows.csv").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "immutable"):
                registry.ingest("course/sample", "v1", source)

    def test_rejects_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            outside = root / "outside"
            outside.write_text("secret", encoding="utf-8")
            (source / "link").symlink_to(outside)
            with self.assertRaisesRegex(DatasetError, "symlink"):
                DatasetRegistry(root / "store").ingest("sample", "1", source)
            (source / "link").unlink()
            original = source / "data"
            original.write_text("value", encoding="utf-8")
            os.link(original, source / "hardlink")
            with self.assertRaisesRegex(DatasetError, "hardlink"):
                DatasetRegistry(root / "store2").ingest("sample", "1", source)

    def test_never_accepts_host_path_as_mount_identity(self):
        with self.assertRaises(DatasetError):
            DatasetMount("train", "/etc", "1")
        with self.assertRaises(DatasetError):
            DatasetMount("../escape", "sample", "1")


if __name__ == "__main__":
    unittest.main()
