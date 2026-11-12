"""Focused validation tests for provider-produced renderable artifact content."""

import json
import logging
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.documents import DocumentFormat
from app.models.artifacts import ArtifactMetric, ArtifactSection, ArtifactTable, ArtifactText, HTMLArtifactSection
from app.models.intermediate import DocumentIR, IRBlock, IRSection, ProvenanceRecord, SourceLocation, TableData
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
    SourceReference,
)
from app.models.llm import LLMCompletionResult, LLMTokenUsage
from app.models.transformation import (
    ContentMapping,
    DOCXOutputStructure,
    DOCXSectionPlan,
    PlanDestination,
    PlanSourceItem,
    PlanValidationRules,
    TransformationMetadata,
    TransformationPlan,
    TransformationProvenance,
)
from app.prompts.artifact import build_artifact_messages
from app.services.artifact_transformation import (
    InvalidArtifactContentError,
    _to_html_section,
    _parse_artifact_content,
    validate_artifact_references,
)
from app.services.interpretation import UnresolvedSourceReferenceError
from app.storage.interpretations import InterpretationStore


def _planned_render_inputs(item_count: int = 24):
    document_id = "00000000-0000-4000-8000-000000000301"
    interpretation_id = UUID("00000000-0000-4000-8000-000000000302")
    section_id = "financial-section"
    blocks = []
    facts = []
    metrics = []
    for index in range(item_count):
        block_id = f"financial-source-{index}"
        period = f"Q{index % 4 + 1} 2026"
        amount = str((index + 1) * 1000)
        location = SourceLocation(section_path=["Financial results"], paragraph_index=index + 1)
        source_text = "Reported revenue was $" + amount + " in " + period + ". " * 4
        blocks.append(IRBlock(id=block_id, kind="text", text=source_text, source=location))
        reference = SourceReference(block_id=block_id, section_id=section_id, source_location=location)
        facts.append(InterpretationFact(
            statement="Revenue was $" + amount + " in " + period + ".",
            source_references=[reference],
            confidence=0.99,
            evidence_type="explicit",
        ))
        metrics.append(InterpretationMetric(
            name="Revenue " + period,
            value=(index + 1) * 1000,
            currency="$",
            reporting_period=period,
            source_references=[reference],
            confidence=0.99,
            evidence_type="explicit",
        ))

    section = IRSection(
        id=section_id,
        title="Financial results",
        source=SourceLocation(section_path=["Financial results"]),
        blocks=blocks,
    )
    formula = IRBlock(
        id="formula-source",
        kind="formula",
        text="=SUM(B2:B3)",
        source=SourceLocation(sheet_name="Raw data", cell_range="B4"),
    )
    table = IRBlock(
        id="table-source",
        kind="table",
        source=SourceLocation(sheet_name="Raw data", cell_range="A1:B3"),
        table=TableData(headers=["Period", "Revenue"], rows=[["Q3 2026", "$24,000"]]),
    )
    ir = DocumentIR(
        document_id=document_id,
        source_format=DocumentFormat.HTML,
        filename="financial-report.html",
        title="Financial Report",
        metadata={"author": "Finance", "reporting_basis": "FY2026"},
        sections=[section],
        blocks=[formula, table],
        provenance=[ProvenanceRecord(
            extractor="html_reader",
            source_format=DocumentFormat.HTML,
            details={"encoding": "utf-8", "source_document": "uploaded document"},
        )],
        warnings=["Source contains a referenced formula and table."],
    )
    source_fingerprint = InterpretationStore.fingerprint(ir.model_dump(mode="json"))
    auxiliary_reference = facts[0].source_references[0]
    interpretation = DocumentInterpretation(
        interpretation_id=interpretation_id,
        document_id=document_id,
        summary="The report presents quarterly revenue figures for 2026.",
        facts=facts,
        metrics=metrics,
        entities=[InterpretationEntity(
            entity_id="entity-company",
            name="Example Company",
            entity_type="organization",
            attributes={"reporting_basis": "FY2026"},
            source_references=[auxiliary_reference],
            confidence=0.95,
        )],
        claims=[InterpretationClaim(
            statement="Revenue is reported quarterly.",
            claim_type="reporting_frequency",
            source_references=[auxiliary_reference],
            confidence=0.96,
            evidence_type="explicit",
        )],
        relationships=[InterpretationRelationship(
            source_entity_id="entity-company",
            target_entity_id="entity-company",
            relationship_type="reports",
            source_references=[auxiliary_reference],
            confidence=0.8,
        )],
        insights=[InterpretationInsight(
            observation="Quarterly values are available for comparison.",
            reasoning="The source reports multiple quarters.",
            supporting_source_references=[auxiliary_reference],
            confidence=0.9,
            evidence_type="inferred",
        )],
        warnings=["Quarter labels are explicit in the source."],
        provenance=InterpretationProvenance(
            provider="groq",
            model="openai/gpt-oss-120b",
            prompt_version="interpretation_v3",
            is_mock=False,
            source_provenance=ir.provenance,
            token_usage=LLMTokenUsage(prompt_tokens=1200, completion_tokens=600, total_tokens=1800),
        ),
        metadata=InterpretationMetadata(
            source_format=ir.source_format,
            source_ir_fingerprint=source_fingerprint,
            instruction_fingerprint="1" * 64,
            input_fingerprint="2" * 64,
        ),
    )

    mappings = []
    required_items = []
    for item_type, items in (("fact", facts), ("metric", metrics)):
        for index, item in enumerate(items):
            item_id = item_type + "-" + str(index + 1)
            mapping_id = "mapping-" + item_type + "-" + str(index)
            mappings.append(ContentMapping(
                mapping_id=mapping_id,
                source_item_type=item_type,
                source_item_id=item_id,
                destination=PlanDestination(target_type="doc_section", target_id="doc-financial"),
                operation="preserve",
                formatting_guidance="Preserve the amount, currency, quarter, and year.",
                source_references=item.source_references,
            ))
            required_items.append(PlanSourceItem(source_item_type=item_type, source_item_id=item_id))
    plan = TransformationPlan(
        plan_id=UUID("00000000-0000-4000-8000-000000000303"),
        document_id=document_id,
        interpretation_id=interpretation_id,
        schema_version="2.0",
        target_format=DocumentFormat.DOCX,
        user_instructions="Make the quarterly figures easy to compare.",
        output_structure=DOCXOutputStructure(
            target_format="docx",
            document_title="Quarterly Revenue Report",
            sections=[DOCXSectionPlan(
                section_id="doc-financial",
                title="Quarterly revenue",
                heading_level=1,
                purpose="Report each source-backed quarterly revenue value.",
            )],
        ),
        content_mappings=mappings,
        generation_instructions=["Use a readable table for the quarterly values."],
        preservation_rules=["Preserve every amount, currency, quarter, and year exactly."],
        validation_rules=PlanValidationRules(
            validation_status="ready",
            target_format=DocumentFormat.DOCX,
            required_content_items=required_items,
        ),
        provenance=TransformationProvenance(
            provider="groq",
            model="openai/gpt-oss-120b",
            prompt_version="transformation_v3",
            is_mock=False,
            token_usage=LLMTokenUsage(prompt_tokens=2000, completion_tokens=800, total_tokens=2800),
        ),
        metadata=TransformationMetadata(
            source_ir_fingerprint=source_fingerprint,
            interpretation_fingerprint="3" * 64,
            instruction_fingerprint="4" * 64,
            input_fingerprint="5" * 64,
        ),
        warnings=["All interpreted semantic items are mapped."],
    )
    return ir, interpretation, plan


