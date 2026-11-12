"""Extension and content based validation for supported source documents."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

from app.core.errors import APIError
from app.core.formats import MERMAID_DECLARATIONS
from app.models.documents import DocumentFormat


MAX_ARCHIVE_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
OPENXML_PACKAGES: dict[DocumentFormat, tuple[str, str]] = {
    DocumentFormat.PPTX: ("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
    DocumentFormat.XLSX: ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
    DocumentFormat.DOCX: ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
}


def supported_format_from_name(filename: str | None) -> DocumentFormat:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    try:
        return DocumentFormat(suffix.lstrip("."))
    except ValueError as exc:
        raise APIError(415, "unsupported_format", "Supported file formats are PPTX, XLSX, DOCX, MMD, and HTML.") from exc


def validate_actual_type(filename: str, content: bytes) -> tuple[DocumentFormat, str]:
    expected = supported_format_from_name(filename)
    if not content:
        raise APIError(422, "empty_file", "The uploaded file is empty.")

    if zipfile.is_zipfile(BytesIO(content)):
        detected, mime = _detect_openxml(content)
    else:
        decoded = _decode_text(content)
        if _looks_like_mermaid(decoded):
            detected, mime = DocumentFormat.MMD, "text/x-mermaid"
        elif _looks_like_html(decoded):
            detected, mime = DocumentFormat.HTML, "text/html"
        else:
            raise APIError(422, "invalid_file_content", "The file content is not a valid HTML document or Mermaid diagram.")

    if detected != expected:
        raise APIError(
            415,
            "file_type_mismatch",
            f"The file extension indicates {expected.value.upper()}, but its content is {detected.value.upper()}. Rename it to .{detected.value} or upload a matching file.",
        )
    return detected, mime


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise APIError(422, "invalid_text_encoding", "HTML and Mermaid files must use UTF-8 text encoding.") from exc


def _looks_like_html(text: str) -> bool:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    if soup.find("html") or re.search(r"(?i)<!doctype\s+html\b", text):
        return True
    return bool(soup.find([
        "head", "body", "title", "meta", "link", "main", "article", "section", "header", "footer", "nav", "aside",
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "ul", "ol", "div", "span", "a", "img", "script", "style",
    ]))


def _looks_like_mermaid(text: str) -> bool:
    candidate = re.sub(r"^\s*```(?:mermaid)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE)
    candidate = re.sub(r"^\s*%%\{.*?\}%%\s*", "", candidate, count=1, flags=re.DOTALL)
    candidate = re.sub(r"(?m)^\s*%%.*$", "", candidate)
    declaration_pattern = "|".join(re.escape(declaration) for declaration in MERMAID_DECLARATIONS)
    return bool(re.search(rf"(?im)^\s*(?:{declaration_pattern})\b", candidate))


def _detect_openxml(content: bytes) -> tuple[DocumentFormat, str]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_UNPACKED_BYTES:
                raise APIError(413, "archive_too_large", "The Office document expands beyond the safe processing limit.")
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise APIError(422, "corrupt_archive", "The Office document archive contains a damaged file.")
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                raise APIError(422, "invalid_office_package", "The Office document is missing its package content types.")
            content_types = archive.read("[Content_Types].xml")
            for document_format, (required_part, required_content_type) in OPENXML_PACKAGES.items():
                if required_part in names and required_content_type.encode("ascii") in content_types:
                    if document_format == DocumentFormat.PPTX and not any(re.fullmatch(r"ppt/slides/slide\d+\.xml", name) for name in names):
                        continue
                    return document_format, required_content_type
    except APIError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise APIError(422, "invalid_office_package", "The uploaded Office document is malformed or corrupted.") from exc
    raise APIError(422, "invalid_office_package", "The uploaded ZIP file is not a valid PPTX, XLSX, or DOCX package.")
