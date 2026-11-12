"""Synchronous target-content generation, validation, rendering, and persistence."""

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.artifacts import (
    ArtifactMetadata,
    ArtifactSection,
    ArtifactTable,
    ArtifactText,
    DOCXArtifactContent,
    HTMLArtifactContent,
    HTMLArtifactSection,
)
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR, IRBlock, IRSection, SourceLocation
from app.models.interpretation import DocumentInterpretation, SourceReference
from app.models.llm import LLMTokenUsage
from app.models.transformation import TransformationPlan
from app.prompts.artifact import ARTIFACT_PROMPT_VERSION, build_artifact_messages
from app.services.artifact_renderers import render_docx, render_html, validate_rendered_output
from app.services.interpretation import SourceReferenceResolver
from app.services.llm import LLMService
from app.storage.artifacts import ArtifactStore
from app.storage.interpretations import InterpretationStore


logger = logging.getLogger(__name__)
MOCK_ARTIFACT_WARNING = "MOCK_LLM is enabled; this is a deterministic source-content artifact, not an AI transformation."


class UnsupportedArtifactFormatError(ValueError):
    """A valid target format does not yet have a native renderer."""


class InvalidArtifactContentError(ValueError):
    """Generated structured content or rendered output failed validation."""


@dataclass(frozen=True)
class RenderedArtifact:
    metadata: ArtifactMetadata
    usage: LLMTokenUsage | None


class ArtifactTransformationService:
    def __init__(self, llm_service: LLMService, storage_root: Path) -> None:
        self.llm_service = llm_service
        self.store = ArtifactStore(storage_root)

    async def transform(
        self,
        document_ir: DocumentIR,
        interpretation: DocumentInterpretation,
        target_format: DocumentFormat,
        *,
        run_id: UUID,
        user_instructions: str | None = None,
        plan: TransformationPlan | None = None,
    ) -> RenderedArtifact:
        if target_format not in {DocumentFormat.HTML, DocumentFormat.DOCX}:
            raise UnsupportedArtifactFormatError
        if interpretation.document_id != document_ir.document_id:
            raise InvalidArtifactContentError("The interpretation does not belong to the supplied document.")
        source_fingerprint = InterpretationStore.fingerprint(document_ir.model_dump(mode="json"))
        if interpretation.metadata.source_ir_fingerprint != source_fingerprint:
            raise InvalidArtifactContentError("The interpretation was not derived from the supplied source IR.")
        if plan is not None and (
            plan.document_id != document_ir.document_id
            or plan.interpretation_id != interpretation.interpretation_id
            or plan.target_format != target_format
        ):
            raise InvalidArtifactContentError("The transformation plan does not match the source, interpretation, and target format.")

        completion = None
        is_mock = self.llm_service.settings.mock_llm
        warnings: list[str] = []
        if is_mock:
            content = _mock_content(document_ir, target_format)
            warnings.append(MOCK_ARTIFACT_WARNING)
        else:
            messages = build_artifact_messages(document_ir, interpretation, target_format, user_instructions, plan)
            completion = await self.llm_service.complete(messages)
            is_mock = completion.is_mock
            if is_mock:
                content = _mock_content(document_ir, target_format)
                warnings.append(MOCK_ARTIFACT_WARNING)
            else:
                content = _parse_artifact_content(
                    completion.content,
                    target_format,
                    finish_reason=completion.finish_reason,
                    usage=completion.usage,
                )
                try:
                    validate_artifact_references(content, document_ir)
                except Exception as exc:
                    raise InvalidArtifactContentError("Generated content cited a source location that does not resolve to the input document.") from exc

        try:
            if target_format == DocumentFormat.HTML:
                rendered = render_html(content, is_mock=is_mock)
            else:
                rendered = render_docx(content, is_mock=is_mock)
            validate_rendered_output(rendered, target_format.value)
        except Exception as exc:
            raise InvalidArtifactContentError("The rendered output failed file validation.") from exc

        output_id = uuid4()
        source_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(document_ir.filename).stem).strip(".-") or "document"
        filename = f"{source_stem}-transmuted-{str(output_id)[:8]}.{target_format.value}"
        metadata = ArtifactMetadata(
            output_id=output_id,
            document_id=document_ir.document_id,
            interpretation_id=interpretation.interpretation_id,
            target_format=target_format,
            filename=filename,
            provider=completion.provider if completion is not None else "mock",
            model=completion.model if completion is not None else "mock",
            prompt_version=ARTIFACT_PROMPT_VERSION,
            is_mock=is_mock,
            warnings=warnings,
        )
        await asyncio.to_thread(self.store.save, metadata, rendered)
        logger.info(
            "document_artifact_created",
            extra={
                "node_id": document_ir.document_id,
                "run_id": str(run_id),
                "output_id": str(output_id),
                "target_format": target_format.value,
                "is_mock": is_mock,
                "token_usage_present": completion is not None and completion.usage is not None,
            },
        )
        return RenderedArtifact(metadata=metadata, usage=None if is_mock or completion is None else completion.usage)


