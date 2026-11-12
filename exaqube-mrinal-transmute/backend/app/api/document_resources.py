"""Shared server-side document loading for document-scoped operation routes."""

from pathlib import Path

from app.core.errors import APIError
from app.models.intermediate import DocumentIR
from app.storage.manager import load_json


def require_document(storage_root: Path, document_id: str) -> DocumentIR:
    try:
        metadata = load_json(storage_root, document_id, "metadata.json")
        if metadata is None:
            raise APIError(404, "document_not_found", "No uploaded document matches this ID.")
        raw_ir = load_json(storage_root, document_id, "ir.json")
    except ValueError as exc:
        raise APIError(400, "invalid_document_id", "The document ID is invalid.") from exc
    if raw_ir is None:
        raise APIError(404, "document_not_found", "No extracted document matches this ID.")
    return DocumentIR.model_validate(raw_ir)
