"""Authoritative registry for target artifact schemas, prompts, writers and validators."""

from dataclasses import dataclass
import json
from typing import Callable, cast

from pydantic import BaseModel

from app.models.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    DOCXArtifactContent,
    HTMLArtifactContent,
    PPTXArtifactContent,
)
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR
from app.services.artifact_renderers import render_docx, render_html, validate_rendered_output
from app.services.mmd_writer import IR_MMD_SCHEMA_VERSION, render_mmd, validate_mmd_output
from app.services.xlsx_writer import IR_XLSX_SCHEMA_VERSION, render_xlsx, validate_xlsx_output
from app.services.pptx_writer import render_pptx


class ArtifactContractConfigurationError(RuntimeError):
    """The requested target does not have a complete, internally consistent artifact contract."""

    def __init__(self, target_format: DocumentFormat, reason: str) -> None:
        super().__init__(f"Artifact contract unavailable for {target_format.value}: {reason}")
        self.code = "artifact_contract_unavailable"
        self.target_format = target_format
        self.reason = reason


ArtifactWriter = Callable[[BaseModel, bool, dict[str, object]], bytes]
IRWriter = Callable[[DocumentIR], bytes]


@dataclass(frozen=True)
class ArtifactContract:
    target_format: DocumentFormat
    schema_model: type[BaseModel]
    schema_version: str
    writer: ArtifactWriter
    output_validator: Callable[[bytes], None]
    standalone_guidance: str
    planned_guidance: str


@dataclass(frozen=True)
class NativeIRWriterContract:
    target_format: DocumentFormat
    schema_version: str
    writer: IRWriter
    output_validator: Callable[[bytes], None]


def _render_html(content: BaseModel, is_mock: bool, provenance: dict[str, object]) -> bytes:
    del provenance
    return render_html(cast(HTMLArtifactContent, content), is_mock=is_mock)


def _render_docx(content: BaseModel, is_mock: bool, provenance: dict[str, object]) -> bytes:
    del provenance
    return render_docx(cast(DOCXArtifactContent, content), is_mock=is_mock)


def _render_pptx(content: BaseModel, is_mock: bool, provenance: dict[str, object]) -> bytes:
    return render_pptx(cast(PPTXArtifactContent, content), is_mock=is_mock, provenance=provenance)


ARTIFACT_CONTRACTS: dict[DocumentFormat, ArtifactContract] = {
    DocumentFormat.HTML: ArtifactContract(
        target_format=DocumentFormat.HTML,
        schema_model=HTMLArtifactContent,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        writer=_render_html,
        output_validator=lambda content: validate_rendered_output(content, "html"),
        standalone_guidance=(
            "Create a self-contained semantic HTML explainer with a clear page title, sections, concise paragraphs, "
            "bullets, metric cards, and tables where supported."
        ),
        planned_guidance=(
            "Follow the validated HTML section and component plan, include every mapped item, and honor its "
            "preservation rules and explicit omissions."
        ),
    ),
    DocumentFormat.DOCX: ArtifactContract(
        target_format=DocumentFormat.DOCX,
        schema_model=DOCXArtifactContent,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        writer=_render_docx,
        output_validator=lambda content: validate_rendered_output(content, "docx"),
        standalone_guidance=(
            "Create a polished Word report with a document title, hierarchical sections, readable paragraphs, "
            "lists, and native tables for supported metrics or tabular data."
        ),
        planned_guidance=(
            "Use the planned document title and section order exactly; follow each section's purpose and mapping IDs. "
            "Use paragraphs, lists, metrics, and tables according to each mapping's operation and formatting guidance. "
            "Include every mapped semantic item and honor explicit omissions."
        ),
    ),
    DocumentFormat.PPTX: ArtifactContract(
        target_format=DocumentFormat.PPTX,
        schema_model=PPTXArtifactContent,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        writer=_render_pptx,
        output_validator=lambda content: validate_rendered_output(content, "pptx"),
        standalone_guidance=(
            "Generate a native editable PowerPoint. Use editable title/text shapes, bullet paragraphs, native tables, "
            "metric callouts, source-backed callouts, and native bar, line, or pie charts when categories and numeric "
            "series are supported by cited source content. Do not infer missing chart values. Image placeholders are unsupported."
        ),
        planned_guidance=(
            "Follow the supplied slide and element IDs, purpose, visual guidance, and mapping destinations exactly. "
            "Use editable titles, text, bullets, tables, metric callouts, source-backed callouts, and native bar, line, "
            "or pie charts where planned. For charts return title, chart_type, categories, named series with one numeric "
            "value or null per category, and source_references copied from the mapped source. Never invent values or "
            "fill gaps. Image placeholders are unsupported; do not invent images."
        ),
    ),
}