def _parse_artifact_content(
    content: str,
    target_format: DocumentFormat,
    *,
    finish_reason: str | None = None,
    usage: LLMTokenUsage | None = None,
):
    model = HTMLArtifactContent if target_format == DocumentFormat.HTML else DOCXArtifactContent
    normalized_content, was_fenced = _unwrap_json_fence(content)
    try:
        payload = json.loads(normalized_content, parse_constant=_reject_nonstandard_json_constant)
    except (json.JSONDecodeError, ValueError) as parse_error:
        try:
            model.model_validate_json(normalized_content)
        except ValidationError as exc:
            _log_artifact_validation_failure(
                exc,
                normalized_content,
                was_fenced=was_fenced,
                finish_reason=finish_reason,
                usage=usage,
                json_parsing_succeeded=False,
            )
            raise InvalidArtifactContentError("The provider response did not contain valid JSON for the target document schema.") from exc
        logger.error(
            "artifact_content_validation_failed",
            extra={
                "failure_phase": "artifact_json_parsing",
                "failure_reason": "invalid_json",
                "exception_class": type(parse_error).__name__,
                "error_category": "invalid_artifact_content",
                "json_parsing_failed": True,
                "json_parsing_succeeded": False,
                "pydantic_errors": [],
                "content_empty": not normalized_content.strip(),
                "content_char_count": len(normalized_content),
                "contains_markdown_code_fence": was_fenced,
                "finish_reason": finish_reason,
                "token_usage_present": usage is not None,
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
            },
        )
        raise InvalidArtifactContentError("The provider response did not contain valid JSON for the target document schema.") from parse_error

    normalized_references = _normalize_nested_reference_section_ids(payload)
    normalized_cells = _normalize_table_cells(payload)
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        _log_artifact_validation_failure(
            exc,
            normalized_content,
            was_fenced=was_fenced,
            finish_reason=finish_reason,
            usage=usage,
            json_parsing_succeeded=True,
            normalized_table_cell_count=normalized_cells,
            normalized_section_reference_count=normalized_references,
        )
        raise InvalidArtifactContentError("The provider response did not match the target document schema.") from exc
    if normalized_cells:
        logger.info(
            "artifact_table_cells_normalized",
            extra={"normalized_table_cell_count": normalized_cells},
        )
    if normalized_references:
        logger.info(
            "artifact_section_reference_normalized",
            extra={"normalized_section_reference_count": normalized_references},
        )
    return validated


def _reject_nonstandard_json_constant(value: str):
    raise ValueError(f"Non-standard JSON constant: {value}")


