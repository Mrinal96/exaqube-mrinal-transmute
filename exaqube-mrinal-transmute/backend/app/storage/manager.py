"""Persistent, per-document storage for uploads, metadata, and canonical IR."""

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)


def storage_available(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "uploads").mkdir(exist_ok=True)
        (root / "outputs").mkdir(exist_ok=True)
        return root.is_dir()
    except OSError:
        return False


def _document_directory(root: Path, document_id: str) -> Path:
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise ValueError("Invalid document identifier.")
    return root / "uploads" / document_id


def save_document(root: Path, document_id: str, filename: str, content: bytes, metadata: dict[str, Any], ir: dict[str, Any]) -> Path:
    directory = _document_directory(root, document_id)
    directory.mkdir(parents=True, exist_ok=False)
    source_path = directory / f"source{Path(filename).suffix.lower()}"
    try:
        with source_path.open("xb") as source_file:
            source_file.write(content)
        _write_json_atomic(directory / "metadata.json", metadata)
        _write_json_atomic(directory / "ir.json", ir)
    except OSError:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)
        raise
    return source_path


def load_json(root: Path, document_id: str, filename: str) -> dict[str, Any] | None:
    path = _document_directory(root, document_id) / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored document data could not be read.") from exc


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    temp_name: str | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp_file:
            temp_file.write(encoded)
            temp_name = temp_file.name
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)

