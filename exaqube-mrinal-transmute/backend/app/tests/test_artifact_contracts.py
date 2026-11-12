"""Cross-format checks for registered artifact schemas, prompts and native writers."""

import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.artifacts import ARTIFACT_SCHEMA_VERSION
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR, IRBlock, IRSection, ProvenanceRecord, SourceLocation
from app.models.interpretation import (
    DocumentInterpretation,
    InterpretationMetadata,
    InterpretationProvenance,
    SourceReference,
)
from app.orchestration.engine import WorkflowExecutor
from app.prompts.artifact import ARTIFACT_PROMPT_VERSION, build_artifact_messages
from app.services.artifact_contracts import (
    ARTIFACT_CONTRACTS,
    ArtifactContractConfigurationError,
    get_artifact_contract,
    validate_artifact_contract,
)
from app.services.artifact_transformation import (
    ArtifactTransformationService,
    validate_artifact_references,
)


SOURCE_BLOCK_ID = "ir-block-financial-1"
SOURCE_REFERENCE = {
    "block_id": SOURCE_BLOCK_ID,
    "section_id": "ir-section-financial",
    "source_location": {"section_path": ["Financial"], "element_index": 0},
}


def _source_inputs():
    source_format = DocumentFormat.HTML
    provenance = ProvenanceRecord(extractor="html_reader", source_format=source_format)
    block = IRBlock(
        id=SOURCE_BLOCK_ID,
        kind="text",
        text="Revenue was $12 million in Q3 2026.",
        source=SourceLocation(section_path=["Financial"], element_index=0),
    )
    document_ir = DocumentIR(
        document_id="00000000-0000-4000-8000-000000000801",
        source_format=source_format,
        filename="financial.html",
        title="Financial Update",
        sections=[IRSection(
            id="ir-section-financial",
            title="Financial",
            source=SourceLocation(section_path=["Financial"]),
            blocks=[block],
        )],
        provenance=[provenance],
    )
    interpretation = DocumentInterpretation(
        interpretation_id=uuid4(),
        document_id=document_ir.document_id,
        summary="Revenue was $12 million in Q3 2026.",
        provenance=InterpretationProvenance(
            provider="test",
            model="test-model",
            prompt_version="interpretation_test",
            is_mock=True,
            source_provenance=[provenance],
        ),
        metadata=InterpretationMetadata(
            source_format=source_format,
            source_ir_fingerprint="a" * 64,
            instruction_fingerprint="b" * 64,
            input_fingerprint="c" * 64,
        ),
    )
    return document_ir, interpretation


def _valid_response(target_format: DocumentFormat) -> dict[str, object]:
    text = {
        "text": "Revenue was $12 million in Q3 2026.",
        "source_references": [SOURCE_REFERENCE],
    }
    if target_format == DocumentFormat.HTML:
        return {
            "target_format": "html",
            "page_title": "Financial Update",
            "sections": [{"heading": "Revenue", "paragraphs": [text]}],
        }
    if target_format == DocumentFormat.DOCX:
        return {
            "target_format": "docx",
            "document_title": "Financial Update",
            "sections": [{"heading": "Revenue", "paragraphs": [text]}],
        }
    if target_format == DocumentFormat.PPTX:
        return {
            "target_format": "pptx",
            "presentation_title": "Financial Update",
            "slides": [{
                "slide_id": "slide-revenue",
                "title": "Revenue",
                "purpose": "Present the reported quarterly revenue.",
                "visual_guidance": "Emphasize the reported amount.",
                "title_source_references": [SOURCE_REFERENCE],
                "elements": [{
                    "element_id": "element-revenue",
                    "element_type": "paragraph",
                    "mapping_ids": ["mapping-revenue"],
                    "content": text,
                }],
            }],
        }
    raise AssertionError(f"Unexpected registered format: {target_format}")