def _normalize_table_cells(payload) -> int:
    """Convert scalar JSON table cells to text without coercing nested data."""
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
        return 0
    normalized = 0
    for section in payload["sections"]:
        if not isinstance(section, dict) or not isinstance(section.get("tables"), list):
            continue
        for table in section["tables"]:
            if not isinstance(table, dict):
                continue
            for key in ("headers", "rows"):
                values = table.get(key)
                if not isinstance(values, list):
                    continue
                groups = values if key == "rows" else [values]
                for group in groups:
                    if not isinstance(group, list):
                        continue
                    for index, value in enumerate(group):
                        if isinstance(value, str):
                            continue
                        if value is None:
                            group[index] = ""
                        elif isinstance(value, bool):
                            group[index] = "true" if value else "false"
                        elif isinstance(value, int):
                            group[index] = str(value)
                        elif isinstance(value, float) and math.isfinite(value):
                            group[index] = json.dumps(value, allow_nan=False)
                        else:
                            # Objects, arrays, and non-finite values are ambiguous;
                            # leave them untouched so Pydantic rejects them.
                            continue
                        normalized += 1
    return normalized


def _normalize_nested_reference_section_ids(payload) -> int:
    """Lift a misplaced reference.section_id out of source_location, losslessly."""
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
        return 0
    normalized = 0
    for section in payload["sections"]:
        if not isinstance(section, dict):
            continue
        for collection_name in ("paragraphs", "bullet_points", "metrics", "tables"):
            collection = section.get(collection_name)
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, dict) or not isinstance(item.get("source_references"), list):
                    continue
                for reference in item["source_references"]:
                    if not isinstance(reference, dict):
                        continue
                    location = reference.get("source_location")
                    if not isinstance(location, dict) or "section_id" not in location:
                        continue
                    nested_section_id = location["section_id"]
                    if "section_id" not in reference:
                        reference["section_id"] = nested_section_id
                        del location["section_id"]
                        normalized += 1
                    elif reference["section_id"] == nested_section_id:
                        # Identical duplicate values are represented once in the
                        # canonical SourceReference shape.
                        del location["section_id"]
                        normalized += 1
                    # Conflicting values deliberately remain unnormalized and
                    # fail SourceLocation's extra-forbid validation.
    return normalized


def _log_artifact_validation_failure(
    exc: ValidationError,
    content: str,
    *,
    was_fenced: bool,
    finish_reason: str | None,
    usage: LLMTokenUsage | None,
    json_parsing_succeeded: bool,
    normalized_table_cell_count: int = 0,
    normalized_section_reference_count: int = 0,
) -> None:
    errors = exc.errors(include_url=False, include_input=False)
    logger.error(
        "artifact_content_validation_failed",
        extra={
            "failure_phase": "artifact_schema_validation" if json_parsing_succeeded else "artifact_json_parsing",
            "failure_reason": "schema_mismatch" if json_parsing_succeeded else "invalid_json",
            "exception_class": type(exc).__name__,
            "error_category": "invalid_artifact_content",
            "json_parsing_failed": not json_parsing_succeeded,
            "json_parsing_succeeded": json_parsing_succeeded,
            "pydantic_errors": [
                {
                    "location": _safe_error_location(error.get("loc", ())),
                    "type": error.get("type", "unknown"),
                }
                for error in errors
            ],
            "content_empty": not content.strip(),
            "content_char_count": len(content),
            "contains_markdown_code_fence": was_fenced,
            "finish_reason": finish_reason,
            "token_usage_present": usage is not None,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "normalized_table_cell_count": normalized_table_cell_count,
            "normalized_section_reference_count": normalized_section_reference_count,
        },
    )


def _unwrap_json_fence(content: str) -> tuple[str, bool]:
    """Accept plain JSON or one complete Markdown JSON fence; reject surrounding prose."""
    match = re.fullmatch(r"\s*```(?:json)?\s*\r?\n(.*?)\r?\n```\s*", content, re.IGNORECASE | re.DOTALL)
    if match is None:
        return content, False
    return match.group(1), True


