"""Format-specific source readers normalized to the canonical DocumentIR."""

import logging

from app.core.errors import APIError
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR
from app.readers.docx_reader import read_docx
from app.readers.errors import ExtractionError
from app.readers.html_reader import read_html
from app.readers.mmd_reader import read_mmd
from app.readers.pptx_reader import read_pptx
from app.readers.xlsx_reader import read_xlsx

logger = logging.getLogger(__name__)


def extract_document(content: bytes, document_id: str, filename: str, document_format: DocumentFormat) -> DocumentIR:
    readers = {
        DocumentFormat.PPTX: read_pptx,
        DocumentFormat.XLSX: read_xlsx,
        DocumentFormat.DOCX: read_docx,
        DocumentFormat.MMD: read_mmd,
        DocumentFormat.HTML: read_html,
    }
    try:
        return readers[document_format](content, document_id, filename)
    except ExtractionError as exc:
        raise APIError(422, "document_limit_or_syntax_error", str(exc)) from exc
    except APIError:
        raise
    except Exception as exc:
        logger.exception("document_extraction_failed", extra={"node_id": document_id})
        raise APIError(422, "document_extraction_failed", "The file passed type detection but could not be extracted. Verify that it is a valid, unencrypted document.") from exc