# These writers serialize the already validated canonical IR directly. They do
# not call the LLM or reuse its target-content schemas.
NATIVE_IR_WRITERS: dict[DocumentFormat, NativeIRWriterContract] = {
    DocumentFormat.XLSX: NativeIRWriterContract(
        target_format=DocumentFormat.XLSX,
        schema_version=IR_XLSX_SCHEMA_VERSION,
        writer=render_xlsx,
        output_validator=validate_xlsx_output,
    ),
    DocumentFormat.MMD: NativeIRWriterContract(
        target_format=DocumentFormat.MMD,
        schema_version=IR_MMD_SCHEMA_VERSION,
        writer=render_mmd,
        output_validator=validate_mmd_output,
    ),
}


def get_artifact_contract(target_format: DocumentFormat) -> ArtifactContract:
    contract = ARTIFACT_CONTRACTS.get(target_format)
    if contract is None:
        raise ArtifactContractConfigurationError(
            target_format,
            "no target artifact schema and native writer are registered",
        )
    validate_artifact_contract(contract)
    return contract


def get_native_ir_writer(target_format: DocumentFormat) -> NativeIRWriterContract | None:
    return NATIVE_IR_WRITERS.get(target_format)


def validate_artifact_contract(contract: ArtifactContract) -> None:
    """Preflight the schema/writer association before any provider request."""
    if not isinstance(contract.schema_model, type) or not issubclass(contract.schema_model, BaseModel):
        raise ArtifactContractConfigurationError(contract.target_format, "registered artifact model is invalid")
    if contract.writer is None or not callable(contract.writer):
        raise ArtifactContractConfigurationError(contract.target_format, "no native writer is registered")
    if contract.output_validator is None or not callable(contract.output_validator):
        raise ArtifactContractConfigurationError(contract.target_format, "no output validator is registered")
    if not contract.schema_version.strip():
        raise ArtifactContractConfigurationError(contract.target_format, "artifact schema version is missing")
    if not contract.standalone_guidance.strip() or not contract.planned_guidance.strip():
        raise ArtifactContractConfigurationError(contract.target_format, "artifact prompt guidance is missing")
    if contract.schema_model.model_config.get("extra") != "forbid":
        raise ArtifactContractConfigurationError(contract.target_format, "artifact model must forbid undeclared fields")
    try:
        schema = contract.schema_model.model_json_schema()
        json.dumps(schema, ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        raise ArtifactContractConfigurationError(contract.target_format, "artifact JSON Schema cannot be serialized") from exc
    properties = schema.get("properties", {})
    target = properties.get("target_format", {})
    if target.get("const") != contract.target_format.value:
        raise ArtifactContractConfigurationError(
            contract.target_format,
            "artifact schema target_format does not match its registry key",
        )
    if "target_format" not in schema.get("required", []):
        raise ArtifactContractConfigurationError(contract.target_format, "artifact schema must require target_format")
    if not _all_object_schemas_forbid_extra_properties(schema):
        raise ArtifactContractConfigurationError(
            contract.target_format,
            "all nested artifact models must forbid undeclared properties",
        )


def _all_object_schemas_forbid_extra_properties(schema: object) -> bool:
    if isinstance(schema, dict):
        is_object_schema = schema.get("type") == "object" or "properties" in schema
        if is_object_schema and schema.get("additionalProperties") is not False:
            return False
        return all(_all_object_schemas_forbid_extra_properties(value) for value in schema.values())
    if isinstance(schema, list):
        return all(_all_object_schemas_forbid_extra_properties(value) for value in schema)
    return True


SUPPORTED_ARTIFACT_FORMATS = frozenset(ARTIFACT_CONTRACTS) | frozenset(NATIVE_IR_WRITERS)