def _valid_docx_payload() -> dict[str, object]:
    return {
        "target_format": "docx",
        "document_title": "Quarterly Report",
        "sections": [{
            "heading": "Revenue",
            "paragraphs": [{
                "text": "Revenue was $500,000 in Q3 2026.",
                "source_references": [{
                    "block_id": "block-1",
                    "section_id": "section-1",
                    "source_location": {"section_path": ["Financial Update"]},
                }],
            }],
            "bullet_points": [],
            "metrics": [],
            "tables": [],
        }],
    }


def test_planned_docx_prompt_compacts_duplicate_context_without_losing_content_or_provenance():
    ir, interpretation, plan = _planned_render_inputs()
    instructions = "Make the report easy to compare by quarter."
    messages = build_artifact_messages(ir, interpretation, DocumentFormat.DOCX, instructions, plan)
    compact_user = json.loads(messages[1].content)

    legacy_user = {
        "target_format": DocumentFormat.DOCX.value,
        "target_guidance": compact_user["target_guidance"],
        "user_instructions": instructions,
        "document_ir_untrusted_data": ir.model_dump(mode="json"),
        "interpretation_untrusted_data": interpretation.model_dump(mode="json"),
        "transformation_plan_untrusted_data": plan.model_dump(mode="json"),
    }
    legacy_messages = [
        messages[0],
        messages[1].model_copy(update={
            "content": json.dumps(legacy_user, ensure_ascii=False, sort_keys=True),
        }),
    ]

    def wire_size(request_messages) -> int:
        body = {
            "model": "openai/gpt-oss-120b",
            "messages": [message.model_dump(mode="json") for message in request_messages],
            "max_completion_tokens": 8192,
            "reasoning_effort": "low",
        }
        return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    compact_size = wire_size(messages)
    legacy_size = wire_size(legacy_messages)
    assert compact_size < legacy_size * 0.85
    assert len(compact_user["interpretation_untrusted_data"]["facts"]) == len(interpretation.facts)
    assert len(compact_user["interpretation_untrusted_data"]["metrics"]) == len(interpretation.metrics)
    for category in ("entities", "claims", "relationships", "insights"):
        assert compact_user["interpretation_untrusted_data"][category] == [
            item.model_dump(mode="json", exclude_none=True)
            for item in getattr(interpretation, category)
        ]
    assert compact_user["interpretation_untrusted_data"]["warnings"] == interpretation.warnings
    assert compact_user["user_instructions"] == instructions
    assert compact_user["transformation_plan_untrusted_data"]["user_instructions"] == plan.user_instructions
    assert compact_user["transformation_plan_untrusted_data"]["output_structure"] == plan.output_structure.model_dump(
        mode="json", exclude_none=True
    )
    compact_mappings = compact_user["transformation_plan_untrusted_data"]["content_mappings"]
    assert len(compact_mappings) == len(plan.content_mappings)
    assert compact_mappings[0]["source_item_id"] == plan.content_mappings[0].source_item_id
    assert compact_mappings[0]["destination"] == {"target_type": "doc_section", "target_id": "doc-financial"}
    assert "mapping_ids" not in compact_user["transformation_plan_untrusted_data"]["output_structure"]["sections"][0]
    assert "source_references" not in compact_mappings[0]
    assert compact_user["transformation_plan_untrusted_data"]["provenance"]["prompt_version"] == "transformation_v3"
    assert compact_user["transformation_plan_untrusted_data"]["metadata"] == plan.metadata.model_dump(mode="json")
    assert compact_user["transformation_plan_untrusted_data"]["required_content_items"] == [
        item.model_dump(mode="json", exclude_none=True)
        for item in plan.validation_rules.required_content_items
    ]

    compact_ir = compact_user["document_ir_untrusted_data"]
    assert compact_ir["provenance"] == [item.model_dump(mode="json", exclude_none=True) for item in ir.provenance]
    assert compact_ir["metadata"] == ir.metadata
    source_blocks = compact_ir["sections"][0]["blocks"]
    assert len(source_blocks) == len(interpretation.facts)
    assert source_blocks[0]["id"] == interpretation.facts[0].source_references[0].block_id
    assert source_blocks[0]["source"] == interpretation.facts[0].source_references[0].source_location.model_dump(
        mode="json", exclude_none=True
    )
    assert "text" not in source_blocks[0]
    assert compact_ir["blocks"][0]["text"] == "=SUM(B2:B3)"
    assert compact_ir["blocks"][1]["table"] == ir.blocks[1].table.model_dump(mode="json", exclude_none=True)

    compact_interpretation = compact_user["interpretation_untrusted_data"]
    for compact_fact, source_fact in zip(compact_interpretation["facts"], interpretation.facts):
        assert compact_fact["statement"] == source_fact.statement
        assert compact_fact["source_references"] == [
            reference.model_dump(mode="json", exclude_none=True)
            for reference in source_fact.source_references
        ]
    assert compact_interpretation["provenance"]["provider"] == interpretation.provenance.provider
    assert compact_interpretation["provenance"]["model"] == interpretation.provenance.model
    assert compact_interpretation["provenance"]["source_provenance_ref"] == "document_ir_untrusted_data.provenance"
    assert compact_interpretation["metadata"] == interpretation.metadata.model_dump(mode="json", exclude_none=True)
    assert "JSON Schema" in messages[0].content
    assert "PPTXOutputStructure" not in messages[0].content


