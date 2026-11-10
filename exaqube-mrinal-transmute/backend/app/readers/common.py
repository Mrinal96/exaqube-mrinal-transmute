"""Shared constructors for consistent IR blocks, sections, and provenance."""

from typing import Any

from app.models.intermediate import DocumentIR, IRBlock, IRSection, ProvenanceRecord, SourceLocation


def base_ir(document_id: str, filename: str, source_format: str, extractor: str, title: str = "", metadata: dict[str, Any] | None = None) -> DocumentIR:
    return DocumentIR(
        document_id=document_id,
        source_format=source_format,
        filename=filename,
        title=title or filename,
        metadata=metadata or {},
        provenance=[ProvenanceRecord(extractor=extractor, source_format=source_format)],
    )


def make_block(block_id: str, kind: str, text: str = "", source: SourceLocation | None = None, **kwargs: Any) -> IRBlock:
    return IRBlock(id=block_id, kind=kind, text=text, source=source or SourceLocation(), **kwargs)


def make_section(section_id: str, title: str, level: int = 1, order: int = 0, source: SourceLocation | None = None) -> IRSection:
    return IRSection(id=section_id, title=title or "Untitled section", level=level, order=order, source=source)
