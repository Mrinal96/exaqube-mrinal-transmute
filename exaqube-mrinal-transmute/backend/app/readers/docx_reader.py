"""Extract Word headings, paragraphs, tables, lists, and document order."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from docx import Document as open_document
from docx.document import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.models.intermediate import AssetReference, DocumentIR, IRSection, SourceLocation, TableData
from app.readers.common import base_ir, make_block, make_section


def _iter_body_blocks(document: Document):
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def read_docx(content: bytes, document_id: str, filename: str) -> DocumentIR:
    document = open_document(BytesIO(content))
    properties = document.core_properties
    ir = base_ir(
        document_id,
        filename,
        "docx",
        "docx_reader",
        title=properties.title or "",
        metadata={"author": properties.author or "", "subject": properties.subject or "", "keywords": properties.keywords or ""},
    )
    stack: list[IRSection] = []
    order = 0
    paragraph_index = 0
    for item in _iter_body_blocks(document):
        if isinstance(item, Paragraph):
            paragraph_index += 1
            text = item.text.strip()
            style_name = item.style.name if item.style else "Normal"
            if style_name.lower().startswith("heading"):
                try:
                    level = int(style_name.split()[-1])
                except ValueError:
                    level = 1
                level = max(1, min(level, 9))
                section = make_section(
                    f"section-{order + 1}", text or f"Heading {order + 1}", level=level, order=order,
                    source=SourceLocation(paragraph_index=paragraph_index, section_path=[text] if text else []),
                )
                while stack and stack[-1].level >= level:
                    stack.pop()
                if stack:
                    stack[-1].children.append(section)
                else:
                    ir.sections.append(section)
                stack.append(section)
                order += 1
                if not ir.title and level == 1:
                    ir.title = text
                continue
            if text:
                location = SourceLocation(paragraph_index=paragraph_index, section_path=[part.title for part in stack])
                kind = "list" if "list" in style_name.lower() else "text"
                block = make_block(f"paragraph-{paragraph_index}", kind, text, location, attributes={"style": style_name})
                if stack:
                    stack[-1].blocks.append(block)
                else:
                    section = _get_default_section(ir, order)
                    section.blocks.append(block)
            for link_index, hyperlink in enumerate(item._p.xpath(".//w:hyperlink")):
                relation_id = hyperlink.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                relationship = item.part.rels.get(relation_id) if relation_id else None
                if relationship and relationship.target_ref:
                    link_text = "".join(node.text or "" for node in hyperlink.xpath(".//w:t"))
                    link = make_block(
                        f"paragraph-{paragraph_index}-link-{link_index}", "link", link_text,
                        SourceLocation(paragraph_index=paragraph_index, section_path=[part.title for part in stack]),
                        attributes={"href": relationship.target_ref},
                    )
                    (stack[-1].blocks if stack else _get_default_section(ir, order).blocks).append(link)
        else:
            matrix = [[cell.text.strip() for cell in row.cells] for row in item.rows]
            location = SourceLocation(paragraph_index=paragraph_index, section_path=[part.title for part in stack])
            table_block = make_block(
                f"table-{order + 1}", "table", source=location,
                table=TableData(headers=matrix[0] if matrix else [], rows=matrix[1:] if matrix else []),
                attributes={"row_count": len(matrix), "column_count": len(matrix[0]) if matrix else 0},
            )
            (stack[-1].blocks if stack else _get_default_section(ir, order).blocks).append(table_block)
            order += 1

    with ZipFile(BytesIO(content)) as archive:
        for part in archive.namelist():
            if part.startswith("word/media/") and not part.endswith("/"):
                info = archive.getinfo(part)
                ir.assets.append(AssetReference(source_part=part, size_bytes=info.file_size))
    if ir.assets:
        ir.warnings.append("Embedded Word media are referenced in the IR; image contents are not interpreted.")
    if not ir.title:
        ir.title = filename
    return ir


def _get_default_section(ir: DocumentIR, order: int) -> IRSection:
    for section in ir.sections:
        if section.id == "document-body":
            return section
    section = make_section("document-body", "Document body", order=order)
    ir.sections.insert(0, section)
    return section