def test_standalone_transform_prompt_keeps_existing_full_payload_contract():
    ir, interpretation, _ = _planned_render_inputs(item_count=1)
    messages = build_artifact_messages(ir, interpretation, DocumentFormat.DOCX, "Standalone instructions.")
    body = json.loads(messages[1].content)

    assert body["document_ir_untrusted_data"] == ir.model_dump(mode="json")
    assert body["interpretation_untrusted_data"] == interpretation.model_dump(mode="json")
    assert body["transformation_plan_untrusted_data"] is None
    assert messages[0].content.startswith("You are generating structured content for a real document artifact.")


def test_artifact_parser_accepts_valid_groq_style_json():
    parsed = _parse_artifact_content(
        json.dumps(_valid_docx_payload()), DocumentFormat.DOCX
    )

    assert parsed.document_title == "Quarterly Report"
    assert parsed.sections[0].paragraphs[0].text == "Revenue was $500,000 in Q3 2026."


def test_artifact_parser_accepts_one_complete_markdown_json_fence():
    content = "```json\n" + json.dumps(_valid_docx_payload()) + "\n```"

    parsed = _parse_artifact_content(content, DocumentFormat.DOCX)

    assert parsed.document_title == "Quarterly Report"


def _nested_section_id_docx_fixture(section_id: str = "section-financial"):
    def reference(block_id: str, element_index: int) -> dict:
        return {
            "block_id": block_id,
            "source_location": {
                "section_id": section_id,
                "section_path": ["Financial Update"],
                "element_index": element_index,
            },
        }

    location_specs = [
        ("paragraph-1", 1),
        ("bullet-1", 2),
        ("table-1", 3),
    ]
    ir = DocumentIR(
        document_id="00000000-0000-4000-8000-000000000401",
        source_format=DocumentFormat.HTML,
        filename="financial.html",
        title="Financial Update",
        sections=[IRSection(
            id="section-financial",
            title="Financial Update",
            source=SourceLocation(section_path=["Financial Update"]),
            blocks=[
                IRBlock(
                    id=block_id,
                    kind="text",
                    text="Source-backed content.",
                    source=SourceLocation(section_path=["Financial Update"], element_index=element_index),
                )
                for block_id, element_index in location_specs
            ],
        )],
        provenance=[ProvenanceRecord(extractor="html_reader", source_format=DocumentFormat.HTML)],
    )
    payload = {
        "target_format": "docx",
        "document_title": "Financial Update",
        "sections": [{
            "heading": "Financial Update",
            "paragraphs": [{
                "text": "Revenue increased.",
                "source_references": [reference("paragraph-1", 1)],
            }],
            "bullet_points": [{
                "text": "Reported result",
                "source_references": [reference("bullet-1", 2)],
            }],
            "tables": [{
                "headers": ["Metric", "Value"],
                "rows": [["Revenue", "1200"]],
                "source_references": [reference("table-1", 3)],
            }],
        }],
    }
    return payload, ir


