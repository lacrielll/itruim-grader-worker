import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from grader_worker.local_uploads import copy_local_upload, store_upload
from grader_worker.repository import RepositoryFailure


class LocalUploadsTests(unittest.TestCase):
    def test_stores_folder_snapshot_and_copies_by_digest(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as output:
            stored = store_upload([("solution.py", b"answer = 42\n"), ("grader_contracts/types.py", b"class Input: pass\n")], Path(directory))
            destination = Path(output) / "snapshot"
            copy_local_upload(str(stored["upload_id"]), str(stored["sha256"]), destination, Path(directory))
            self.assertEqual((destination / "solution.py").read_text(), "answer = 42\n")

    def test_extracts_zip_without_retaining_archive(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("lab/solution.py", "value = 1\n")
        with tempfile.TemporaryDirectory() as directory:
            stored = store_upload([("lab.zip", stream.getvalue())], Path(directory))
            self.assertTrue((Path(directory) / str(stored["upload_id"]) / "lab" / "solution.py").is_file())

    def test_rejects_zip_path_traversal(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../escape.py", "bad = True")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RepositoryFailure):
                store_upload([("bad.zip", stream.getvalue())], Path(directory))


if __name__ == "__main__":
    unittest.main()
