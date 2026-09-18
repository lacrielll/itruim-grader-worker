from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DATASET_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}(?:/[a-z][a-z0-9-]{0,63})*$")
DATASET_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MOUNT_ALIAS = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetLimits:
    total_bytes: int = 20 * 1024 * 1024 * 1024
    single_file_bytes: int = 4 * 1024 * 1024 * 1024
    file_count: int = 100_000


@dataclass(frozen=True)
class DatasetDescriptor:
    dataset_id: str
    version: str
    digest: str
    files: int
    bytes: int


@dataclass(frozen=True)
class DatasetMount:
    alias: str
    dataset_id: str
    version: str
    digest: str | None = None

    def __post_init__(self) -> None:
        if not MOUNT_ALIAS.fullmatch(self.alias):
            raise DatasetError(f"invalid dataset mount alias: {self.alias!r}")
        if not DATASET_ID.fullmatch(self.dataset_id):
            raise DatasetError(f"invalid dataset id: {self.dataset_id!r}")
        if not DATASET_VERSION.fullmatch(self.version):
            raise DatasetError(f"invalid dataset version: {self.version!r}")
        if self.digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.digest):
            raise DatasetError("dataset digest must be sha256:<64 lowercase hex chars>")


class DatasetRegistry:
    """Content-addressed, immutable local dataset store.

    Only this trusted registry resolves logical IDs to host paths. Neither a
    student submission nor an assignment form can provide a host path.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.objects = self.root / "objects"
        self.index = self.root / "index"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.index.mkdir(parents=True, exist_ok=True)

    def ingest(self, dataset_id: str, version: str, source: Path, limits: DatasetLimits = DatasetLimits()) -> DatasetDescriptor:
        DatasetMount("data", dataset_id, version)
        source = source.resolve(strict=True)
        if not source.is_dir():
            raise DatasetError("dataset source must be a directory")
        entries, total = self._scan(source, limits)
        digest_hash = hashlib.sha256()
        for relative, path, size in entries:
            digest_hash.update(relative.as_posix().encode("utf-8") + b"\0")
            digest_hash.update(str(size).encode("ascii") + b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest_hash.update(chunk)
        digest_hex = digest_hash.hexdigest()
        descriptor = DatasetDescriptor(dataset_id, version, f"sha256:{digest_hex}", len(entries), total)
        object_dir = self.objects / digest_hex
        if not object_dir.exists():
            with tempfile.TemporaryDirectory(prefix="dataset-ingest-", dir=self.root) as temporary:
                temporary_root = Path(temporary)
                data_root = temporary_root / "data"
                data_root.mkdir()
                for relative, path, _ in entries:
                    target = data_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target, follow_symlinks=False)
                    target.chmod(0o444)
                for directory in sorted((item for item in data_root.rglob("*") if item.is_dir()), reverse=True):
                    directory.chmod(0o555)
                data_root.chmod(0o555)
                (temporary_root / "manifest.json").write_text(json.dumps(asdict(descriptor), ensure_ascii=False, sort_keys=True), encoding="utf-8")
                (temporary_root / "manifest.json").chmod(0o444)
                os.replace(temporary_root, object_dir)
        index_path = self._index_path(dataset_id, version)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        if index_path.exists():
            existing = json.loads(index_path.read_text(encoding="utf-8"))
            if existing["digest"] != descriptor.digest:
                raise DatasetError(f"dataset version is immutable: {dataset_id}@{version}")
        else:
            temporary_index = index_path.with_suffix(".tmp")
            temporary_index.write_text(json.dumps(asdict(descriptor), ensure_ascii=False, sort_keys=True), encoding="utf-8")
            os.replace(temporary_index, index_path)
            index_path.chmod(0o444)
        return descriptor

    def resolve(self, mount: DatasetMount) -> tuple[DatasetDescriptor, Path]:
        index_path = self._index_path(mount.dataset_id, mount.version)
        try:
            descriptor = DatasetDescriptor(**json.loads(index_path.read_text(encoding="utf-8")))
        except FileNotFoundError as error:
            raise DatasetError(f"dataset is not installed: {mount.dataset_id}@{mount.version}") from error
        if mount.digest is not None and descriptor.digest != mount.digest:
            raise DatasetError(f"dataset digest mismatch: {mount.dataset_id}@{mount.version}")
        data_path = (self.objects / descriptor.digest.removeprefix("sha256:") / "data").resolve(strict=True)
        try:
            data_path.relative_to(self.objects.resolve(strict=True))
        except ValueError as error:
            raise DatasetError("dataset object escaped registry root") from error
        if "," in str(data_path):
            raise DatasetError("dataset storage path cannot contain a comma")
        return descriptor, data_path

    def _index_path(self, dataset_id: str, version: str) -> Path:
        return self.index.joinpath(*dataset_id.split("/"), f"{version}.json")

    @staticmethod
    def _scan(source: Path, limits: DatasetLimits) -> tuple[list[tuple[Path, Path, int]], int]:
        entries: list[tuple[Path, Path, int]] = []
        total = 0
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise DatasetError(f"dataset symlink is forbidden: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise DatasetError(f"dataset special file is forbidden: {relative}")
            if metadata.st_nlink != 1:
                raise DatasetError(f"dataset hardlink is forbidden: {relative}")
            if metadata.st_size > limits.single_file_bytes:
                raise DatasetError(f"dataset file is too large: {relative}")
            entries.append((relative, path, metadata.st_size))
            total += metadata.st_size
            if len(entries) > limits.file_count:
                raise DatasetError("dataset contains too many files")
            if total > limits.total_bytes:
                raise DatasetError("dataset is too large")
        return entries, total