def test_artifact_source_references_lift_nested_section_id_and_resolve_for_all_content_types(caplog):
    payload, ir = _nested_section_id_docx_fixture()

    with caplog.at_level(logging.INFO, logger="app.services.artifact_transformation"):
        parsed = _parse_artifact_content(json.dumps(payload), DocumentFormat.DOCX)

    validate_artifact_references(parsed, ir)
    section = parsed.sections[0]
    references = [
        section.paragraphs[0].source_references[0],
        section.bullet_points[0].source_references[0],
        section.tables[0].source_references[0],
    ]
    assert [reference.section_id for reference in references] == ["section-financial"] * 3
    assert [reference.block_id for reference in references] == ["paragraph-1", "bullet-1", "table-1"]
    record = next(item for item in caplog.records if item.message == "artifact_section_reference_normalized")
    assert record.normalized_section_reference_count == 3


def test_nested_section_id_that_does_not_resolve_is_rejected():
    payload, ir = _nested_section_id_docx_fixture(section_id="invented-section")
    parsed = _parse_artifact_content(json.dumps(payload), DocumentFormat.DOCX)

    with pytest.raises(UnresolvedSourceReferenceError):
        validate_artifact_references(parsed, ir)


def test_unsupported_source_location_fields_remain_rejected():
    payload, _ = _nested_section_id_docx_fixture()
    payload["sections"][0]["paragraphs"][0]["source_references"][0]["source_location"]["unsupported"] = "value"

    with pytest.raises(InvalidArtifactContentError) as error:
        _parse_artifact_content(json.dumps(payload), DocumentFormat.DOCX)

    assert isinstance(error.value.__cause__, ValidationError)


