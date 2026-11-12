"""Validation, extraction, and persistence for uploaded source documents."""

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import APIError
from app.models.documents import DocumentMetadata
from app.models.intermediate import DocumentIR
from app.readers import extract_document
from app.services.file_types import validate_actual_type
from app.storage.manager import save_document, storage_available

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def safe_display_filename(filename: str | None) -> str:
    candidate = (filename or "document").replace("\\", "/").split("/")[-1]
    candidate = re.sub(r"[\x00-\x1f\x7f]", "", candidate).strip()
    if not candidate or candidate in {".", ".."}:
        return "document"
    return candidate[:200]


def ingest_document(filename: str | None, content: bytes, storage_root: Path, max_upload_size_mb: int = 10) -> tuple[DocumentMetadata, DocumentIR]:
    if len(content) > min(max_upload_size_mb * 1024 * 1024, MAX_UPLOAD_BYTES):
        raise APIError(413, "file_too_large", "The maximum upload size is 10 MB.")
    safe_name = safe_display_filename(filename)
    detected_format, detected_mime = validate_actual_type(safe_name, content)
    if not storage_available(storage_root):
        raise APIError(503, "storage_unavailable", "Document storage is unavailable.")

    document_id = str(uuid.uuid4())
    try:
        ir = extract_document(content, document_id, safe_name, detected_format)
    except APIError:
        raise
    except Exception as exc:
        logger.exception("document_ingestion_failed", extra={"node_id": document_id})
        raise APIError(422, "document_extraction_failed", "The uploaded document could not be extracted.") from exc

    metadata = DocumentMetadata(
        id=document_id,
        filename=safe_name,
        format=detected_format,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        detected_mime=detected_mime,
        uploaded_at=datetime.now(timezone.utc),
        extraction_status="complete",
        warnings=ir.warnings,
    )
    ir.metadata.update({
        "original_filename": safe_name,
        "file_size_bytes": len(content),
        "sha256": metadata.sha256,
        "detected_mime": detected_mime,
        "uploaded_at": metadata.uploaded_at.isoformat(),
    })
    for record in ir.provenance:
        record.details.update({"sha256": metadata.sha256, "original_filename": safe_name})
    try:
        save_document(
            storage_root,
            document_id,
            f"source.{detected_format.value}",
            content,
            metadata.model_dump(mode="json"),
            ir.model_dump(mode="json"),
        )
    except OSError as exc:
        logger.exception("document_persistence_failed", extra={"node_id": document_id})
        raise APIError(503, "storage_write_failed", "The document was extracted but could not be saved to storage.") from exc
    logger.info("document_ingested", extra={"node_id": document_id})
    return metadata, ir
