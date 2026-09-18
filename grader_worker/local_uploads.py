from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tempfile
import zipfile
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .repository import RepositoryFailure, SnapshotLimits, validate_snapshot

MAX_REQUEST_BYTES = 12 * 1024 * 1024


def upload_root() -> Path:
    return Path(os.getenv("LOCAL_UPLOAD_ROOT", ".worker-state/local-uploads")).resolve()


def _safe_relative(raw: str) -> Path:
    normalized = raw.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RepositoryFailure("UPLOAD_PATH_INVALID", "Архив содержит недопустимый путь")
    return Path(*path.parts)


def _write_files(parts: list[tuple[str, bytes]], destination: Path) -> None:
    if len(parts) == 1 and parts[0][0].lower().endswith(".zip"):
        archive_path = destination.parent / "upload.zip"
        archive_path.write_bytes(parts[0][1])
        try:
            with zipfile.ZipFile(archive_path) as archive:
                files = [info for info in archive.infolist() if not info.is_dir()]
                if len(files) > SnapshotLimits().file_count or sum(info.file_size for info in files) > SnapshotLimits().total_bytes:
                    raise RepositoryFailure("ARCHIVE_TOO_LARGE", "Распакованный ZIP превышает лимиты snapshot")
                for info in files:
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RepositoryFailure("SYMLINK_FORBIDDEN", "Символические ссылки в архиве запрещены")
                    relative = _safe_relative(info.filename)
                    if info.file_size > SnapshotLimits().single_file_bytes:
                        raise RepositoryFailure("FILE_TOO_LARGE", f"Файл {relative} превышает лимит")
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        except zipfile.BadZipFile as error:
            raise RepositoryFailure("ARCHIVE_INVALID", "ZIP-архив повреждён или имеет неверный формат") from error
        finally:
            archive_path.unlink(missing_ok=True)
        return
    for filename, content in parts:
        relative = _safe_relative(filename)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def store_upload(parts: list[tuple[str, bytes]], root: Path | None = None) -> dict[str, object]:
    if not parts:
        raise RepositoryFailure("UPLOAD_EMPTY", "Не получено ни одного файла")
    root = (root or upload_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="incoming-", dir=root) as temporary:
        snapshot = Path(temporary) / "snapshot"
        snapshot.mkdir()
        _write_files(parts, snapshot)
        stats = validate_snapshot(snapshot)
        digest = hashlib.sha256()
        for path in sorted(item for item in snapshot.rglob("*") if item.is_file()):
            relative = path.relative_to(snapshot).as_posix().encode()
            digest.update(len(relative).to_bytes(4, "big")); digest.update(relative); digest.update(path.read_bytes())
        upload_id = secrets.token_urlsafe(18)
        os.replace(snapshot, root / upload_id)
        (root / f"{upload_id}.json").write_text(json.dumps({"sha256": digest.hexdigest(), **stats}), encoding="utf-8")
    return {"upload_id": upload_id, "sha256": digest.hexdigest(), **stats}


def copy_local_upload(upload_id: str, expected_sha: str, destination: Path, root: Path | None = None) -> None:
    if not upload_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in upload_id):
        raise RepositoryFailure("LOCAL_UPLOAD_INVALID", "Некорректный ID локальной загрузки")
    root = (root or upload_root()).resolve()
    source, manifest = root / upload_id, root / f"{upload_id}.json"
    if not source.is_dir() or not manifest.is_file():
        raise RepositoryFailure("LOCAL_UPLOAD_NOT_FOUND", "Локальная загрузка не найдена; загрузите решение повторно")
    if json.loads(manifest.read_text(encoding="utf-8")).get("sha256") != expected_sha:
        raise RepositoryFailure("LOCAL_UPLOAD_CHANGED", "SHA локальной загрузки не совпадает")
    shutil.copytree(source, destination)


def serve(host: str = "127.0.0.1", port: int = 8790) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("Local upload server may only bind to loopback")
    allowed = {item.rstrip("/") for item in os.getenv("LOCAL_UPLOAD_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8787,http://127.0.0.1:8787").split(",") if item}

    class Handler(BaseHTTPRequestHandler):
        def origin(self) -> str | None:
            origin = self.headers.get("Origin", "")
            return origin if origin in allowed else None

        def do_OPTIONS(self):
            origin = self.origin()
            if not origin: self.send_error(403); return
            self.send_response(204); self.send_header("Access-Control-Allow-Origin", origin); self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.end_headers()

        def do_POST(self):
            origin = self.origin()
            if not origin: self.send_error(403); return
            if urlparse(self.path).path != "/uploads": self.send_error(404); return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES: self.send_error(413); return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data;"): self.send_error(415); return
            raw = self.rfile.read(length)
            message = BytesParser(policy=default).parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
            parts = [(part.get_filename() or "", part.get_payload(decode=True) or b"") for part in message.iter_parts() if part.get_filename()]
            try:
                payload, status = store_upload(parts), 201
            except RepositoryFailure as error:
                payload, status = {"error": {"code": error.code, "message": str(error)}}, 400
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status); self.send_header("Access-Control-Allow-Origin", origin); self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    root = upload_root(); root.mkdir(parents=True, exist_ok=True)
    print(f"Local upload server: http://{host}:{port}/uploads -> {root}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
