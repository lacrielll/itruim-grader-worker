from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class RepositoryFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SnapshotLimits:
    total_bytes: int = 10 * 1024 * 1024
    single_file_bytes: int = 2 * 1024 * 1024
    file_count: int = 500


FORBIDDEN_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx", ".bin", ".zip", ".tar", ".gz", ".7z"}


def validate_snapshot(root: Path, limits: SnapshotLimits = SnapshotLimits()) -> dict[str, int]:
    total = 0
    count = 0
    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise RepositoryFailure("SYMLINK_FORBIDDEN", f"Символическая ссылка запрещена: {path.relative_to(root)}")
        if not path.is_file():
            continue
        count += 1
        size = path.stat().st_size
        total += size
        if count > limits.file_count:
            raise RepositoryFailure("TOO_MANY_FILES", f"В snapshot больше {limits.file_count} файлов")
        if size > limits.single_file_bytes:
            raise RepositoryFailure("FILE_TOO_LARGE", f"Файл {path.relative_to(root)} превышает лимит {limits.single_file_bytes} байт")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RepositoryFailure("FORBIDDEN_FILE_TYPE", f"Запрещённый файл: {path.relative_to(root)}")
        if total > limits.total_bytes:
            raise RepositoryFailure("REPOSITORY_TOO_LARGE", f"Snapshot превышает лимит {limits.total_bytes} байт")
    return {"files": count, "bytes": total}


def checkout_exact(repo_url: str, commit_sha: str, destination: Path) -> None:
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise RepositoryFailure("REPOSITORY_UNAVAILABLE", "Разрешён только публичный HTTPS repository")
    if len(commit_sha) != 40 or any(character not in "0123456789abcdefABCDEF" for character in commit_sha):
        raise RepositoryFailure("COMMIT_NOT_FOUND", "Укажите полный 40-символьный SHA commit")
    git_environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "5",
        "GIT_CONFIG_KEY_0": "protocol.allow",
        "GIT_CONFIG_VALUE_0": "never",
        "GIT_CONFIG_KEY_1": "protocol.https.allow",
        "GIT_CONFIG_VALUE_1": "always",
        "GIT_CONFIG_KEY_2": "submodule.recurse",
        "GIT_CONFIG_VALUE_2": "false",
        "GIT_CONFIG_KEY_3": "core.hooksPath",
        "GIT_CONFIG_VALUE_3": os.devnull,
        "GIT_CONFIG_KEY_4": "fetch.fsckObjects",
        "GIT_CONFIG_VALUE_4": "true",
    }
    process = subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", "--no-tags", "--", repo_url, str(destination)],
        capture_output=True, text=True, timeout=90,
        env=git_environment,
    )
    if process.returncode:
        raise RepositoryFailure("REPOSITORY_UNAVAILABLE", "Не удалось загрузить публичный repository")
    verify = subprocess.run(["git", "-C", str(destination), "cat-file", "-e", f"{commit_sha}^{{commit}}"], capture_output=True, timeout=30)
    if verify.returncode:
        raise RepositoryFailure("COMMIT_NOT_FOUND", "Указанный commit не найден в repository")
    checkout = subprocess.run(["git", "-C", str(destination), "checkout", "--detach", commit_sha], capture_output=True, timeout=60)
    if checkout.returncode:
        raise RepositoryFailure("COMMIT_NOT_FOUND", "Не удалось извлечь указанный commit")
    git_dir = destination / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)


def temporary_snapshot() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="itruim-submission-")
    os.chmod(temporary.name, 0o755)
    return temporary, Path(temporary.name) / "snapshot"
