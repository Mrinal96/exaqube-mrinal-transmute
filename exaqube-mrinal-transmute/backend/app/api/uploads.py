"""Document upload, metadata, and canonical IR endpoints."""

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.errors import APIError
from app.models.documents import DocumentMetadata
from app.models.intermediate import DocumentIR
from app.services.ingestion import ingest_document
from app.storage.manager import load_json

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentMetadata, status_code=201)
async def upload_document(file: UploadFile = File(...)) -> DocumentMetadata:
    settings = get_settings()
    max_bytes = min(settings.max_upload_size_mb * 1024 * 1024, 10 * 1024 * 1024)
    content = bytearray()
    while chunk := await file.read(min(1024 * 1024, max_bytes + 1 - len(content))):
        content.extend(chunk)
        if len(content) > max_bytes:
            await file.close()
            raise APIError(413, "file_too_large", "The maximum upload size is 10 MB.")
    await file.close()
    metadata, _ = await run_in_threadpool(
        ingest_document,
        file.filename,
        bytes(content),
        settings.storage_root,
        settings.max_upload_size_mb,
    )
    return metadata


@router.get("/{document_id}", response_model=DocumentMetadata)
def get_document(document_id: str) -> DocumentMetadata:
    try:
        stored = load_json(get_settings().storage_root, document_id, "metadata.json")
    except ValueError as exc:
        raise APIError(400, "invalid_document_id", "The document ID is invalid.") from exc
    if stored is None:
        raise APIError(404, "document_not_found", "No uploaded document matches this ID.")
    return DocumentMetadata.model_validate(stored)


@router.get("/{document_id}/ir", response_model=DocumentIR)
def get_document_ir(document_id: str) -> DocumentIR:
    try:
        stored = load_json(get_settings().storage_root, document_id, "ir.json")
    except ValueError as exc:
        raise APIError(400, "invalid_document_id", "The document ID is invalid.") from exc
    if stored is None:
        raise APIError(404, "document_not_found", "No extracted document matches this ID.")
    return DocumentIR.model_validate(stored)
