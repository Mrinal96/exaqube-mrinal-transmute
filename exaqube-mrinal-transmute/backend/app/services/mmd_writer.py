"""Deterministic Mermaid output from canonical IR structures."""

from __future__ import annotations

import json
import re

from app.core.formats import MERMAID_DECLARATIONS
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR, IRBlock, IRSection
from app.services.native_writer_errors import UnsupportedIRContentError


IR_MMD_SCHEMA_VERSION = "native-ir-mmd-v1"
_DECLARATION = re.compile(
    r"(?im)^\s*(?:" + "|".join(re.escape(value) for value in MERMAID_DECLARATIONS) + r")\b"
)


def render_mmd(document_ir: DocumentIR) -> bytes:
    """Generate a flowchart or preserve one source Mermaid diagram without an LLM."""
    ir = _validated_ir(document_ir)
    source_diagrams = [block for block in _all_blocks(ir) if block.kind == "diagram"]
    if source_diagrams:
        if _is_lossless_source_diagram(ir, source_diagrams):
            diagram = source_diagrams[0].text
            rendered = diagram.rstrip() + "\n\n" + _metadata_comments(ir) + "\n"
            validate_mmd_output(rendered.encode("utf-8"))
            return rendered.encode("utf-8")
        raise UnsupportedIRContentError(
            "MMD writer cannot merge a source diagram with additional IR structures without a Mermaid parser."
        )

    unsupported = [block for block in _all_blocks(ir) if block.kind == "chart"]
    if unsupported:
        raise UnsupportedIRContentError(
            "MMD writer cannot represent chart block(s): " + ", ".join(block.id for block in unsupported) + "."
        )

    lines = ["flowchart TD"]
    document_node = "document_0"
    document_label = {
        "title": ir.title,
        "filename": ir.filename,
        "source_format": ir.source_format.value,
        "document_id": ir.document_id,
    }
    lines.append(f"  {document_node}[\"{_escape_label(_json(document_label))}\"]")

    section_counter = 0
    block_counter = 0
    top_level_sections: list[str] = []

    def render_section(section: IRSection, path: tuple[str, ...], indent: int = 0) -> None:
        nonlocal section_counter, block_counter
        current = section_counter
        section_counter += 1
        graph_id = f"section_group_{current}"
        node_id = f"section_{current}"
        if not path:
            top_level_sections.append(node_id)
        indent_text = "  " * (indent + 1)
        section_payload = {
            "id": section.id,
            "title": section.title,
            "level": section.level,
            "order": section.order,
            "source": section.source.model_dump(mode="json", exclude_none=True) if section.source else None,
        }
        lines.append(f"{'  ' * indent}subgraph {graph_id}[\"{_escape_label(section.title)}\"]")
        lines.append(f"{indent_text}direction TB")
        lines.append(f"{indent_text}{node_id}[\"{_escape_label(_json(section_payload))}\"]")
        for block in section.blocks:
            block_id = f"ir_block_{block_counter}"
            block_counter += 1
            lines.append(f"{indent_text}{block_id}[\"{_escape_label(_json(_block_payload(block)))}\"]")
        for child in section.children:
            render_section(child, path + (section.title,), indent + 1)
        lines.append(f"{'  ' * indent}end")

    for section in ir.sections:
        render_section(section, ())
    for index, block in enumerate(ir.blocks):
        block_id = f"ir_root_block_{index}"
        lines.append(f"  {block_id}[\"{_escape_label(_json(_block_payload(block)))}\"]")
        lines.append(f"  {document_node} -->|contains| {block_id}")
    for section_node in top_level_sections:
        lines.append(f"  {document_node} -->|contains| {section_node}")

    entity_nodes: dict[str, str] = {}
    for index, entity in enumerate(ir.entities):
        node_id = f"entity_{index}"
        if entity.id in entity_nodes:
            raise UnsupportedIRContentError(f"Duplicate entity ID {entity.id!r} cannot be represented in Mermaid.")
        entity_nodes[entity.id] = node_id
        payload = {
            "id": entity.id,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "attributes": entity.attributes,
            "source_locations": [location.model_dump(mode="json", exclude_none=True) for location in entity.source_locations],
        }
        lines.append(f"  {node_id}[\"{_escape_label(_json(payload))}\"]")

    for index, relationship in enumerate(ir.relationships):
        source_node = entity_nodes.get(relationship.source_entity_id)
        target_node = entity_nodes.get(relationship.target_entity_id)
        if source_node is None or target_node is None:
            raise UnsupportedIRContentError(
                f"Relationship {index + 1} refers to an entity ID absent from the IR entity collection."
            )
        label = {
            "type": relationship.relationship_type,
            "source_locations": [location.model_dump(mode="json", exclude_none=True) for location in relationship.source_locations],
        }
        lines.append(f"  {source_node} -->|\"{_escape_label(_json(label))}\"| {target_node}")

    fact_groups = (("fact", ir.facts), ("metric", ir.metrics), ("claim", ir.claims))
    semantic_counter = 0
    for collection, facts in fact_groups:
        for fact in facts:
            node_id = f"semantic_{semantic_counter}"
            semantic_counter += 1
            payload = {"collection": collection, **fact.model_dump(mode="json", exclude_none=True)}
            lines.append(f"  {node_id}[\"{_escape_label(_json(payload))}\"]")

    for index, asset in enumerate(ir.assets):
        payload = asset.model_dump(mode="json", exclude_none=True)
        lines.append(f"  asset_{index}[\"{_escape_label(_json(payload))}\"]")

    rendered = "\n".join(lines) + "\n\n" + _metadata_comments(ir) + "\n"
    validate_mmd_output(rendered.encode("utf-8"))
    return rendered.encode("utf-8")


