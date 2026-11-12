"""Unit coverage for native editable PPTX rendering and validation."""

from io import BytesIO
import json
from uuid import uuid4

import pytest
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pydantic import ValidationError

from app.models.artifacts import (
    ArtifactMetric,
    ArtifactTable,
    ArtifactText,
    PPTXArtifactContent,
    PPTXBulletsElement,
    PPTXChartContent,
    PPTXChartElement,
    PPTXMetricElement,
    PPTXParagraphElement,
    PPTXTableElement,
    PPTXTitleElement,
)
from app.models.interpretation import SourceReference
from app.models.documents import DocumentFormat
from app.models.transformation import (
    PPTXElementPlan,
    PPTXOutputStructure,
    PPTXSlidePlan,
    ContentMapping,
    PlanDestination,
    PlanValidationRules,
    TransformationMetadata,
    TransformationPlan,
    TransformationProvenance,
)
from app.services.artifact_transformation import (
    InvalidArtifactContentError,
    UnsupportedArtifactElementError,
    _parse_artifact_content,
    _reject_unsupported_pptx_plan_elements,
    _validate_pptx_plan_alignment,
)
from app.services.pptx_writer import render_pptx, validate_pptx_output


def _reference(block_id: str = "block-revenue") -> SourceReference:
    return SourceReference.model_validate({
        "block_id": block_id,
        "section_id": "section-financial",
        "source_location": {"slide_number": 2, "section_path": ["Financial results"]},
    })


def _content() -> PPTXArtifactContent:
    reference = _reference()
    return PPTXArtifactContent(
        target_format="pptx",
        presentation_title="Quarterly Results",
        slides=[{
            "slide_id": "slide-results",
            "title": "Financial results",
            "mapping_ids": ["mapping-summary"],
            "elements": [
                PPTXTitleElement(
                    element_id="element-heading",
                    element_type="title",
                    content=ArtifactText(text="Revenue performance", source_references=[reference]),
                ),
                PPTXParagraphElement(
                    element_id="element-summary",
                    element_type="paragraph",
                    content=ArtifactText(text="Revenue increased in Q3.", source_references=[reference]),
                ),
                PPTXBulletsElement(
                    element_id="element-bullets",
                    element_type="bullets",
                    items=[ArtifactText(text="Q3 was the strongest quarter.", source_references=[reference])],
                ),
                PPTXMetricElement(
                    element_id="element-metric",
                    element_type="metric",
                    content=ArtifactMetric(
                        name="Revenue",
                        value=1200000,
                        currency="$",
                        reporting_period="Q3 2026",
                        source_references=[reference],
                    ),
                ),
                PPTXTableElement(
                    element_id="element-table",
                    element_type="table",
                    content=ArtifactTable(
                        caption="Revenue by quarter",
                        headers=["Quarter", "Revenue"],
                        rows=[["Q3 2026", "$1,200,000"]],
                        source_references=[reference],
                    ),
                ),
            ],
        }],
    )


def test_writer_creates_editable_native_pptx_with_citations_and_provenance():
    content = _content()
    output = render_pptx(
        content,
        is_mock=False,
        provenance={
            "document_id": "doc-123",
            "interpretation_id": "interp-456",
            "source_provenance": [{"extractor": "html_reader", "source_format": "html"}],
        },
    )

    validate_pptx_output(output)
    presentation = Presentation(BytesIO(output))
    assert len(presentation.slides) == 1
    slide = presentation.slides[0]
    texts = [shape.text for shape in slide.shapes if shape.has_text_frame]
    assert any("Financial results" in text for text in texts)
    assert any("Revenue increased in Q3." in text for text in texts)
    assert any("Q3 was the strongest quarter." in text for text in texts)
    assert any(shape.has_table for shape in slide.shapes)
    table_text = "\n".join(
        cell.text
        for shape in slide.shapes
        if shape.has_table
        for row in shape.table.rows
        for cell in row.cells
    )
    assert "$1,200,000" in table_text
    assert any("Source: block-revenue" in text for text in texts)
    notes = slide.notes_slide.notes_text_frame.text
    assert '"document_id": "doc-123"' in notes
    assert '"block_id": "block-revenue"' in notes
    assert "MOCK OUTPUT" not in "\n".join(texts)