def test_docx_parser_preserves_heading_only_section_and_normalizes_scalar_table_cells(caplog):
    payload = {
        "target_format": "docx",
        "document_title": "Quarterly Report",
        "sections": [
            {"heading": "Executive summary"},
            {
                "heading": "Financial results",
                "tables": [{
                    "caption": "Quarterly values",
                    "headers": ["Metric", "Q1", "Q2", "Q3", "Q4"],
                    "rows": [
                        ["Revenue", "10", "20", "30", "40"],
                        ["Net income", "1", "2", "3", 40],
                    ],
                    "source_references": [{
                        "block_id": "block-1",
                        "section_id": "section-1",
                        "source_location": {"section_path": ["Financial Update"]},
                    }],
                }],
            },
        ],
    }

    with caplog.at_level(logging.INFO, logger="app.services.artifact_transformation"):
        parsed = _parse_artifact_content(json.dumps(payload), DocumentFormat.DOCX)

    assert [section.heading for section in parsed.sections] == ["Executive summary", "Financial results"]
    assert parsed.sections[0].paragraphs == []
    assert parsed.sections[1].tables[0].rows[1] == ["Net income", "1", "2", "3", "40"]
    record = next(item for item in caplog.records if item.message == "artifact_table_cells_normalized")
    assert record.normalized_table_cell_count == 1


def test_docx_parser_rejects_ambiguous_object_table_cell_without_dropping_content(caplog):
    payload = {
        "target_format": "docx",
        "document_title": "Quarterly Report",
        "sections": [{
            "heading": "Financial results",
            "tables": [{
                "headers": ["Metric", "Q1"],
                "rows": [["Revenue", {"amount": 40}]],
                "source_references": [{
                    "block_id": "block-1",
                    "section_id": "section-1",
                    "source_location": {"section_path": ["Financial Update"]},
                }],
            }],
        }],
    }

    with caplog.at_level(logging.ERROR, logger="app.services.artifact_transformation"):
        with pytest.raises(InvalidArtifactContentError) as error:
            _parse_artifact_content(json.dumps(payload), DocumentFormat.DOCX)

    assert isinstance(error.value.__cause__, ValidationError)
    record = next(item for item in caplog.records if item.message == "artifact_content_validation_failed")
    assert record.json_parsing_succeeded is True
    assert any(
        item["location"] == ["sections", 0, "tables", 0, "rows", 0, 1]
        and item["type"] == "string_type"
        for item in record.pydantic_errors
    )


def test_mock_html_section_conversion_preserves_all_content_and_citations():
    reference = SourceReference.model_validate({
        "block_id": "block-1",
        "section_id": "section-1",
        "source_location": {"section_path": ["Financial Update"]},
    })
    section = ArtifactSection(
        heading="Financial results",
        paragraphs=[ArtifactText(text="Revenue increased.", source_references=[reference])],
        bullet_points=[ArtifactText(text="Q3 result", source_references=[reference])],
        metrics=[ArtifactMetric(
            name="Revenue",
            value=1200,
            currency="$",
            reporting_period="Q3 2026",
            source_references=[reference],
        )],
        tables=[ArtifactTable(
            caption="Revenue by quarter",
            headers=["Quarter", "Revenue"],
            rows=[["Q3 2026", "$1,200"]],
            source_references=[reference],
        )],
    )

    converted = _to_html_section(section)

    assert isinstance(converted, HTMLArtifactSection)
    assert converted.model_dump(mode="python") == section.model_dump(mode="python")
    assert converted.paragraphs[0].source_references[0] == reference
    assert converted.bullet_points[0].source_references[0] == reference
    assert converted.metrics[0].source_references[0] == reference
    assert converted.tables[0].source_references[0] == reference