def validate_mmd_output(content: bytes) -> None:
    if not content:
        raise ValueError("The Mermaid renderer produced an empty file.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("The rendered Mermaid source is not valid UTF-8.") from exc
    if not text.strip() or _DECLARATION.search(text) is None:
        raise ValueError("The rendered Mermaid source has no recognized diagram declaration.")
    diagram_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("%%")]
    if diagram_lines and re.match(r"^(?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR)\b", diagram_lines[0], re.IGNORECASE) is None:
        if re.match(r"^(?:flowchart|graph)\b", diagram_lines[0], re.IGNORECASE):
            raise ValueError("A Mermaid flowchart declaration must include a valid direction.")


def _validated_ir(document_ir: DocumentIR) -> DocumentIR:
    if isinstance(document_ir, DocumentIR):
        return DocumentIR.model_validate(document_ir.model_dump(mode="python"))
    return DocumentIR.model_validate(document_ir)


def _all_blocks(ir: DocumentIR) -> list[IRBlock]:
    blocks = list(ir.blocks)

    def visit(sections: list[IRSection]) -> None:
        for section in sections:
            blocks.extend(section.blocks)
            visit(section.children)

    visit(ir.sections)
    return blocks


def _is_lossless_source_diagram(ir: DocumentIR, diagrams: list[IRBlock]) -> bool:
    return (
        ir.source_format == DocumentFormat.MMD
        and len(diagrams) == 1
        and len(_all_blocks(ir)) == 1
        and not ir.entities
        and not ir.facts
        and not ir.metrics
        and not ir.claims
        and not ir.relationships
        and not ir.assets
    )


def _block_payload(block: IRBlock) -> dict[str, object]:
    return {
        "id": block.id,
        "kind": block.kind,
        "text": block.text,
        "level": block.level,
        "table": block.table.model_dump(mode="json", exclude_none=True) if block.table else None,
        "attributes": block.attributes,
        "source": block.source.model_dump(mode="json", exclude_none=True),
    }


def _metadata_comments(ir: DocumentIR) -> str:
    values = {
        "document_id": ir.document_id,
        "filename": ir.filename,
        "title": ir.title,
        "source_format": ir.source_format.value,
        "schema_version": ir.schema_version,
        "metadata": ir.metadata,
        "warnings": ir.warnings,
        "provenance": [record.model_dump(mode="json", exclude_none=True) for record in ir.provenance],
        "sections": [_section_metadata(section) for section in ir.sections],
    }
    return "\n".join(
        "%% Transmute " + key + ": " + _json(value)
        for key, value in values.items()
    )


def _section_metadata(section: IRSection) -> dict[str, object]:
    return {
        "id": section.id,
        "title": section.title,
        "order": section.order,
        "level": section.level,
        "source": section.source.model_dump(mode="json", exclude_none=True) if section.source else None,
        "children": [_section_metadata(child) for child in section.children],
    }


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    except (TypeError, ValueError) as exc:
        raise UnsupportedIRContentError("Mermaid writer encountered IR data that cannot be serialized losslessly.") from exc


def _json_default(value: object) -> str:
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


def _escape_label(value: str) -> str:
    replacements = {
        "&": "#38;",
        "#": "#35;",
        '"': "#quot;",
        "'": "#39;",
        "[": "#91;",
        "]": "#93;",
        "(": "#40;",
        ")": "#41;",
        "{": "#123;",
        "}": "#125;",
        "<": "#60;",
        ">": "#62;",
        "|": "#124;",
        "\\": "#92;",
    }
    escaped = "".join(replacements.get(char, "<br/>" if char in "\r\n" else char) for char in value)
    return escaped
