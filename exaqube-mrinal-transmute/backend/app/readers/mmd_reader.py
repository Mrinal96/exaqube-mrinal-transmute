"""Extract Mermaid source, diagram kind, title, and line provenance."""

import re

from app.models.intermediate import SourceLocation
from app.models.intermediate import DocumentIR
from app.readers.common import base_ir, make_block, make_section
from app.readers.errors import ExtractionError

MERMAID_DECLARATIONS = (
    "flowchart", "graph", "sequencediagram", "classdiagram", "statediagram", "erdiagram", "journey", "gantt", "pie",
    "mindmap", "timeline", "gitgraph", "quadrantchart", "requirementdiagram", "c4context", "c4container", "c4component",
    "c4dynamic", "c4deployment", "xychart-beta", "block-beta", "sankey-beta", "architecture-beta", "packet-beta", "kanban", "radar-beta",
)


def read_mmd(content: bytes, document_id: str, filename: str) -> DocumentIR:
    text = content.decode("utf-8-sig")
    declaration_pattern = "|".join(re.escape(value) for value in MERMAID_DECLARATIONS)
    declaration = re.search(rf"(?im)^\s*({declaration_pattern})\b", text)
    if not declaration:
        raise ExtractionError("Mermaid source has no recognized diagram declaration.")
    diagram_type = declaration.group(1) if declaration else "unknown"
    title_match = re.search(r"(?im)^\s*(?:title|accTitle)\s*:\s*(.+)$", text)
    title = title_match.group(1).strip().strip("\"'") if title_match else ""
    lines = text.splitlines()
    ir = base_ir(
        document_id, filename, "mmd", "mmd_reader", title=title,
        metadata={"diagram_type": diagram_type, "line_count": len(lines)},
    )
    location = SourceLocation(line_start=1, line_end=max(1, len(lines)))
    section = make_section("diagram", title or f"{diagram_type} diagram", order=0, source=location)
    section.blocks.append(make_block("diagram-source", "diagram", text, location, attributes={"diagram_type": diagram_type}))
    ir.sections.append(section)
    if not title:
        ir.warnings.append("The Mermaid source does not declare a title.")
    return ir