def test_mock_html_section_conversion_does_not_weaken_nonempty_validation():
    with pytest.raises(ValidationError):
        _to_html_section(ArtifactSection(heading="Empty section"))


def test_artifact_parser_does_not_accept_prose_around_json_fence():
    content = "Here is the report:\n```json\n" + json.dumps(_valid_docx_payload()) + "\n```"

    with pytest.raises(InvalidArtifactContentError) as error:
        _parse_artifact_content(content, DocumentFormat.DOCX)

    assert isinstance(error.value.__cause__, ValidationError)


def test_artifact_schema_failure_logs_sanitized_diagnostics(caplog):
    payload = _valid_docx_payload()
    payload["sections"][0]["paragraphs"][0]["text"] = "PRIVATE_SENTINEL_CONTENT"
    payload["sections"][0]["paragraphs"][0].pop("source_references")
    usage = LLMTokenUsage(prompt_tokens=3482, completion_tokens=2600, total_tokens=6082)

    with caplog.at_level(logging.ERROR, logger="app.services.artifact_transformation"):
        with pytest.raises(InvalidArtifactContentError):
            _parse_artifact_content(
                json.dumps(payload),
                DocumentFormat.DOCX,
                finish_reason="stop",
                usage=usage,
            )

    record = next(item for item in caplog.records if item.message == "artifact_content_validation_failed")
    assert record.failure_phase == "artifact_schema_validation"
    assert record.target_format == "docx"
    assert record.schema_model == "DOCXArtifactContent"
    assert record.prompt_version == "artifact_v7"
    assert record.artifact_schema_version == "1.1"
    assert record.json_parsing_succeeded is True
    assert record.content_empty is False
    assert record.contains_markdown_code_fence is False
    assert record.finish_reason == "stop"
    assert (record.prompt_tokens, record.completion_tokens, record.total_tokens) == (3482, 2600, 6082)
    assert any("source_references" in error["location"] for error in record.pydantic_errors)
    assert any(error["category"] == "missing_field" for error in record.pydantic_errors)
    assert "PRIVATE_SENTINEL_CONTENT" not in caplog.text


def test_artifact_type_error_returns_sanitized_structured_diagnostics(caplog):
    payload = _valid_docx_payload()
    payload["document_title"] = {"private": "must not be echoed"}
    with caplog.at_level(logging.ERROR, logger="app.services.artifact_transformation"):
        with pytest.raises(InvalidArtifactContentError) as error:
            _parse_artifact_content(json.dumps(payload), DocumentFormat.DOCX)

    details = error.value.diagnostics
    assert details is not None
    assert details["target_format"] == "docx"
    assert details["schema_model"] == "DOCXArtifactContent"
    assert details["error_category"] == "schema_validation"
    assert any(
        item["field_path"] == ["document_title"]
        and item["category"] == "incorrect_type"
        for item in details["validation_errors"]
    )
    assert "must not be echoed" not in caplog.text


def test_artifact_invalid_json_logs_parse_failure_without_response_content(caplog):
    content = '{"secret":"PRIVATE_SENTINEL_CONTENT"'

    with caplog.at_level(logging.ERROR, logger="app.services.artifact_transformation"):
        with pytest.raises(InvalidArtifactContentError):
            _parse_artifact_content(content, DocumentFormat.DOCX)

    record = next(item for item in caplog.records if item.message == "artifact_content_validation_failed")
    assert record.failure_phase == "artifact_json_parsing"
    assert record.json_parsing_failed is True
    assert record.pydantic_errors
    assert "PRIVATE_SENTINEL_CONTENT" not in caplog.text
