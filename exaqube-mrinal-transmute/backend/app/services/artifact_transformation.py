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
    DOCXArtifactSection,
    HTMLArtifactContent,
    HTMLArtifactSection,
    PPTXArtifactContent,
    PPTXChartElement,
    PPTXArtifactSlide,
    PPTXBulletsElement,
    PPTXCalloutElement,
    PPTXMetricElement,
    PPTXParagraphElement,
    PPTXTableElement,
    PPTXTitleElement,
)
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR, IRBlock, IRSection, SourceLocation
from app.models.interpretation import DocumentInterpretation, SourceReference
from app.models.llm import LLMTokenUsage
from app.models.transformation import PPTXOutputStructure, TransformationPlan
from app.prompts.artifact import ARTIFACT_PROMPT_VERSION, build_artifact_messages
from app.services.artifact_contracts import (
    ArtifactContract,
    ArtifactContractConfigurationError,
    get_artifact_contract,
    get_native_ir_writer,
)
from app.services.interpretation import SourceReferenceResolver
from app.services.llm import LLMService
from app.services.native_writer_errors import UnsupportedIRContentError
from app.storage.artifacts import ArtifactStore
from app.storage.interpretations import InterpretationStore


logger = logging.getLogger(__name__)
MOCK_ARTIFACT_WARNING = "MOCK_LLM is enabled; this is a deterministic source-content artifact, not an AI transformation."
NATIVE_IR_WRITER_VERSION = "native_ir_writer_v1"


class UnsupportedArtifactFormatError(ValueError):
    """A valid target format does not yet have a native renderer."""


class UnsupportedArtifactElementError(ValueError):
    """A plan requests an element that the native renderer cannot produce."""