def test_pptx_response_accepts_typed_slide_guidance_and_preserves_it_in_native_notes():
    reference = _reference()
    response = {
        "target_format": "pptx",
        "presentation_title": "Quarterly Results",
        "slides": [{
            "slide_id": "slide-results",
            "title": "Financial results",
            "purpose": "Summarize reported quarterly revenue.",
            "visual_guidance": "Use a restrained title and a prominent revenue callout.",
            "mapping_ids": ["mapping-revenue"],
            "title_source_references": [reference.model_dump(mode="json")],
            "elements": [{
                "element_id": "element-revenue",
                "element_type": "paragraph",
                "mapping_ids": ["mapping-revenue"],
                "content": {
                    "text": "Revenue was $1.2 million in Q3 2026.",
                    "source_references": [reference.model_dump(mode="json")],
                },
            }],
        }],
    }
    content = _parse_artifact_content(json.dumps(response), DocumentFormat.PPTX)
    rendered = render_pptx(
        content,
        is_mock=False,
        provenance={"document_id": "doc-123", "plan_id": "plan-456"},
    )

    validate_pptx_output(rendered)
    presentation = Presentation(BytesIO(rendered))
    slide = presentation.slides[0]
    notes = slide.notes_slide.notes_text_frame.text
    assert "Summarize reported quarterly revenue." in notes
    assert "Use a restrained title and a prominent revenue callout." in notes
    assert '"block_id": "block-revenue"' in notes
    assert '"plan_id": "plan-456"' in notes


def test_pptx_slide_guidance_schema_still_rejects_undeclared_fields():
    payload = {
        "target_format": "pptx",
        "presentation_title": "Quarterly Results",
        "slides": [{
            "slide_id": "slide-1",
            "title": "Revenue",
            "unrecognized_instruction": "Must remain invalid",
        }],
    }
    with pytest.raises(ValidationError):
        PPTXArtifactContent.model_validate(payload)


def test_mock_writer_marks_output_and_still_generates_valid_native_pptx():
    output = render_pptx(_content(), is_mock=True, provenance={"document_id": "doc-123"})
    validate_pptx_output(output)
    presentation = Presentation(BytesIO(output))
    assert any(
        "MOCK OUTPUT" in shape.text
        for shape in presentation.slides[0].shapes
        if shape.has_text_frame
    )


@pytest.mark.parametrize("output", [b"", b"not a zip package"])
def test_validator_rejects_empty_or_malformed_pptx(output):
    with pytest.raises(ValueError):
        validate_pptx_output(output)


def test_schema_accepts_typed_native_chart_and_rejects_image_placeholder():
    reference = _reference()
    chart_payload = {
        "target_format": "pptx",
        "presentation_title": "Quarterly Results",
        "slides": [{
            "slide_id": "slide-1",
            "title": "Revenue",
            "elements": [{
                "element_id": "chart-1",
                "element_type": "chart",
                "content": {
                    "title": "Revenue by quarter",
                    "chart_type": "bar",
                    "categories": ["Q1", "Q2"],
                    "series": [{"name": "Revenue", "values": [10, 12]}],
                    "source_references": [reference.model_dump(mode="json")],
                },
            }],
        }],
    }
    parsed = PPTXArtifactContent.model_validate(chart_payload)
    assert isinstance(parsed.slides[0].elements[0], PPTXChartElement)

    payload = {
        "target_format": "pptx",
        "presentation_title": "Quarterly Results",
        "slides": [{
            "slide_id": "slide-1",
            "title": "Revenue",
            "elements": [{
                "element_id": "image-1",
                "element_type": "image_placeholder",
            }],
        }],
    }
    with pytest.raises(ValidationError):
        PPTXArtifactContent.model_validate(payload)