@pytest.mark.parametrize("target_format", list(ARTIFACT_CONTRACTS))
def test_registered_artifact_contract_schema_prompt_references_and_writer(target_format):
    contract = get_artifact_contract(target_format)
    document_ir, interpretation = _source_inputs()
    messages = build_artifact_messages(document_ir, interpretation, target_format)
    serialized_schema = json.dumps(contract.schema_model.model_json_schema(), ensure_ascii=False, sort_keys=True)

    assert contract.schema_version == ARTIFACT_SCHEMA_VERSION
    assert ARTIFACT_PROMPT_VERSION.startswith("artifact_v")
    assert contract.schema_model.__name__ in messages[0].content
    assert f"Artifact schema version: {contract.schema_version}" in messages[0].content
    assert serialized_schema in messages[0].content
    assert "return only declared properties" in messages[0].content
    assert "include all required fields" in messages[0].content
    assert "use the exact declared types and allowed enum values" in messages[0].content
    assert "do not add properties" in messages[0].content

    response = _valid_response(target_format)
    artifact = contract.schema_model.model_validate(response)
    validate_artifact_references(artifact, document_ir)
    rendered = contract.writer(artifact, False, {"document_id": document_ir.document_id})
    contract.output_validator(rendered)


@pytest.mark.parametrize("target_format", list(ARTIFACT_CONTRACTS))
def test_registered_artifact_contract_requires_target_and_rejects_unknown_properties(target_format):
    contract = get_artifact_contract(target_format)
    response = _valid_response(target_format)

    missing_required = dict(response)
    del missing_required["target_format"]
    with pytest.raises(ValidationError):
        contract.schema_model.model_validate(missing_required)

    invalid_enum = _valid_response(target_format)
    invalid_enum["target_format"] = "pdf"
    with pytest.raises(ValidationError):
        contract.schema_model.model_validate(invalid_enum)

    invalid_type = _valid_response(target_format)
    title_key = {
        DocumentFormat.HTML: "page_title",
        DocumentFormat.DOCX: "document_title",
        DocumentFormat.PPTX: "presentation_title",
    }[target_format]
    invalid_type[title_key] = {"not": "a string"}
    with pytest.raises(ValidationError):
        contract.schema_model.model_validate(invalid_type)

    with_undeclared_property = dict(response)
    with_undeclared_property["undeclared_contract_field"] = "must be rejected"
    with pytest.raises(ValidationError):
        contract.schema_model.model_validate(with_undeclared_property)

    nested_undeclared = _valid_response(target_format)
    nested_key = {
        DocumentFormat.HTML: "sections",
        DocumentFormat.DOCX: "sections",
        DocumentFormat.PPTX: "slides",
    }[target_format]
    nested_items = nested_undeclared[nested_key]
    assert isinstance(nested_items, list) and isinstance(nested_items[0], dict)
    nested_items[0]["undeclared_nested_field"] = "must be rejected"
    with pytest.raises(ValidationError):
        contract.schema_model.model_validate(nested_undeclared)


@pytest.mark.parametrize("target_format", [DocumentFormat.XLSX, DocumentFormat.MMD])
def test_unimplemented_targets_fail_contract_preflight_before_provider_request(tmp_path, target_format):
    class NeverCalledLLM:
        settings = SimpleNamespace(mock_llm=False)

        async def complete(self, messages):
            raise AssertionError("Provider must not be called for an unregistered target contract.")

    service = ArtifactTransformationService(NeverCalledLLM(), tmp_path)
    with pytest.raises(ArtifactContractConfigurationError):
        asyncio.run(service.transform(None, None, target_format, run_id=uuid4()))


@pytest.mark.parametrize(
    "changes",
    [
        {"writer": None},
        {"standalone_guidance": ""},
        {"planned_guidance": ""},
    ],
)
def test_contract_preflight_rejects_missing_writer_or_prompt_registration(changes):
    contract = get_artifact_contract(DocumentFormat.PPTX)
    with pytest.raises(ArtifactContractConfigurationError):
        validate_artifact_contract(replace(contract, **changes))


def test_workflow_maps_contract_preflight_failure_to_safe_structured_status():
    error = ArtifactContractConfigurationError(DocumentFormat.MMD, "internal registration detail")
    assert WorkflowExecutor._safe_error(error) == (
        "artifact_contract_unavailable",
        "Artifact generation is not configured for this target format.",
    )

