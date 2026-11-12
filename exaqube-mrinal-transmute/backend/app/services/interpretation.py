"""Semantic interpretation of DocumentIR into a separate persisted object."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4
from dataclasses import dataclass

from pydantic import ValidationError

from app.models.intermediate import DocumentIR, IRBlock, IRSection, SourceLocation
from app.models.llm import LLMTokenUsage
from app.models.interpretation import (
    DocumentInterpretation,
    InterpretationClaim,
    InterpretationEntity,
    InterpretationFact,
    InterpretationInsight,
    InterpretationMetadata,
    InterpretationMetric,
    InterpretationProvenance,
    InterpretationRelationship,
    SemanticInterpretation,
    SourceReference,
)
from app.prompts.interpretation import PROMPT_VERSION, build_interpretation_messages
from app.services.llm import LLMService
from app.storage.interpretations import InterpretationStore

logger = logging.getLogger(__name__)
MOCK_INTERPRETATION_WARNING = "MOCK_LLM is enabled; no semantic interpretation was performed."
MOCK_INTERPRETATION_SUMMARY = "Mock mode: no semantic interpretation was performed."
_INTERPRETATION_FIELDS = {
    "summary", "facts", "metrics", "entities", "claims", "relationships", "insights", "warnings",
    "statement", "source_references", "confidence", "evidence_type", "name", "value", "unit",
    "currency", "reporting_period", "description", "entity_id", "entity_type", "attributes",
    "claim_type", "source_entity_id", "target_entity_id", "relationship_type", "observation",
    "reasoning", "supporting_source_references", "block_id", "section_id", "source_location",
}


@dataclass(frozen=True)
class StoredInterpretation:
    interpretation: DocumentInterpretation
    reused: bool


class InterpretationError(RuntimeError):
    """Base class for safe interpretation-stage errors."""


class InvalidInterpretationResponseError(InterpretationError):
    """The provider response could not be parsed as the semantic schema."""


class UnresolvedSourceReferenceError(InterpretationError):
    """A model-generated citation did not resolve to the supplied source IR."""


class InterpretationService:
    def __init__(self, llm_service: LLMService, storage_root: Path) -> None:
        self.llm_service = llm_service
        self.store = InterpretationStore(storage_root)
        self._fingerprint_locks: dict[str, asyncio.Lock] = {}

    async def interpret(
        self,
        document_ir: DocumentIR,
        user_instructions: str | None = None,
        *,
        max_completion_tokens: int | None = None,
    ) -> DocumentInterpretation:
        """Interpret and persist IR without modifying the source representation."""
        result = await self.interpret_with_status(
            document_ir,
            user_instructions,
            max_completion_tokens=max_completion_tokens,
        )
        return result.interpretation

    async def interpret_with_status(
        self,
        document_ir: DocumentIR,
        user_instructions: str | None = None,
        *,
        idempotency_key: str | None = None,
        max_completion_tokens: int | None = None,
    ) -> StoredInterpretation:
        """Interpret once per input fingerprint and report whether storage was reused."""
        source_fingerprint = self.store.fingerprint(document_ir.model_dump(mode="json"))
        instruction_fingerprint = hashlib.sha256((user_instructions or "").encode("utf-8")).hexdigest()
        identity = self._provider_identity()
        fingerprint_payload = {
            "source_ir_fingerprint": source_fingerprint,
            "instructions": user_instructions,
            "prompt_version": PROMPT_VERSION,
            "provider_identity": identity,
        }
        if max_completion_tokens is not None:
            fingerprint_payload["max_completion_tokens"] = max_completion_tokens
        input_fingerprint = self.store.fingerprint(fingerprint_payload)

        if idempotency_key is not None:
            await asyncio.to_thread(
                self.store.bind_idempotency_key, document_ir.document_id, idempotency_key, input_fingerprint
            )
        lock = self._fingerprint_locks.setdefault(input_fingerprint, asyncio.Lock())
        async with lock:
            cached = await asyncio.to_thread(self.store.get, document_ir.document_id, input_fingerprint)
            if cached is not None:
                logger.info("document_interpretation_reused", extra={"node_id": document_ir.document_id})
                return StoredInterpretation(cached, True)

            messages = build_interpretation_messages(document_ir, user_instructions)
            if max_completion_tokens is None:
                completion = await self.llm_service.complete(messages)
            else:
                completion = await self.llm_service.complete(
                    messages,
                    max_completion_tokens=max_completion_tokens,
                )
            phase = "semantic_validation"
            try:
                if completion.is_mock:
                    semantic = self._mock_semantic_result()
                else:
                    semantic = self._parse_semantic_result(completion.content)
                    phase = "source_reference_validation"
                    validate_source_references(semantic, document_ir)

                phase = "interpretation_model_validation"
                interpretation = DocumentInterpretation(
                    interpretation_id=uuid4(),
                    document_id=document_ir.document_id,
                    summary=semantic.summary,
                    facts=semantic.facts,
                    metrics=semantic.metrics,
                    entities=semantic.entities,
                    claims=semantic.claims,
                    relationships=semantic.relationships,
                    insights=semantic.insights,
                    warnings=[*document_ir.warnings, *semantic.warnings],
                    provenance=InterpretationProvenance(
                        provider=completion.provider,
                        model=completion.model,
                        prompt_version=PROMPT_VERSION,
                        created_at=datetime.now(timezone.utc),
                        is_mock=completion.is_mock,
                        source_provenance=document_ir.provenance,
                        token_usage=completion.usage,
                    ),
                    metadata=InterpretationMetadata(
                        source_format=document_ir.source_format,
                        source_ir_fingerprint=source_fingerprint,
                        instruction_fingerprint=instruction_fingerprint,
                        input_fingerprint=input_fingerprint,
                    ),
                )
                phase = "interpretation_persistence"
                saved = await asyncio.to_thread(self.store.save_if_absent, interpretation)
            except Exception as exc:
                _log_interpretation_failure(
                    exc,
                    phase=phase,
                    content=None if completion.is_mock else completion.content,
                    finish_reason=completion.finish_reason,
                    token_usage=completion.usage,
                )
                raise
            reused = saved.interpretation_id != interpretation.interpretation_id
            logger.info("document_interpretation_completed", extra={"node_id": document_ir.document_id})
            return StoredInterpretation(saved, reused)

    def _provider_identity(self) -> dict[str, str | bool]:
        settings = self.llm_service.settings
        if settings.mock_llm:
            return {"provider": "mock", "model": "mock", "is_mock": True}
        return {
            "provider": "openai-compatible",
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "is_mock": False,
        }

    @staticmethod
    def _parse_semantic_result(content: str) -> SemanticInterpretation:
        try:
            return SemanticInterpretation.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise InvalidInterpretationResponseError(
                "The LLM response did not match the required interpretation JSON schema."
            ) from exc

    @staticmethod
    def _mock_semantic_result() -> SemanticInterpretation:
        """Return an explicitly empty mock result, never synthetic document analysis."""
        return SemanticInterpretation(
            summary=MOCK_INTERPRETATION_SUMMARY,
            facts=[],
            metrics=[],
            entities=[],
            claims=[],
            relationships=[],
            insights=[],
            warnings=[MOCK_INTERPRETATION_WARNING],
        )


def _log_interpretation_failure(
    exc: Exception,
    *,
    phase: str,
    content: str | None,
    finish_reason: str | None,
    token_usage: LLMTokenUsage | None,
) -> None:
    cause = exc.__cause__
    validation_error = exc if isinstance(exc, ValidationError) else cause
    pydantic_errors = (
        validation_error.errors(include_url=False)
        if isinstance(validation_error, ValidationError) else []
    )
    json_parsing_succeeded: bool | None = None
    if isinstance(exc, InvalidInterpretationResponseError):
        json_parsing_succeeded = not any(
            error.get("type") == "json_invalid" for error in pydantic_errors
        ) and bool(pydantic_errors)
        error_category = "semantic_schema_validation" if json_parsing_succeeded else "semantic_json_parse"
    elif isinstance(exc, UnresolvedSourceReferenceError):
        error_category = "source_reference_validation"
        json_parsing_succeeded = True
    elif phase == "interpretation_model_validation":
        error_category = "interpretation_model_validation"
        json_parsing_succeeded = True
    elif phase == "interpretation_persistence":
        error_category = "interpretation_persistence"
        json_parsing_succeeded = True
    else:
        error_category = "interpretation_execution"

    usage_metadata = None
    if token_usage is not None:
        usage_metadata = {
            "prompt_tokens": token_usage.prompt_tokens,
            "completion_tokens": token_usage.completion_tokens,
            "total_tokens": token_usage.total_tokens,
        }
    content_empty = None if content is None else not content.strip()
    has_code_fence = None if content is None else "```" in content
    safe_errors = [
        {
            "location": [
                part if isinstance(part, int) else (
                    part if isinstance(part, str) and part in _INTERPRETATION_FIELDS
                    else "<unknown-field>"
                )
                for part in error.get("loc", ())
            ],
            "type": error.get("type", "unknown"),
        }
        for error in pydantic_errors
    ]
    try:
        setattr(exc, "operation_usage", token_usage)
        setattr(exc, "operation_error_category", error_category)
        setattr(exc, "persistence_failed", phase == "interpretation_persistence")
    except (AttributeError, TypeError):
        pass

    event = {
        "semantic_json_parse": "interpretation_response_validation_failed",
        "semantic_schema_validation": "interpretation_response_validation_failed",
        "source_reference_validation": "interpretation_source_reference_validation_failed",
        "interpretation_persistence": "interpretation_persistence_failed",
        "interpretation_model_validation": "interpretation_model_validation_failed",
    }.get(error_category, "interpretation_execution_failed")
    logger.error(
        event,
        extra={
            "exception_class": type(exc).__name__,
            "cause_exception_class": type(cause).__name__ if cause is not None else None,
            "error_category": error_category,
            "failure_phase": phase,
            "source_reference_failure_category": (
                "unresolvable_source_reference" if isinstance(exc, UnresolvedSourceReferenceError) else None
            ),
            "persistence_failed": phase == "interpretation_persistence",
            "json_parsing_succeeded": json_parsing_succeeded,
            "json_parsing_failed": (
                None if json_parsing_succeeded is None else not json_parsing_succeeded
            ),
            "pydantic_errors": safe_errors,
            "content_empty": content_empty,
            "contains_markdown_code_fence": has_code_fence,
            "finish_reason": finish_reason,
            "token_usage_present": token_usage is not None,
            "token_usage": usage_metadata,
        },
    )
def validate_source_references(semantic: SemanticInterpretation, document_ir: DocumentIR) -> None:
    """Reject every citation that cannot be resolved exactly against the source IR."""
    resolver = SourceReferenceResolver(document_ir)
    for item in _all_semantic_items(semantic):
        references = getattr(item, "source_references", None)
        if references is None:
            references = item.supporting_source_references
        for reference in references:
            resolver.validate(reference)


class SourceReferenceResolver:
    """Resolve one or more interpretation/plan citations against an immutable IR."""

    def __init__(self, document_ir: DocumentIR) -> None:
        self.block_index: dict[str, tuple[IRBlock, tuple[str, ...]]] = {}
        self.section_index: dict[str, IRSection] = {}

        def visit_section(section: IRSection, ancestors: tuple[str, ...]) -> None:
            self.section_index[section.id] = section
            section_ids = (*ancestors, section.id)
            for block in section.blocks:
                self.block_index[block.id] = (block, section_ids)
            for child in section.children:
                visit_section(child, section_ids)

        for section in document_ir.sections:
            visit_section(section, ())
        for block in document_ir.blocks:
            self.block_index[block.id] = (block, ())

    def validate(self, reference: SourceReference) -> None:
        _validate_one_reference(reference, self.block_index, self.section_index)


def _validate_one_reference(
    reference: SourceReference,
    blocks: dict[str, tuple[IRBlock, tuple[str, ...]]],
    sections: dict[str, IRSection],
) -> None:
    location = reference.source_location
    if not _has_source_coordinates(location):
        raise UnresolvedSourceReferenceError("A source reference must include a concrete IR source location.")

    if reference.block_id is not None:
        found = blocks.get(reference.block_id)
        if found is None:
            raise UnresolvedSourceReferenceError("A source reference names a block absent from the input IR.")
        block, ancestors = found
        if block.source != location:
            raise UnresolvedSourceReferenceError("A source reference location does not match its input IR block.")
        if reference.section_id is not None and reference.section_id not in ancestors:
            raise UnresolvedSourceReferenceError("A source reference section is not an ancestor of its input IR block.")
        return

    section = sections.get(reference.section_id or "")
    if section is None:
        raise UnresolvedSourceReferenceError("A source reference names a section absent from the input IR.")
    if section.source is None or section.source != location:
        raise UnresolvedSourceReferenceError("A source reference location does not match its input IR section.")


def _has_source_coordinates(location: SourceLocation) -> bool:
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


def _all_semantic_items(
    semantic: SemanticInterpretation,
) -> Iterable[
    InterpretationFact
    | InterpretationMetric
    | InterpretationEntity
    | InterpretationClaim
    | InterpretationRelationship
    | InterpretationInsight
]:
    yield from semantic.facts
    yield from semantic.metrics
    yield from semantic.entities
    yield from semantic.claims
    yield from semantic.relationships
    yield from semantic.insights