@pytest.mark.parametrize(
    ("chart_type", "native_type"),
    [
        ("bar", XL_CHART_TYPE.BAR_CLUSTERED),
        ("line", XL_CHART_TYPE.LINE),
        ("pie", XL_CHART_TYPE.PIE),
    ],
)
def test_writer_creates_editable_native_chart_with_title_categories_series_and_values(chart_type, native_type):
    content = PPTXArtifactContent(
        target_format="pptx",
        presentation_title="Quarterly Results",
        slides=[{
            "slide_id": "slide-chart",
            "title": "Revenue",
            "elements": [PPTXChartElement(
                element_id="chart-1",
                element_type="chart",
                mapping_ids=["mapping-chart"],
                content=PPTXChartContent(
                    title="Revenue by quarter",
                    chart_type=chart_type,
                    categories=["Q1", "Q2", "Q3"],
                    series=[{
                        "name": "Revenue",
                        "values": [10, 12, 15],
                    }],
                    source_references=[_reference()],
                ),
            )],
        }],
    )
    output = render_pptx(content, is_mock=False, provenance={"document_id": "doc-chart"})

    validate_pptx_output(output)
    presentation = Presentation(BytesIO(output))
    slide = presentation.slides[0]
    chart_shape = next(shape for shape in slide.shapes if shape.has_chart)
    chart = chart_shape.chart
    assert chart.chart_type == native_type
    assert chart.chart_title.text_frame.text == "Revenue by quarter"
    assert [category.label for category in chart.plots[0].categories] == ["Q1", "Q2", "Q3"]
    assert chart.series[0].name == "Revenue"
    assert list(chart.series[0].values) == [10.0, 12.0, 15.0]
    assert "Source: block-revenue" in "\n".join(
        shape.text for shape in slide.shapes if shape.has_text_frame
    )
    assert '"block_id": "block-revenue"' in slide.notes_slide.notes_text_frame.text


def test_chart_allows_missing_values_as_native_gaps():
    chart_content = PPTXChartContent(
        title="Quarterly revenue",
        chart_type="line",
        categories=["Q1", "Q2", "Q3"],
        series=[{"name": "Revenue", "values": [10, None, 15]}],
        source_references=[_reference()],
    )
    content = PPTXArtifactContent(
        target_format="pptx",
        presentation_title="Results",
        slides=[{
            "slide_id": "slide-chart",
            "title": "Revenue",
            "elements": [PPTXChartElement(element_id="chart-1", element_type="chart", content=chart_content)],
        }],
    )
    output = render_pptx(content, is_mock=False, provenance={})
    chart = next(shape.chart for shape in Presentation(BytesIO(output)).slides[0].shapes if shape.has_chart)
    assert list(chart.series[0].values) == [10.0, None, 15.0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"series": [{"name": "Revenue", "values": [10]}]},
        {"series": [{"name": "Revenue", "values": [10, "unknown"]}]},
        {"series": [{"name": "Revenue", "values": [10, float("nan")]}]},
        {"series": [{"name": "Revenue", "values": [None, None]}]},
        {"categories": ["Q1", "Q2"], "series": [{"name": "Revenue", "values": [-1, 2]}], "chart_type": "pie"},
        {"categories": ["Q1", "Q2"], "series": [
            {"name": "Revenue", "values": [1, 2]}, {"name": "Cost", "values": [2, 3]},
        ], "chart_type": "pie"},
    ],
)
def test_chart_schema_rejects_malformed_or_unsupported_data(overrides):
    data = {
        "title": "Quarterly results",
        "chart_type": "bar",
        "categories": ["Q1", "Q2"],
        "series": [{"name": "Revenue", "values": [10, 12]}],
        "source_references": [_reference().model_dump(mode="json")],
        **overrides,
    }
    with pytest.raises(ValidationError):
        PPTXChartContent.model_validate(data)


def test_chart_schema_requires_source_references_and_rejects_unknown_chart_types():
    with pytest.raises(ValidationError):
        PPTXChartContent.model_validate({
            "title": "Results", "chart_type": "area", "categories": ["Q1"],
            "series": [{"name": "Revenue", "values": [10]}],
        })


def test_schema_requires_source_references_for_content_items():
    payload = {
        "target_format": "pptx",
        "presentation_title": "Quarterly Results",
        "slides": [{
            "slide_id": "slide-1",
            "title": "Revenue",
            "elements": [{
                "element_id": "paragraph-1",
                "element_type": "paragraph",
                "content": {"text": "Revenue grew."},
            }],
        }],
    }
    with pytest.raises(ValidationError):
        PPTXArtifactContent.model_validate(payload)


