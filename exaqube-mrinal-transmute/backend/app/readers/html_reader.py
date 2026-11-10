"""Extract semantic HTML content while retaining links and table structure."""

from bs4 import BeautifulSoup

from app.models.intermediate import AssetReference, DocumentIR, IRSection, SourceLocation, TableData
from app.readers.common import base_ir, make_block, make_section

CONTENT_TAGS = {"p", "blockquote", "ul", "ol", "table", "a", "pre", "figure", "figcaption", "address", "dl"}
HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}
SEMANTIC_TAGS = ("header", "nav", "main", "article", "section", "aside", "footer")


def read_html(content: bytes, document_id: str, filename: str) -> DocumentIR:
    text = content.decode("utf-8-sig")
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if not title:
        first_heading = soup.find(list(HEADING_TAGS))
        title = first_heading.get_text(" ", strip=True) if first_heading else ""
    semantic_regions = [{"tag": tag.name, "id": tag.get("id"), "role": tag.get("role")} for tag in soup.find_all(SEMANTIC_TAGS)]
    ir = base_ir(
        document_id,
        filename,
        "html",
        "html_reader",
        title=title,
        metadata={"language": (soup.html.get("lang") if soup.html else None), "semantic_regions": semantic_regions},
    )
    stack: list[IRSection] = []
    element_index = 0
    for tag in soup.find_all(list(HEADING_TAGS) + sorted(CONTENT_TAGS)):
        element_index += 1
        if tag.name in HEADING_TAGS:
            level = HEADING_TAGS[tag.name]
            heading_text = tag.get_text(" ", strip=True)
            section = make_section(
                f"html-section-{element_index}", heading_text or f"Heading {element_index}", level=level, order=element_index,
                source=SourceLocation(element_index=element_index, section_path=[part.title for part in stack]),
            )
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(section)
            else:
                ir.sections.append(section)
            stack.append(section)
            continue
        if tag.name in {"ul", "ol"}:
            items = [item.get_text(" ", strip=True) for item in tag.find_all("li", recursive=True)]
            block = make_block(
                f"html-list-{element_index}", "list", "\n".join(items),
                SourceLocation(element_index=element_index, section_path=[part.title for part in stack]),
                attributes={"ordered": tag.name == "ol", "items": items},
            )
        elif tag.name == "table":
            matrix = [[cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"], recursive=False)] for row in tag.find_all("tr")]
            matrix = [row for row in matrix if row]
            caption = tag.find("caption")
            block = make_block(
                f"html-table-{element_index}", "table", source=SourceLocation(element_index=element_index, section_path=[part.title for part in stack]),
                table=TableData(headers=matrix[0] if matrix else [], rows=matrix[1:] if matrix else [], caption=caption.get_text(" ", strip=True) if caption else None),
                attributes={"row_count": len(matrix), "column_count": len(matrix[0]) if matrix else 0},
            )
        elif tag.name == "a":
            href = tag.get("href")
            block = make_block(
                f"html-link-{element_index}", "link", tag.get_text(" ", strip=True),
                SourceLocation(element_index=element_index, section_path=[part.title for part in stack]),
                attributes={"href": href, "title": tag.get("title")},
            )
        else:
            block = make_block(
                f"html-text-{element_index}", "text", tag.get_text(" ", strip=True),
                SourceLocation(element_index=element_index, section_path=[part.title for part in stack]),
                attributes={"tag": tag.name, "id": tag.get("id"), "class": tag.get("class", [])},
            )
        if stack:
            stack[-1].blocks.append(block)
        else:
            if not ir.sections:
                ir.sections.append(make_section("html-document", title or "Document content"))
            ir.sections[0].blocks.append(block)

    for image_index, image in enumerate(soup.find_all(["img", "source"]), start=1):
        source = image.get("src") or image.get("srcset")
        if source:
            ir.assets.append(AssetReference(source_part=str(source), media_type=image.get("type"), size_bytes=0))
    if not ir.title:
        ir.title = filename
    if ir.assets:
        ir.warnings.append("External or embedded HTML media are referenced in the IR; asset contents are not downloaded.")
    return ir