def _safe_error_location(location) -> list[str | int]:
    """Keep schema paths useful without copying arbitrary provider-supplied keys to logs."""
    safe: list[str | int] = []
    for part in location:
        if isinstance(part, int):
            safe.append(part)
        elif isinstance(part, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            safe.append(part)
        else:
            safe.append("[key]")
    return safe


def validate_artifact_references(content, document_ir: DocumentIR) -> None:
    resolver = SourceReferenceResolver(document_ir)
    for section in content.sections:
        for item in (*section.paragraphs, *section.bullet_points, *section.metrics, *section.tables):
            for reference in item.source_references:
                resolver.validate(reference)


def _mock_content(document_ir: DocumentIR, target_format: DocumentFormat):
    sections = _mock_sections(document_ir.sections)
    if document_ir.blocks:
        loose = _mock_section_from_blocks("Document content", None, document_ir.blocks)
        if loose is not None:
            sections.append(loose)
    if not sections:
        raise InvalidArtifactContentError("The source IR contains no renderable content.")
    title = document_ir.title or document_ir.filename
    if target_format == DocumentFormat.HTML:
        html_sections = [_to_html_section(section) for section in sections]
        return HTMLArtifactContent(target_format="html", page_title=title, sections=html_sections)
    return DOCXArtifactContent(target_format="docx", document_title=title, sections=sections)


def _to_html_section(section: ArtifactSection) -> HTMLArtifactSection:
    """Validate a lossless conversion while retaining HTML's nonempty-section rule."""
    return HTMLArtifactSection.model_validate(section.model_dump(mode="python"))


def _mock_sections(source_sections: list[IRSection]) -> list[ArtifactSection]:
    result: list[ArtifactSection] = []
    for source_section in source_sections:
        artifact_section = _mock_section_from_blocks(source_section.title, source_section, source_section.blocks)
        if artifact_section is not None:
            result.append(artifact_section)
        result.extend(_mock_sections(source_section.children))
    return result


def _mock_section_from_blocks(
    heading: str,
    source_section: IRSection | None,
    blocks: list[IRBlock],
) -> ArtifactSection | None:
    paragraphs: list[ArtifactText] = []
    bullet_points: list[ArtifactText] = []
    tables: list[ArtifactTable] = []
    for block in blocks:
        reference = _mock_reference(block, source_section)
        if reference is None:
            continue
        refs = [reference]
        if block.kind == "table" and block.table is not None and block.table.headers:
            tables.append(ArtifactTable(
                caption=block.table.caption or "",
                headers=[str(value) for value in block.table.headers],
                rows=[[str(value) for value in row] for row in block.table.rows],
                source_references=refs,
            ))
        elif block.kind == "list":
            items = block.attributes.get("items", [])
            if not isinstance(items, list):
                items = [part for part in block.text.splitlines() if part.strip()]
            bullet_points.extend(ArtifactText(text=str(item), source_references=refs) for item in items if str(item).strip())
        elif block.text.strip():
            paragraphs.append(ArtifactText(text=block.text, source_references=refs))
    if not (paragraphs or bullet_points or tables):
        return None
    return ArtifactSection(
        heading=heading or "Document content",
        paragraphs=paragraphs,
        bullet_points=bullet_points,
        tables=tables,
    )


def _mock_reference(block: IRBlock, section: IRSection | None) -> SourceReference | None:
    if _has_coordinates(block.source):
        return SourceReference(
            block_id=block.id,
            section_id=section.id if section is not None else None,
            source_location=block.source,
        )
    if section is not None and section.source is not None and _has_coordinates(section.source):
        return SourceReference(section_id=section.id, source_location=section.source)
    return None


def _has_coordinates(location: SourceLocation) -> bool:
    return any((
        location.slide_number is not None,
        location.sheet_name is not None,
        location.cell_range is not None,
        bool(location.section_path),
        location.paragraph_index is not None,
        location.element_index is not None,
        location.line_start is not None,
        location.line_end is not None,
        location.source_part is not None,
    ))