def test_planned_image_placeholders_remain_explicitly_unsupported():
    element_type = "image_placeholder"
    plan = TransformationPlan(
        plan_id=uuid4(),
        document_id="00000000-0000-4000-8000-000000000501",
        interpretation_id=uuid4(),
        target_format=DocumentFormat.PPTX,
        output_structure=PPTXOutputStructure(
            target_format="pptx",
            presentation_title="Plan",
            slides=[PPTXSlidePlan(
                slide_id="slide-1",
                title="Revenue",
                purpose="Report source data.",
                elements=[PPTXElementPlan(
                    element_id="element-1",
                    element_type=element_type,
                    purpose="Unsupported visual output.",
                )],
            )],
        ),
        validation_rules=PlanValidationRules(
            validation_status="ready",
            target_format=DocumentFormat.PPTX,
        ),
        provenance=TransformationProvenance(
            provider="groq", model="test-model", prompt_version="transformation_v6", is_mock=False,
        ),
        metadata=TransformationMetadata(
            source_ir_fingerprint="a" * 64,
            interpretation_fingerprint="b" * 64,
            instruction_fingerprint="c" * 64,
            input_fingerprint="d" * 64,
        ),
    )

    with pytest.raises(UnsupportedArtifactElementError, match=element_type):
        _reject_unsupported_pptx_plan_elements(plan)


def test_pptx_artifact_must_preserve_plan_slide_element_and_mapping_ids():
    reference = _reference()
    plan = TransformationPlan(
        plan_id=uuid4(),
        document_id="00000000-0000-4000-8000-000000000502",
        interpretation_id=uuid4(),
        target_format=DocumentFormat.PPTX,
        output_structure=PPTXOutputStructure(
            target_format="pptx",
            presentation_title="Quarterly Results",
            slides=[PPTXSlidePlan(
                slide_id="slide-results",
                title="Financial results",
                purpose="Summarize revenue.",
                visual_guidance="Use a restrained visual hierarchy.",
                elements=[PPTXElementPlan(
                    element_id="element-summary",
                    element_type="paragraph",
                    purpose="State the reported result.",
                    mapping_ids=["mapping-revenue"],
                )],
            )],
        ),
        content_mappings=[ContentMapping(
            mapping_id="mapping-revenue",
            source_item_type="fact",
            source_item_id="fact-1",
            destination=PlanDestination(target_type="slide_element", target_id="element-summary"),
            operation="preserve",
            source_references=[reference],
        )],
        generation_instructions=["Preserve the reported value."],
        preservation_rules=["Keep the source citation."],
        validation_rules=PlanValidationRules(
            validation_status="ready",
            target_format=DocumentFormat.PPTX,
        ),
        provenance=TransformationProvenance(
            provider="groq", model="test-model", prompt_version="transformation_v6", is_mock=False,
        ),
        metadata=TransformationMetadata(
            source_ir_fingerprint="a" * 64,
            interpretation_fingerprint="b" * 64,
            instruction_fingerprint="c" * 64,
            input_fingerprint="d" * 64,
        ),
    )
    content = PPTXArtifactContent(
        target_format="pptx",
        presentation_title="Quarterly Results",
        slides=[{
            "slide_id": "slide-results",
            "title": "Financial results",
            "purpose": "Summarize revenue.",
            "visual_guidance": "Use a restrained visual hierarchy.",
            "elements": [{
                "element_id": "element-summary",
                "element_type": "paragraph",
                "mapping_ids": ["mapping-revenue"],
                "content": {
                    "text": "Revenue increased.",
                    "source_references": [reference.model_dump(mode="json")],
                },
            }],
        }],
    )

    _validate_pptx_plan_alignment(content, plan)
    mismatched = content.model_copy(deep=True)
    mismatched.slides[0].elements[0].mapping_ids = []
    with pytest.raises(InvalidArtifactContentError, match="mapping placements"):
        _validate_pptx_plan_alignment(mismatched, plan)

    mismatched_guidance = content.model_copy(deep=True)
    mismatched_guidance.slides[0].visual_guidance = "Use a chart."
    with pytest.raises(InvalidArtifactContentError, match="visual guidance"):
        _validate_pptx_plan_alignment(mismatched_guidance, plan)