class InvalidArtifactContentError(ValueError):
    """Generated structured content or rendered output failed validation."""

    def __init__(self, message: str, *, diagnostics: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


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
        # Resolve and verify the complete schema/prompt/writer contract before
        # invoking the provider or producing a mock artifact.
        native_writer = get_native_ir_writer(target_format)
        contract: ArtifactContract | None = None if native_writer else get_artifact_contract(target_format)
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
        if native_writer is not None and plan is not None:
            raise UnsupportedIRContentError(
                f"The deterministic native {target_format.value.upper()} export serializes canonical IR and does not apply semantic transformation plans."
            )
        if native_writer is not None and user_instructions and user_instructions.strip():
            raise UnsupportedIRContentError(
                f"The deterministic native {target_format.value.upper()} export cannot apply user transformation instructions."
            )
        if target_format == DocumentFormat.PPTX and plan is not None:
            _reject_unsupported_pptx_plan_elements(plan)
        if target_format == DocumentFormat.HTML and plan is not None:
            _reject_unsupported_html_plan_elements(plan)

        completion = None
        is_mock = False if native_writer is not None else self.llm_service.settings.mock_llm
        warnings: list[str] = (
            ["Generated directly from canonical DocumentIR by a deterministic native writer; no LLM was used."]
            if native_writer is not None
            else []
        )
        content = None
        if native_writer is None and is_mock:
            content = _mock_content(document_ir, target_format)
            warnings.append(MOCK_ARTIFACT_WARNING)
        elif native_writer is None:
            assert contract is not None
            messages = build_artifact_messages(
                document_ir,
                interpretation,
                target_format,
                user_instructions,
                plan,
                contract=contract,
            )
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
                    contract=contract,
                )
                try:
                    validate_artifact_references(content, document_ir)
                except Exception as exc:
                    raise InvalidArtifactContentError("Generated content cited a source location that does not resolve to the input document.") from exc
                if target_format == DocumentFormat.PPTX and plan is not None:
                    _validate_pptx_plan_alignment(content, plan)
                elif target_format == DocumentFormat.DOCX and plan is not None:
                    _validate_docx_plan_alignment(content, plan)
                elif target_format == DocumentFormat.HTML and plan is not None:
                    _validate_html_plan_alignment(content, plan)

        try:
            if native_writer is not None:
                rendered = native_writer.writer(document_ir)
                native_writer.output_validator(rendered)
            else:
                assert contract is not None and content is not None
                provenance = _pptx_provenance(document_ir, interpretation, plan, run_id) if target_format == DocumentFormat.PPTX else {}
                rendered = contract.writer(content, is_mock, provenance)
                contract.output_validator(rendered)
        except UnsupportedIRContentError:
            raise
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
            provider=completion.provider if completion is not None else ("native_ir" if native_writer else "mock"),
            model=completion.model if completion is not None else ("deterministic-writer" if native_writer else "mock"),
            prompt_version=NATIVE_IR_WRITER_VERSION if native_writer else ARTIFACT_PROMPT_VERSION,
            artifact_schema_version=native_writer.schema_version if native_writer else contract.schema_version,
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
    contract: ArtifactContract | None = None,
):
    contract = contract or get_artifact_contract(target_format)
    if contract.target_format != target_format:
        raise ArtifactContractConfigurationError(target_format, "parser schema does not match the requested format")
    model = contract.schema_model
    normalized_content, was_fenced = _unwrap_json_fence(content)
    try:
        payload = json.loads(normalized_content, parse_constant=_reject_nonstandard_json_constant)
    except (json.JSONDecodeError, ValueError) as parse_error:
        try:
            model.model_validate_json(normalized_content)
        except ValidationError as exc:
            diagnostics = _artifact_validation_diagnostics(
                exc,
                target_format=target_format,
                model_name=model.__name__,
                prompt_version=ARTIFACT_PROMPT_VERSION,
                artifact_schema_version=contract.schema_version,
                json_parsing_succeeded=False,
            )
            _log_artifact_validation_failure(
                exc,
                normalized_content,
                was_fenced=was_fenced,
                finish_reason=finish_reason,
                usage=usage,
                json_parsing_succeeded=False,
                target_format=target_format,
                model_name=model.__name__,
                prompt_version=ARTIFACT_PROMPT_VERSION,
                artifact_schema_version=contract.schema_version,
                diagnostics=diagnostics,
            )
            raise InvalidArtifactContentError(
                "The provider response did not contain valid JSON for the target document schema.",
                diagnostics=diagnostics,
            ) from exc
        diagnostics = {
            "target_format": target_format.value,
            "schema_model": model.__name__,
            "prompt_version": ARTIFACT_PROMPT_VERSION,
            "artifact_schema_version": contract.schema_version,
            "error_category": "invalid_json",
            "json_parsing_succeeded": False,
            "validation_errors": [],
        }
        logger.error(
            "artifact_content_validation_failed",
            extra={
                "failure_phase": "artifact_json_parsing",
                "failure_reason": "invalid_json",
                "exception_class": type(parse_error).__name__,
                "error_category": "invalid_artifact_content",
                "target_format": target_format.value,
                "schema_model": model.__name__,
                "prompt_version": ARTIFACT_PROMPT_VERSION,
                "artifact_schema_version": contract.schema_version,
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
        raise InvalidArtifactContentError(
            "The provider response did not contain valid JSON for the target document schema.",
            diagnostics=diagnostics,
        ) from parse_error

    normalized_references = _normalize_nested_reference_section_ids(payload)
    normalized_cells = _normalize_table_cells(payload)
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        diagnostics = _artifact_validation_diagnostics(
            exc,
            target_format=target_format,
            model_name=model.__name__,
            prompt_version=ARTIFACT_PROMPT_VERSION,
            artifact_schema_version=contract.schema_version,
            json_parsing_succeeded=True,
        )
        _log_artifact_validation_failure(
            exc,
            normalized_content,
            was_fenced=was_fenced,
            finish_reason=finish_reason,
            usage=usage,
            json_parsing_succeeded=True,
            target_format=target_format,
            model_name=model.__name__,
            prompt_version=ARTIFACT_PROMPT_VERSION,
            artifact_schema_version=contract.schema_version,
            diagnostics=diagnostics,
            normalized_table_cell_count=normalized_cells,
            normalized_section_reference_count=normalized_references,
        )
        raise InvalidArtifactContentError(
            "The provider response did not match the target document schema.",
            diagnostics=diagnostics,
        ) from exc
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
    if not isinstance(payload, dict):
        return 0
    tables: list[dict] = []
    for section in payload.get("sections", []):
        if isinstance(section, dict) and isinstance(section.get("tables"), list):
            tables.extend(table for table in section["tables"] if isinstance(table, dict))
    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        for element in slide.get("elements", []):
            if isinstance(element, dict) and element.get("element_type") == "table":
                table = element.get("content")
                if isinstance(table, dict):
                    tables.append(table)
    normalized = 0
    for table in tables:
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
    if not isinstance(payload, dict):
        return 0
    normalized = 0
    items: list[dict] = []
    for section in payload.get("sections", []):
        if isinstance(section, dict):
            for collection_name in ("paragraphs", "bullet_points", "metrics", "tables"):
                collection = section.get(collection_name)
                if isinstance(collection, list):
                    items.extend(item for item in collection if isinstance(item, dict))
    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        title_references = slide.get("title_source_references")
        if isinstance(title_references, list):
            items.append({"source_references": title_references})
        for element in slide.get("elements", []):
            if not isinstance(element, dict):
                continue
            for item_key in ("content", "items"):
                item_value = element.get(item_key)
                if isinstance(item_value, dict):
                    items.append(item_value)
                elif isinstance(item_value, list):
                    items.extend(item for item in item_value if isinstance(item, dict))
    for item in items:
        if not isinstance(item.get("source_references"), list):
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
                del location["section_id"]
                normalized += 1
            # Conflicting values deliberately remain unnormalized and fail
            # SourceLocation's extra-forbid validation.
    return normalized


def _log_artifact_validation_failure(
    exc: ValidationError,
    content: str,
    *,
    was_fenced: bool,
    finish_reason: str | None,
    usage: LLMTokenUsage | None,
    json_parsing_succeeded: bool,
    target_format: DocumentFormat,
    model_name: str,
    prompt_version: str,
    artifact_schema_version: str,
    diagnostics: dict[str, object],
    normalized_table_cell_count: int = 0,
    normalized_section_reference_count: int = 0,
) -> None:
    logger.error(
        "artifact_content_validation_failed",
        extra={
            "failure_phase": "artifact_schema_validation" if json_parsing_succeeded else "artifact_json_parsing",
            "failure_reason": "schema_mismatch" if json_parsing_succeeded else "invalid_json",
            "exception_class": type(exc).__name__,
            "error_category": "invalid_artifact_content",
            "target_format": target_format.value,
            "schema_model": model_name,
            "prompt_version": prompt_version,
            "artifact_schema_version": artifact_schema_version,
            "json_parsing_failed": not json_parsing_succeeded,
            "json_parsing_succeeded": json_parsing_succeeded,
            "pydantic_errors": diagnostics["validation_errors"],
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


def _artifact_validation_diagnostics(
    exc: ValidationError,
    *,
    target_format: DocumentFormat,
    model_name: str,
    prompt_version: str,
    artifact_schema_version: str,
    json_parsing_succeeded: bool,
) -> dict[str, object]:
    errors = exc.errors(include_url=False, include_input=False)
    return {
        "target_format": target_format.value,
        "schema_model": model_name,
        "prompt_version": prompt_version,
        "artifact_schema_version": artifact_schema_version,
        "error_category": "schema_validation",
        "json_parsing_succeeded": json_parsing_succeeded,
        "validation_errors": [
            {
                "field_path": _safe_error_location(error.get("loc", ())),
                "error_type": error.get("type", "unknown"),
                # Keep the original log keys for existing dashboards/tests.
                "location": _safe_error_location(error.get("loc", ())),
                "type": error.get("type", "unknown"),
                "category": _validation_error_category(error.get("type", "unknown")),
            }
            for error in errors
        ],
    }


def _validation_error_category(error_type: str) -> str:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "undeclared_field"
    if error_type.endswith("_type"):
        return "incorrect_type"
    return "constraint_violation"


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
    if isinstance(content, PPTXArtifactContent):
        for slide in content.slides:
            for reference in slide.title_source_references:
                resolver.validate(reference)
            for item in _pptx_source_items(slide):
                for reference in item.source_references:
                    resolver.validate(reference)
        return
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
    if target_format == DocumentFormat.DOCX:
        return DOCXArtifactContent(
            target_format="docx",
            document_title=title,
            sections=[DOCXArtifactSection.model_validate(section.model_dump(mode="python")) for section in sections],
        )
    if target_format == DocumentFormat.PPTX:
        return _mock_pptx_content(document_ir)
    raise UnsupportedArtifactFormatError


def _mock_pptx_content(document_ir: DocumentIR) -> PPTXArtifactContent:
    title = document_ir.title or document_ir.filename
    section_contents: list[tuple[ArtifactSection, SourceReference | None]] = []

    def visit(source_sections: list[IRSection]) -> None:
        for source_section in source_sections:
            artifact_section = _mock_section_from_blocks(
                source_section.title, source_section, source_section.blocks
            )
            if artifact_section is not None:
                section_reference = None
                if source_section.source is not None and _has_coordinates(source_section.source):
                    section_reference = SourceReference(
                        section_id=source_section.id,
                        source_location=source_section.source,
                    )
                section_contents.append((artifact_section, section_reference))
            visit(source_section.children)

    visit(document_ir.sections)
    if document_ir.blocks:
        loose = _mock_section_from_blocks("Document content", None, document_ir.blocks)
        if loose is not None:
            section_contents.append((loose, None))

    slides: list[PPTXArtifactSlide] = []
    for slide_index, (section, title_reference) in enumerate(section_contents, start=1):
        slide_id = f"mock-slide-{slide_index}"
        elements = []
        for index, paragraph in enumerate(section.paragraphs, start=1):
            elements.append(PPTXParagraphElement(
                element_id=f"{slide_id}-paragraph-{index}",
                element_type="paragraph",
                content=paragraph,
            ))
        if section.bullet_points:
            elements.append(PPTXBulletsElement(
                element_id=f"{slide_id}-bullets-1",
                element_type="bullets",
                items=section.bullet_points,
            ))
        for index, metric in enumerate(section.metrics, start=1):
            elements.append(PPTXMetricElement(
                element_id=f"{slide_id}-metric-{index}",
                element_type="metric",
                content=metric,
            ))
        for index, table in enumerate(section.tables, start=1):
            elements.append(PPTXTableElement(
                element_id=f"{slide_id}-table-{index}",
                element_type="table",
                content=table,
            ))
        if elements:
            slides.append(PPTXArtifactSlide(
                slide_id=slide_id,
                title=section.heading,
                title_source_references=[title_reference] if title_reference else [],
                elements=elements,
            ))
    if not slides:
        raise InvalidArtifactContentError("The source IR contains no renderable content.")
    return PPTXArtifactContent(target_format="pptx", presentation_title=title, slides=slides)


def _pptx_source_items(slide: PPTXArtifactSlide):
    for element in slide.elements:
        if isinstance(element, (PPTXTitleElement, PPTXParagraphElement, PPTXCalloutElement)):
            yield element.content
        elif isinstance(element, PPTXBulletsElement):
            yield from element.items
        elif isinstance(element, (PPTXTableElement, PPTXMetricElement)):
            yield element.content
        elif isinstance(element, PPTXChartElement):
            yield element.content


def _reject_unsupported_pptx_plan_elements(plan: TransformationPlan) -> None:
    structure = plan.output_structure
    if not isinstance(structure, PPTXOutputStructure):
        return
    unsupported = [
        element.element_type
        for slide in structure.slides
        for element in slide.elements
        if element.element_type == "image_placeholder"
    ]
    if unsupported:
        kinds = ", ".join(sorted(set(unsupported)))
        raise UnsupportedArtifactElementError(
            f"PPTX plan element(s) are not supported by the current native writer: {kinds}."
        )


def _reject_unsupported_html_plan_elements(plan: TransformationPlan) -> None:
    from app.models.transformation import HTMLOutputStructure

    structure = plan.output_structure
    if not isinstance(structure, HTMLOutputStructure):
        raise InvalidArtifactContentError("The HTML transformation plan has no HTML output structure.")
    unsupported = [component.component_type for section in structure.sections for component in section.components
                   if component.component_type in {"chart", "link"}]
    if unsupported:
        kinds = ", ".join(sorted(set(unsupported)))
        raise UnsupportedArtifactElementError(
            f"HTML plan component(s) are not supported by the current native writer: {kinds}."
        )


def _validate_pptx_plan_alignment(content: PPTXArtifactContent, plan: TransformationPlan) -> None:
    structure = plan.output_structure
    if not isinstance(structure, PPTXOutputStructure):
        raise InvalidArtifactContentError("The PPTX transformation plan has no PPTX output structure.")
    planned_slides = {slide.slide_id: slide for slide in structure.slides}
    output_slides = {slide.slide_id: slide for slide in content.slides}
    if len(output_slides) != len(content.slides) or set(output_slides) != set(planned_slides):
        raise InvalidArtifactContentError("Generated PPTX slides do not match the validated plan.")
    mapping_destinations: dict[str, tuple[str, str]] = {}
    mappings_by_id = {mapping.mapping_id: mapping for mapping in plan.content_mappings}
    for slide in structure.slides:
        for mapping_id in slide.mapping_ids:
            mapping_destinations[mapping_id] = ("slide", slide.slide_id)
        for element in slide.elements:
            for mapping_id in element.mapping_ids:
                mapping_destinations[mapping_id] = ("slide_element", element.element_id)
    placements: list[tuple[str, tuple[str, str]]] = []
    for slide_id, output_slide in output_slides.items():
        planned_slide = planned_slides[slide_id]
        if output_slide.title != planned_slide.title:
            raise InvalidArtifactContentError("Generated PPTX slide titles do not match the validated plan.")
        if output_slide.purpose is not None and output_slide.purpose != planned_slide.purpose:
            raise InvalidArtifactContentError("Generated PPTX slide purpose does not match the validated plan.")
        if output_slide.visual_guidance is not None and output_slide.visual_guidance != planned_slide.visual_guidance:
            raise InvalidArtifactContentError("Generated PPTX visual guidance does not match the validated plan.")
        if output_slide.mapping_ids != planned_slide.mapping_ids:
            raise InvalidArtifactContentError("Generated PPTX slide mappings do not match the validated plan.")
        slide_references = {
            _reference_fingerprint(reference)
            for reference in output_slide.title_source_references
        }
        for item in _pptx_source_items(output_slide):
            slide_references.update(_reference_fingerprint(reference) for reference in item.source_references)
        for mapping_id in output_slide.mapping_ids:
            mapping = mappings_by_id.get(mapping_id)
            if mapping is None or not {
                _reference_fingerprint(reference) for reference in mapping.source_references
            }.issubset(slide_references):
                raise InvalidArtifactContentError("Generated PPTX slide content did not preserve all mapped source references.")
        planned_elements = {element.element_id: element for element in planned_slide.elements}
        output_elements = {element.element_id: element for element in output_slide.elements}
        if len(output_elements) != len(output_slide.elements) or set(output_elements) != set(planned_elements):
            raise InvalidArtifactContentError("Generated PPTX elements do not match the validated plan.")
        for element_id, output_element in output_elements.items():
            planned_element = planned_elements[element_id]
            if output_element.element_type != planned_element.element_type:
                raise InvalidArtifactContentError("Generated PPTX element types do not match the validated plan.")
            element_references = {
                _reference_fingerprint(reference)
                for item in _pptx_source_items(PPTXArtifactSlide(
                    slide_id=output_slide.slide_id,
                    title=output_slide.title,
                    elements=[output_element],
                ))
                for reference in item.source_references
            }
            for mapping_id in output_element.mapping_ids:
                placements.append((mapping_id, ("slide_element", element_id)))
                mapping = mappings_by_id.get(mapping_id)
                if mapping is None or not {
                    _reference_fingerprint(reference) for reference in mapping.source_references
                }.issubset(element_references):
                    raise InvalidArtifactContentError("Generated PPTX element did not preserve all mapped source references.")
    for slide in content.slides:
        for mapping_id in slide.mapping_ids:
            placements.append((mapping_id, ("slide", slide.slide_id)))
    seen_ids = [mapping_id for mapping_id, _ in placements]
    if len(seen_ids) != len(set(seen_ids)):
        raise InvalidArtifactContentError("Generated PPTX content repeats a plan mapping ID.")
    if dict(placements) != mapping_destinations or set(seen_ids) != set(mapping_destinations):
        raise InvalidArtifactContentError("Generated PPTX mapping placements do not match the validated plan.")


def _validate_docx_plan_alignment(content: DOCXArtifactContent, plan: TransformationPlan) -> None:
    from app.models.transformation import DOCXOutputStructure

    structure = plan.output_structure
    if not isinstance(structure, DOCXOutputStructure):
        raise InvalidArtifactContentError("The DOCX transformation plan has no DOCX output structure.")
    planned_by_id = {section.section_id: section for section in structure.sections}
    if [section.section_id for section in content.sections] != [section.section_id for section in structure.sections]:
        raise InvalidArtifactContentError("Generated DOCX sections or their ordering do not match the validated plan.")
    mapping_destinations = _mapping_destinations(plan)
    for section in content.sections:
        planned = planned_by_id[section.section_id]
        if section.heading != planned.title or section.heading_level != planned.heading_level:
            raise InvalidArtifactContentError("Generated DOCX section heading or hierarchy does not match the validated plan.")
        expected_section_mappings = mapping_destinations.get(("doc_section", section.section_id), [])
        if section.mapping_ids != expected_section_mappings:
            raise InvalidArtifactContentError("Generated DOCX section mappings do not match their declared destinations.")
        items, section_items = _docx_items_by_id(section)
        expected_element_ids = [element.element_id for element in planned.elements]
        if section.element_order != expected_element_ids or set(items) != set(expected_element_ids):
            raise InvalidArtifactContentError("Generated DOCX elements or their ordering do not match the validated plan.")
        section_item_mapping_ids = [mapping_id for item in section_items for mapping_id in item.mapping_ids]
        if len(section_item_mapping_ids) != len(set(section_item_mapping_ids)) or set(section_item_mapping_ids) != set(expected_section_mappings):
            raise InvalidArtifactContentError("Generated DOCX section-level content mappings do not match their declared destinations.")
        for element in planned.elements:
            item_kind, item = items[element.element_id]
            expected_kinds = {
                "heading": {"paragraph_heading"},
                "paragraph": {"paragraph"},
                "callout": {"callout"},
                "list": {"bullet"},
                "table": {"table", "metric"},
            }[element.element_type]
            actual_kind = (
                "paragraph_heading" if item_kind == "paragraph" and item.element_type == "heading"
                else "list" if item_kind == "bullet"
                else item.element_type if item_kind == "paragraph"
                else item_kind
            )
            if actual_kind not in expected_kinds:
                raise InvalidArtifactContentError("Generated DOCX element types do not match the validated plan.")
            target = ("doc_element", element.element_id)
            expected_mapping_ids = mapping_destinations.get(target, [])
            if item.mapping_ids != expected_mapping_ids:
                raise InvalidArtifactContentError("Generated DOCX element mappings do not match their declared destinations.")
            _validate_item_mapping_references(plan, item.mapping_ids, _item_references(item))
        section_references = [reference for item in items.values() for reference in _item_references(item[1])]
        section_references.extend(reference for item in section_items for reference in _item_references(item))
        _validate_item_mapping_references(plan, section.mapping_ids, section_references)


def _validate_html_plan_alignment(content: HTMLArtifactContent, plan: TransformationPlan) -> None:
    from app.models.transformation import HTMLOutputStructure

    structure = plan.output_structure
    if not isinstance(structure, HTMLOutputStructure):
        raise InvalidArtifactContentError("The HTML transformation plan has no HTML output structure.")
    if content.page_title != structure.page_title or content.include_navigation != structure.include_navigation:
        raise InvalidArtifactContentError("Generated HTML title or navigation configuration does not match the validated plan.")
    if [section.section_id for section in content.sections] != [section.section_id for section in structure.sections]:
        raise InvalidArtifactContentError("Generated HTML sections or their ordering do not match the validated plan.")
    mapping_destinations = _mapping_destinations(plan)
    for section, planned in zip(content.sections, structure.sections, strict=True):
        if (
            section.heading != planned.heading
            or section.semantic_element != planned.semantic_element
            or section.purpose != planned.purpose
        ):
            raise InvalidArtifactContentError("Generated HTML section semantics do not match the validated plan.")
        if section.mapping_ids != mapping_destinations.get(("html_section", planned.section_id), []):
            raise InvalidArtifactContentError("Generated HTML section mappings do not match their declared destinations.")
        items, section_items = _html_items_by_id(section)
        expected_ids = [component.component_id for component in planned.components]
        if section.component_order != expected_ids or set(items) != set(expected_ids):
            raise InvalidArtifactContentError("Generated HTML components or their ordering do not match the validated plan.")
        expected_section_mappings = mapping_destinations.get(("html_section", planned.section_id), [])
        section_item_mapping_ids = [mapping_id for item in section_items for mapping_id in item.mapping_ids]
        if len(section_item_mapping_ids) != len(set(section_item_mapping_ids)) or set(section_item_mapping_ids) != set(expected_section_mappings):
            raise InvalidArtifactContentError("Generated HTML section-level content mappings do not match their declared destinations.")
        for component in planned.components:
            item_kind, item, output_type = items[component.component_id]
            if output_type != component.component_type:
                raise InvalidArtifactContentError("Generated HTML component types do not match the validated plan.")
            expected_mapping_ids = mapping_destinations.get(("html_component", component.component_id), [])
            if item.mapping_ids != expected_mapping_ids:
                raise InvalidArtifactContentError("Generated HTML component mappings do not match their declared destinations.")
            _validate_item_mapping_references(plan, item.mapping_ids, _item_references(item))
        section_references = [reference for _, item, _ in items.values() for reference in _item_references(item)]
        section_references.extend(reference for item in section_items for reference in _item_references(item))
        _validate_item_mapping_references(plan, section.mapping_ids, section_references)


def _mapping_destinations(plan: TransformationPlan) -> dict[tuple[str, str], list[str]]:
    destinations: dict[tuple[str, str], list[str]] = {}
    for mapping in plan.content_mappings:
        key = (mapping.destination.target_type, mapping.destination.target_id)
        destinations.setdefault(key, []).append(mapping.mapping_id)
    return destinations


def _docx_items_by_id(section: DOCXArtifactSection):
    result = {}
    section_items = []
    for kind, collection in (("paragraph", section.paragraphs), ("bullet", section.bullet_points), ("metric", section.metrics), ("table", section.tables)):
        for item in collection:
            if item.element_id is None:
                if not item.mapping_ids:
                    raise InvalidArtifactContentError("Generated DOCX section-level content must carry its mapping IDs.")
                section_items.append(item)
                continue
            if item.element_id in result:
                raise InvalidArtifactContentError("Generated DOCX content has a missing or duplicate element ID.")
            result[item.element_id] = (kind, item)
    return result, section_items


def _html_items_by_id(section: HTMLArtifactSection):
    result = {}
    section_items = []
    for kind, collection, component_type in (
        ("text", section.paragraphs, None),
        ("text", section.bullet_points, "list"),
        ("metric", section.metrics, "metric_card"),
        ("table", section.tables, "table"),
    ):
        for item in collection:
            if item.element_id is None:
                if not item.mapping_ids:
                    raise InvalidArtifactContentError("Generated HTML section-level content must carry its mapping IDs.")
                section_items.append(item)
                continue
            if item.element_id in result:
                raise InvalidArtifactContentError("Generated HTML content has a missing or duplicate component ID.")
            result[item.element_id] = (kind, item, component_type or item.element_type)
    return result, section_items


def _item_references(item):
    if isinstance(item, ArtifactText):
        return item.source_references
    return item.source_references


def _validate_item_mapping_references(plan: TransformationPlan, mapping_ids: list[str], references) -> None:
    reference_keys = {_reference_fingerprint(reference) for reference in references}
    mappings = {mapping.mapping_id: mapping for mapping in plan.content_mappings}
    for mapping_id in mapping_ids:
        mapping = mappings.get(mapping_id)
        if mapping is None or not {
            _reference_fingerprint(reference) for reference in mapping.source_references
        }.issubset(reference_keys):
            raise InvalidArtifactContentError("Generated content did not preserve the source references for its plan mapping.")


def _reference_fingerprint(reference: SourceReference) -> str:
    return json.dumps(reference.model_dump(mode="json", exclude_none=True), sort_keys=True, separators=(",", ":"))


def _pptx_provenance(document_ir, interpretation, plan, run_id) -> dict[str, object]:
    return {
        "run_id": str(run_id),
        "document_id": document_ir.document_id,
        "source_format": document_ir.source_format.value,
        "source_provenance": [item.model_dump(mode="json", exclude_none=True) for item in document_ir.provenance],
        "interpretation_id": str(interpretation.interpretation_id),
        "interpretation_provenance": interpretation.provenance.model_dump(mode="json", exclude_none=True),
        "plan_id": str(plan.plan_id) if plan else None,
        "plan_provenance": plan.provenance.model_dump(mode="json", exclude_none=True) if plan else None,
    }


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
