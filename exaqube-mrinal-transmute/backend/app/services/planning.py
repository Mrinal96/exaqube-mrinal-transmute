"""Validated transformation planning, accounting, fingerprinting, and persistence."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError

from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR, IRBlock
from app.models.interpretation import DocumentInterpretation, SourceReference
from app.models.llm import LLMCompletionResult
from app.models.transformation import (
    ContentMapping,
    DOCX_PLAN_SCHEMA_VERSION,
    DOCXTransformationPlanDraft,
    DOCXOutputStructure,
    HTMLOutputStructure,
    MMDOutputStructure,
    OutputStructure,
    PlanSourceItem,
    PlanValidationRules,
    PPTXElementPlan,
    PPTXOutputStructure,
    PPTXPlanningOutputStructure,
    PPTXSlidePlan,
    PPTX_PROVIDER_SCHEMA_VERSION,
    PPTXTransformationPlanDraft,
    TransformationMetadata,
    TransformationPlan,
    TransformationPlanDraft,
    TransformationProvenance,
    XLSXOutputStructure,
)
from app.prompts.transformation import build_transformation_messages, prompt_version_for, semantic_source_items
from app.services.interpretation import SourceReferenceResolver, UnresolvedSourceReferenceError
from app.services.llm import LLMService
from app.storage.transformations import TransformationStore

logger = logging.getLogger(__name__)
MOCK_PLAN_WARNING = "MOCK_LLM or mock interpretation is present; no transformation plan was generated."


@dataclass(frozen=True)
class StoredPlan:
    plan: TransformationPlan
    reused: bool


class PlanningError(RuntimeError):
    """Base class for safe transformation planning failures."""


class InvalidTargetFormatError(PlanningError):
    pass


class DocumentInterpretationMismatchError(PlanningError):
    pass


class InvalidPlanResponseError(PlanningError):
    pass


class PlanValidationError(PlanningError):
    pass


class PlanAccountingError(PlanValidationError):
    pass


class PlanningService:
    def __init__(self, llm_service: LLMService, storage_root: Path) -> None:
        self.llm_service = llm_service
        self.store = TransformationStore(storage_root)
        self._fingerprint_locks: dict[str, asyncio.Lock] = {}

    async def create_plan(
        self,
        document_ir: DocumentIR,
        interpretation: DocumentInterpretation,
        target_format: DocumentFormat | str,
        user_instructions: str | None = None,
    ) -> TransformationPlan:
        result = await self.create_plan_with_status(
            document_ir, interpretation, target_format, user_instructions
        )
        return result.plan

    async def create_plan_with_status(
        self,
        document_ir: DocumentIR,
        interpretation: DocumentInterpretation,
        target_format: DocumentFormat | str,
        user_instructions: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> StoredPlan:
        target = _normalize_target_format(target_format)
        if interpretation.document_id != document_ir.document_id:
            raise DocumentInterpretationMismatchError("The interpretation does not belong to the supplied document.")

        source_ir_fingerprint = self.store.fingerprint(document_ir.model_dump(mode="json"))
        if interpretation.metadata.source_ir_fingerprint != source_ir_fingerprint:
            raise DocumentInterpretationMismatchError("The interpretation was not derived from the supplied DocumentIR.")
        if interpretation.metadata.source_format != document_ir.source_format:
            raise DocumentInterpretationMismatchError("The interpretation source format does not match the supplied document.")

        interpretation_fingerprint = self.store.fingerprint(interpretation.model_dump(mode="json"))
        instruction_fingerprint = hashlib.sha256((user_instructions or "").encode("utf-8")).hexdigest()
        provider_identity = self._provider_identity(interpretation)
        prompt_version = prompt_version_for(target)
        fingerprint_payload = {
            "document_id": document_ir.document_id,
            "source_ir_fingerprint": source_ir_fingerprint,
            "interpretation_id": str(interpretation.interpretation_id),
            "interpretation_fingerprint": interpretation_fingerprint,
            "target_format": target.value,
            "user_instructions": user_instructions,
            "prompt_version": prompt_version,
            "provider_identity": provider_identity,
        }
        if target == DocumentFormat.PPTX:
            fingerprint_payload["planning_schema_version"] = PPTX_PROVIDER_SCHEMA_VERSION
        input_fingerprint = self.store.fingerprint(fingerprint_payload)

        if idempotency_key is not None:
            await asyncio.to_thread(
                self.store.bind_idempotency_key, document_ir.document_id, idempotency_key, input_fingerprint
            )
        lock = self._fingerprint_locks.setdefault(input_fingerprint, asyncio.Lock())
        async with lock:
            cached = await asyncio.to_thread(
                self.store.get,
                document_ir.document_id,
                str(interpretation.interpretation_id),
                input_fingerprint,
            )
            if cached is not None:
                logger.info("transformation_plan_reused", extra={"node_id": document_ir.document_id})
                return StoredPlan(cached, True)

            should_mock = bool(self.llm_service.settings.mock_llm or interpretation.provenance.is_mock)
            completion: LLMCompletionResult | None = None
            draft: TransformationPlanDraft | None = None
            if not should_mock:
                messages = build_transformation_messages(document_ir, interpretation, target, user_instructions)
                completion = await self.llm_service.complete(messages)
                should_mock = completion.is_mock
                if not should_mock:
                    draft = _parse_plan_draft(completion.content, target)
                    if draft.target_format != target:
                        raise _plan_validation_error(
                            "The provider plan target does not match the requested target format.",
                            category="target_format_mismatch",
                            path=["target_format"],
                        )
                    validate_transformation_draft(draft, document_ir, interpretation)

            if should_mock:
                plan = self._build_mock_plan(
                    document_ir,
                    interpretation,
                    target,
                    user_instructions,
                    source_ir_fingerprint,
                    interpretation_fingerprint,
                    instruction_fingerprint,
                    input_fingerprint,
                    completion,
                )
            else:
                assert completion is not None and draft is not None
                required_items = [
                    PlanSourceItem(source_item_type=item["source_item_type"], source_item_id=item["source_item_id"])
                    for item in semantic_source_items(interpretation)
                ]
                plan = TransformationPlan(
                    plan_id=uuid4(),
                    document_id=document_ir.document_id,
                    interpretation_id=interpretation.interpretation_id,
                    schema_version=DOCX_PLAN_SCHEMA_VERSION if target == DocumentFormat.DOCX else "1.0",
                    target_format=target,
                    user_instructions=user_instructions,
                    output_structure=draft.output_structure,
                    content_mappings=draft.content_mappings,
                    generation_instructions=draft.generation_instructions,
                    preservation_rules=draft.preservation_rules,
                    omissions=draft.omissions,
                    validation_rules=PlanValidationRules(
                        validation_status="ready",
                        target_format=target,
                        required_content_items=required_items,
                    ),
                    provenance=TransformationProvenance(
                        provider=completion.provider,
                        model=completion.model,
                        prompt_version=prompt_version,
                        created_at=datetime.now(timezone.utc),
                        is_mock=False,
                        token_usage=completion.usage,
                    ),
                    metadata=TransformationMetadata(
                        source_ir_fingerprint=source_ir_fingerprint,
                        interpretation_fingerprint=interpretation_fingerprint,
                        instruction_fingerprint=instruction_fingerprint,
                        input_fingerprint=input_fingerprint,
                    ),
                    warnings=[*document_ir.warnings, *interpretation.warnings, *draft.warnings],
                )

            saved = await asyncio.to_thread(self.store.save_if_absent, plan)
            reused = saved.plan_id != plan.plan_id
            logger.info("transformation_plan_created", extra={"node_id": document_ir.document_id})
            return StoredPlan(saved, reused)

    def _provider_identity(self, interpretation: DocumentInterpretation) -> dict[str, str | bool]:
        settings = self.llm_service.settings
        if settings.mock_llm or interpretation.provenance.is_mock:
            return {
                "provider": "mock",
                "model": "mock",
                "configured_provider_model": settings.llm_model,
                "is_mock": True,
            }
        return {
            "provider": "openai-compatible",
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "is_mock": False,
        }

    def _build_mock_plan(
        self,
        document_ir: DocumentIR,
        interpretation: DocumentInterpretation,
        target: DocumentFormat,
        user_instructions: str | None,
        source_ir_fingerprint: str,
        interpretation_fingerprint: str,
        instruction_fingerprint: str,
        input_fingerprint: str,
        completion: LLMCompletionResult | None,
    ) -> TransformationPlan:
        return TransformationPlan(
            plan_id=uuid4(),
            document_id=document_ir.document_id,
            interpretation_id=interpretation.interpretation_id,
            schema_version=DOCX_PLAN_SCHEMA_VERSION if target == DocumentFormat.DOCX else "1.0",
            target_format=target,
            user_instructions=user_instructions,
            output_structure=None,
            content_mappings=[],
            generation_instructions=[],
            preservation_rules=[],
            omissions=[],
            validation_rules=PlanValidationRules(validation_status="not_evaluated", target_format=target),
            provenance=TransformationProvenance(
                provider=completion.provider if completion else "mock",
                model=completion.model if completion else "mock",
                prompt_version=prompt_version_for(target),
                created_at=datetime.now(timezone.utc),
                is_mock=True,
                token_usage=completion.usage if completion else None,
            ),
            metadata=TransformationMetadata(
                source_ir_fingerprint=source_ir_fingerprint,
                interpretation_fingerprint=interpretation_fingerprint,
                instruction_fingerprint=instruction_fingerprint,
                input_fingerprint=input_fingerprint,
            ),
            warnings=[*document_ir.warnings, *interpretation.warnings, MOCK_PLAN_WARNING],
        )


def _normalize_target_format(target_format: DocumentFormat | str) -> DocumentFormat:
    try:
        return target_format if isinstance(target_format, DocumentFormat) else DocumentFormat(target_format)
    except (ValueError, TypeError) as exc:
        raise InvalidTargetFormatError("Target format must be one of PPTX, XLSX, DOCX, MMD, or HTML.") from exc


def _parse_plan_draft(content: str, target_format: DocumentFormat) -> TransformationPlanDraft:
    if target_format == DocumentFormat.DOCX:
        try:
            provider_draft = DOCXTransformationPlanDraft.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise InvalidPlanResponseError("The LLM response did not match the required transformation plan schema.") from exc
        return TransformationPlanDraft(
            target_format=provider_draft.target_format,
            output_structure=provider_draft.output_structure,
            content_mappings=provider_draft.content_mappings,
            generation_instructions=provider_draft.generation_instructions,
            preservation_rules=provider_draft.preservation_rules,
            omissions=provider_draft.omissions,
            warnings=provider_draft.warnings,
        )
    if target_format == DocumentFormat.PPTX:
        try:
            provider_draft = PPTXTransformationPlanDraft.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise InvalidPlanResponseError("The LLM response did not match the required transformation plan schema.") from exc
        output_structure = _materialize_pptx_mapping_ids(
            provider_draft.output_structure,
            provider_draft.content_mappings,
        )
        return TransformationPlanDraft(
            target_format=provider_draft.target_format,
            output_structure=output_structure,
            content_mappings=provider_draft.content_mappings,
            generation_instructions=provider_draft.generation_instructions,
            preservation_rules=provider_draft.preservation_rules,
            omissions=provider_draft.omissions,
            warnings=provider_draft.warnings,
        )
    try:
        return TransformationPlanDraft.model_validate_json(content)
    except (ValidationError, ValueError) as exc:
        raise InvalidPlanResponseError("The LLM response did not match the required transformation plan schema.") from exc


def _materialize_pptx_mapping_ids(
    provider_structure: PPTXPlanningOutputStructure,
    mappings: list[ContentMapping],
) -> PPTXOutputStructure:
    """Validate provider destinations, then derive final mapping_ids without redirection."""
    slide_indexes: dict[tuple[str, str], int] = {}
    element_indexes: dict[tuple[str, str], tuple[int, int]] = {}
    slide_mapping_ids: list[list[str]] = [[] for _ in provider_structure.slides]
    element_mapping_ids: list[list[list[str]]] = [
        [[] for _ in slide.elements] for slide in provider_structure.slides
    ]

    for slide_index, slide in enumerate(provider_structure.slides):
        slide_key = ("slide", slide.slide_id)
        if slide_key in slide_indexes:
            raise _plan_validation_error(
                "PPTX slide IDs must be unique.",
                category="duplicate_destination_id",
                path=["output_structure", "slides", slide_index, "slide_id"],
            )
        slide_indexes[slide_key] = slide_index
        for element_index, element in enumerate(slide.elements):
            element_key = ("slide_element", element.element_id)
            if element_key in element_indexes:
                raise _plan_validation_error(
                    "PPTX element IDs must be unique.",
                    category="duplicate_destination_id",
                    path=["output_structure", "slides", slide_index, "elements", element_index, "element_id"],
                )
            element_indexes[element_key] = (slide_index, element_index)

    seen_mapping_ids: set[str] = set()
    for mapping_index, mapping in enumerate(mappings):
        if mapping.mapping_id in seen_mapping_ids:
            raise _plan_validation_error(
                "Transformation mapping IDs must be unique.",
                category="duplicate_mapping_id",
                path=["content_mappings", mapping_index, "mapping_id"],
            )
        seen_mapping_ids.add(mapping.mapping_id)

        target_type = mapping.destination.target_type
        target_id = mapping.destination.target_id
        destination_key = (target_type, target_id)
        if target_type == "slide":
            slide_index = slide_indexes.get(destination_key)
            if slide_index is None:
                raise _plan_validation_error(
                    "A PPTX mapping destination must reference a declared slide_id.",
                    category="unknown_pptx_destination",
                    path=["content_mappings", mapping_index, "destination", "target_id"],
                )
            slide_mapping_ids[slide_index].append(mapping.mapping_id)
        elif target_type == "slide_element":
            element_location = element_indexes.get(destination_key)
            if element_location is None:
                raise _plan_validation_error(
                    "A PPTX mapping destination must reference a declared element_id.",
                    category="unknown_pptx_destination",
                    path=["content_mappings", mapping_index, "destination", "target_id"],
                )
            slide_index, element_index = element_location
            element_mapping_ids[slide_index][element_index].append(mapping.mapping_id)
        else:
            raise _plan_validation_error(
                "PPTX mapping destinations must use slide or slide_element.",
                category="invalid_pptx_destination_type",
                path=["content_mappings", mapping_index, "destination", "target_type"],
            )

    final_slides = [
        PPTXSlidePlan(
            slide_id=slide.slide_id,
            title=slide.title,
            purpose=slide.purpose,
            visual_guidance=slide.visual_guidance,
            mapping_ids=slide_mapping_ids[slide_index],
            elements=[
                PPTXElementPlan(
                    element_id=element.element_id,
                    element_type=element.element_type,
                    purpose=element.purpose,
                    mapping_ids=element_mapping_ids[slide_index][element_index],
                )
                for element_index, element in enumerate(slide.elements)
            ],
        )
        for slide_index, slide in enumerate(provider_structure.slides)
    ]
    return PPTXOutputStructure(
        target_format="pptx",
        presentation_title=provider_structure.presentation_title,
        slides=final_slides,
    )


def validate_transformation_draft(
    draft: TransformationPlanDraft,
    document_ir: DocumentIR,
    interpretation: DocumentInterpretation,
) -> None:
    """Check IDs, citations, destinations, and complete semantic-item accounting."""
    resolver = SourceReferenceResolver(document_ir)
    item_index = _interpretation_item_index(interpretation)
    try:
        for references in item_index.values():
            for reference in references:
                resolver.validate(reference)
    except UnresolvedSourceReferenceError as exc:
        raise _plan_validation_error(
            "The interpretation contains a source reference that does not resolve to the input IR.",
            category="unresolved_interpretation_reference",
            path=["interpretation", "source_references"],
        ) from exc

    mapping_index: dict[str, ContentMapping] = {}
    accounted_by_mapping: set[tuple[str, str]] = set()
    accounted_by_omission: set[tuple[str, str]] = set()

    for mapping in draft.content_mappings:
        if mapping.mapping_id in mapping_index:
            raise _plan_validation_error(
                "Transformation mapping IDs must be unique.",
                category="duplicate_mapping_id",
                path=["content_mappings", len(mapping_index), "mapping_id"],
            )
        mapping_index[mapping.mapping_id] = mapping
        item_key = (mapping.source_item_type, mapping.source_item_id)
        _validate_item_reference(item_key, mapping.source_references, item_index, document_ir, resolver)
        accounted_by_mapping.add(item_key)

    for omission in draft.omissions:
        item_key = (omission.source_item_type, omission.source_item_id)
        if item_key in accounted_by_omission:
            raise _plan_validation_error(
                "A source item may have only one omission record.",
                category="duplicate_omission",
                path=["omissions", len(accounted_by_omission), "source_item_id"],
            )
        if item_key in accounted_by_mapping:
            raise _plan_validation_error(
                "A source item cannot be both mapped and omitted.",
                category="mapped_and_omitted",
                path=["omissions", len(accounted_by_omission)],
                accounting=True,
            )
        _validate_item_reference(item_key, omission.source_references, item_index, document_ir, resolver)
        accounted_by_omission.add(item_key)

    for key in item_index:
        if key not in accounted_by_mapping and key not in accounted_by_omission:
            raise _plan_validation_error(
                "Every interpreted semantic item must be mapped or omitted with a reason.",
                category="unaccounted_semantic_item",
                path=["content_mappings", "omissions"],
                accounting=True,
            )

    _validate_destination_mappings(draft.output_structure, mapping_index)


def _interpretation_item_index(
    interpretation: DocumentInterpretation,
) -> dict[tuple[str, str], tuple[SourceReference, ...]]:
    result = {}
    for item in semantic_source_items(interpretation):
        references = item["source_references"]
        key = (item["source_item_type"], item["source_item_id"])
        result[key] = tuple(SourceReference.model_validate(reference) for reference in references)
    return result


def _validate_item_reference(
    key: tuple[str, str],
    references: list[SourceReference],
    semantic_items: dict[tuple[str, str], tuple[SourceReference, ...]],
    document_ir: DocumentIR,
    resolver: SourceReferenceResolver,
) -> None:
    source_item_type, source_item_id = key
    if source_item_type == "ir_block":
        blocks = _ir_block_index(document_ir)
        if source_item_id not in blocks:
            raise _plan_validation_error(
                "A plan mapping references an IR block absent from the source document.",
                category="unknown_ir_block",
                path=["content_mappings", "source_item_id"],
            )
        if any(reference.block_id != source_item_id for reference in references):
            raise _plan_validation_error(
                "An IR block mapping must cite that exact source block.",
                category="ir_block_reference_mismatch",
                path=["content_mappings", "source_references"],
            )
    else:
        expected_references = semantic_items.get(key)
        if expected_references is None:
            raise _plan_validation_error(
                "A plan mapping references a semantic item absent from the interpretation.",
                category="unknown_semantic_item",
                path=["content_mappings", "source_item_id"],
            )
        expected = {_reference_key(reference) for reference in expected_references}
        if any(_reference_key(reference) not in expected for reference in references):
            raise _plan_validation_error(
                "A plan mapping cites a source outside its semantic interpretation item.",
                category="semantic_reference_mismatch",
                path=["content_mappings", "source_references"],
            )
    try:
        for reference in references:
            resolver.validate(reference)
    except UnresolvedSourceReferenceError as exc:
        raise _plan_validation_error(
            "A plan contains a source reference that does not resolve to the input IR.",
            category="unresolved_plan_reference",
            path=["content_mappings", "source_references"],
        ) from exc


def _reference_key(reference: SourceReference) -> str:
    return json.dumps(reference.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ir_block_index(document_ir: DocumentIR) -> dict[str, IRBlock]:
    blocks: dict[str, IRBlock] = {}

    def visit(section) -> None:
        for block in section.blocks:
            blocks[block.id] = block
        for child in section.children:
            visit(child)

    for section in document_ir.sections:
        visit(section)
    blocks.update({block.id: block for block in document_ir.blocks})
    return blocks


def _validate_destination_mappings(structure: OutputStructure, mappings: dict[str, ContentMapping]) -> None:
    if isinstance(structure, DOCXOutputStructure):
        _validate_docx_mapping_destinations(structure, mappings)
        return

    destinations: dict[tuple[str, str], list[str]] = {}
    mapping_paths = {mapping_id: ["content_mappings", index] for index, mapping_id in enumerate(mappings)}

    def register(target_type: str, target_id: str, mapping_ids: list[str], path: list[str | int]) -> None:
        key = (target_type, target_id)
        if key in destinations:
            raise _plan_validation_error(
                "Output structure destination IDs must be unique within their target type.",
                category="duplicate_destination_id",
                path=[*path, "id"],
            )
        seen_mapping_ids: set[str] = set()
        for mapping_index, mapping_id in enumerate(mapping_ids):
            if mapping_id in seen_mapping_ids:
                raise _plan_validation_error(
                    "An output structure location cannot repeat a content mapping ID.",
                    category="duplicate_destination_mapping_id",
                    path=[*path, "mapping_ids", mapping_index],
                )
            seen_mapping_ids.add(mapping_id)
        destinations[key] = mapping_ids

    if isinstance(structure, PPTXOutputStructure):
        for slide_index, slide in enumerate(structure.slides):
            slide_path = ["output_structure", "slides", slide_index]
            register("slide", slide.slide_id, slide.mapping_ids, slide_path)
            for element_index, element in enumerate(slide.elements):
                register("slide_element", element.element_id, element.mapping_ids, [*slide_path, "elements", element_index])
    elif isinstance(structure, XLSXOutputStructure):
        for worksheet_index, worksheet in enumerate(structure.worksheets):
            worksheet_path = ["output_structure", "worksheets", worksheet_index]
            register("worksheet", worksheet.worksheet_id, worksheet.mapping_ids, worksheet_path)
            for table_index, table in enumerate(worksheet.tables):
                table_path = [*worksheet_path, "tables", table_index]
                register("table", table.table_id, table.mapping_ids, table_path)
                for column_index, column in enumerate(table.columns):
                    register("column", column.column_id, column.mapping_ids, [*table_path, "columns", column_index])
    elif isinstance(structure, MMDOutputStructure):
        for node_index, node in enumerate(structure.nodes):
            register("diagram_node", node.node_id, node.mapping_ids, ["output_structure", "nodes", node_index])
        for edge_index, edge in enumerate(structure.relationships):
            register("diagram_edge", edge.edge_id, edge.mapping_ids, ["output_structure", "relationships", edge_index])
    elif isinstance(structure, HTMLOutputStructure):
        for section_index, section in enumerate(structure.sections):
            section_path = ["output_structure", "sections", section_index]
            register("html_section", section.section_id, section.mapping_ids, section_path)
            for component_index, component in enumerate(section.components):
                register("html_component", component.component_id, component.mapping_ids, [*section_path, "components", component_index])

    referenced_mapping_ids: set[str] = set()
    for destination_key, mapping_ids in destinations.items():
        for mapping_index, mapping_id in enumerate(mapping_ids):
            path = ["output_structure", "destinations", "mapping_ids", mapping_index]
            mapping = mappings.get(mapping_id)
            if mapping is None:
                raise _plan_validation_error(
                    "Output structure references an unknown content mapping.",
                    category="unknown_mapping_id",
                    path=path,
                )
            if (mapping.destination.target_type, mapping.destination.target_id) != destination_key:
                raise _plan_validation_error(
                    "A content mapping destination does not match its output structure location.",
                    category="destination_mismatch",
                    path=[*mapping_paths[mapping_id], "destination"],
                )
            referenced_mapping_ids.add(mapping_id)

    for mapping_id, mapping in mappings.items():
        key = (mapping.destination.target_type, mapping.destination.target_id)
        if key not in destinations or mapping_id not in destinations[key]:
            raise _plan_validation_error(
                "Every content mapping must point to a declared output structure location.",
                category="undeclared_destination",
                path=[*mapping_paths[mapping_id], "destination"],
            )
    if referenced_mapping_ids != set(mappings):
        raise _plan_validation_error(
            "Every content mapping must appear at its declared output destination.",
            category="mapping_not_listed_at_destination",
            path=["output_structure"],
        )


def _validate_docx_mapping_destinations(
    structure: DOCXOutputStructure,
    mappings: dict[str, ContentMapping],
) -> None:
    declared: dict[tuple[str, str], list[str | int]] = {}

    def register(target_type: str, target_id: str, path: list[str | int]) -> None:
        key = (target_type, target_id)
        if key in declared:
            raise _plan_validation_error(
                "DOCX section and element IDs must be unique within their destination type.",
                category="duplicate_destination_id",
                path=[*path, "section_id" if target_type == "doc_section" else "element_id"],
            )
        declared[key] = path

    for section_index, section in enumerate(structure.sections):
        section_path: list[str | int] = ["output_structure", "sections", section_index]
        register("doc_section", section.section_id, section_path)
        for element_index, element in enumerate(section.elements):
            register(
                "doc_element",
                element.element_id,
                [*section_path, "elements", element_index],
            )

    for mapping_index, mapping in enumerate(mappings.values()):
        destination_key = (mapping.destination.target_type, mapping.destination.target_id)
        if destination_key not in declared:
            raise _plan_validation_error(
                "A DOCX content mapping destination must reference a declared section or element.",
                category="unknown_docx_destination",
                path=["content_mappings", mapping_index, "destination", "target_id"],
            )


def _plan_validation_error(
    message: str,
    *,
    category: str,
    path: list[str | int],
    accounting: bool = False,
) -> PlanValidationError:
    error_type = PlanAccountingError if accounting else PlanValidationError
    error = error_type(message)
    logger.warning(
        "transformation_plan_validation_failed",
        extra={
            "exception_class": type(error).__name__,
            "error_category": "plan_accounting" if accounting else "plan_validation",
            "validation_category": category,
            "validation_path": path,
            "validation_reason": message,
        },
    )
    return error
