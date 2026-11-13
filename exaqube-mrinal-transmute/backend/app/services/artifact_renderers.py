"""Native HTML and DOCX renderers plus output-file validation."""

from html import escape
from io import BytesIO

from bs4 import BeautifulSoup
from docx import Document

from app.models.artifacts import ArtifactMetric, ArtifactSection, ArtifactTable, ArtifactText, DOCXArtifactContent, DOCXArtifactSection, HTMLArtifactContent, HTMLArtifactSection
from app.services.pptx_writer import validate_pptx_output


MOCK_NOTICE = (
    "MOCK OUTPUT — no LLM interpretation or semantic transformation was performed. "
    "This file contains source content extracted from the uploaded document."
)


def render_html(content: HTMLArtifactContent, *, is_mock: bool) -> bytes:
    nav = "".join(
        f'<li><a href="#{escape(section.section_id or f"section-{index}", quote=True)}">{escape(section.heading)}</a></li>'
        for index, section in enumerate(content.sections, start=1)
    )
    sections = "".join(_html_section(section, index) for index, section in enumerate(content.sections, start=1))
    has_declared_main = any(section.semantic_element == "main" for section in content.sections)
    main_content = sections if has_declared_main else f"<main>{sections}</main>"
    navigation = f'<nav aria-label="Contents"><ul>{nav}</ul></nav>' if content.include_navigation else ""
    mock_notice = f'<aside class="mock-notice">{escape(MOCK_NOTICE)}</aside>' if is_mock else ""
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(content.page_title)}</title>
<style>
:root{{color-scheme:light;--ink:#172033;--muted:#526078;--accent:#5a47b8;--line:#dce2eb;--surface:#f5f7fb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--surface);color:var(--ink);font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}}
header,main,nav{{max-width:960px;margin:auto;padding:1.5rem}}header{{padding-top:3rem}}h1,h2{{line-height:1.2}}h1{{font-size:2.25rem;margin:.4rem 0}}h2{{margin-top:2rem}}nav{{padding-top:0}}nav ul{{display:flex;flex-wrap:wrap;gap:.75rem;list-style:none;padding:0}}a{{color:var(--accent)}}section,.mock-notice{{background:white;border:1px solid var(--line);border-radius:12px;padding:1.25rem;margin:1rem 0}}
.mock-notice{{border-color:#dbad55;background:#fff8e8;color:#563f12;font-size:.9rem}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem}}.metric{{border:1px solid var(--line);border-radius:8px;padding:.85rem}}.metric strong{{display:block;font-size:1.3rem}}.source{{display:block;color:var(--muted);font-size:.75rem;margin-top:.35rem}}table{{border-collapse:collapse;width:100%;margin:.75rem 0}}th,td{{border:1px solid var(--line);padding:.55rem;text-align:left}}th{{background:#eef1f7}}
</style></head><body><header>{mock_notice}<h1>{escape(content.page_title)}</h1></header>
{navigation}{main_content}</body></html>"""
    return document.encode("utf-8")


def _html_section(section: HTMLArtifactSection, index: int) -> str:
    components = []
    if section.component_order:
        items = {
            item.element_id: (kind, item, output_type)
            for kind, collection, output_type in (("text", section.paragraphs, None), ("text", section.bullet_points, "list"), ("metric", section.metrics, "metric_card"), ("table", section.tables, "table"))
            for item in collection
            if item.element_id is not None
        }
        components = [_html_component(*items[element_id]) for element_id in section.component_order]
        unindexed = [
            *(('text', item, None) for item in section.paragraphs if item.element_id is None),
            *(('text', item, 'list') for item in section.bullet_points if item.element_id is None),
            *(('metric', item, 'metric_card') for item in section.metrics if item.element_id is None),
            *(('table', item, 'table') for item in section.tables if item.element_id is None),
        ]
        components.extend(_html_component(*item) for item in unindexed)
    else:
        components = [
            *(f"<p>{escape(item.text)}{_html_sources(item.source_references)}</p>" for item in section.paragraphs),
            *(f"<ul><li>{escape(item.text)}{_html_sources(item.source_references)}</li></ul>" for item in section.bullet_points),
            *("<article class=\"metric\">" f"<span>{escape(item.name)}</span><strong>{escape(_metric_value(item))}</strong>" f"{_html_sources(item.source_references)}</article>" for item in section.metrics),
            *(_html_table(table) for table in section.tables),
        ]
    tag = section.semantic_element
    section_id = escape(section.section_id or f"section-{index}", quote=True)
    return f'<{tag} id="{section_id}"><h2>{escape(section.heading)}</h2>{"".join(components)}</{tag}>'


def _html_component(kind: str, item, planned_type: str | None = None) -> str:
    if kind == "table":
        return _html_table(item, element_id=item.element_id)
    element_id = f' id="{escape(item.element_id, quote=True)}"' if item.element_id else ""
    if kind == "metric":
        return (
            f'<article class="metric"{element_id}>'
            f"<span>{escape(item.name)}</span><strong>{escape(_metric_value(item))}</strong>"
            f"{_html_sources(item.source_references)}</article>"
        )
    text = escape(item.text)
    source = _html_sources(item.source_references)
    element_type = planned_type or item.element_type or "paragraph"
    if element_type == "heading":
        return f"<h3{element_id}>{text}</h3>{source}"
    if element_type == "list":
        return f"<ul{element_id}><li>{text}{source}</li></ul>"
    if element_type == "callout":
        return f"<aside class=\"callout\"{element_id}>{text}{source}</aside>"
    if element_type == "accordion":
        label = escape(item.label or "Details")
        body = f"<p>{text}{source}</p>"
        return f"<details{element_id}><summary>{label}</summary>{body}</details>"
    return f"<p{element_id}>{text}{source}</p>"


def _html_table(table, *, element_id: str | None = None) -> str:
    caption = f"<caption>{escape(table.caption)}</caption>" if table.caption else ""
    headers = "".join(f"<th>{escape(value)}</th>" for value in table.headers)
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>"
        for row in table.rows
    )
    identifier = f' id="{escape(element_id, quote=True)}"' if element_id else ""
    return f"<table{identifier}>{caption}<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>{_html_sources(table.source_references)}"


def _html_sources(references) -> str:
    ids = [reference.block_id or reference.section_id for reference in references]
    return f'<small class="source">Source: {escape(", ".join(ids))}</small>'


def _metric_value(metric) -> str:
    parts = [f"{metric.currency or ''}{metric.value}", metric.unit, metric.reporting_period]
    return " · ".join(str(part) for part in parts if part)


def render_docx(content: DOCXArtifactContent, *, is_mock: bool) -> bytes:
    document = Document()
    document.add_heading(content.document_title, 0)
    if is_mock:
        notice = document.add_paragraph(MOCK_NOTICE)
        if notice.runs:
            notice.runs[0].italic = True
    for section in content.sections:
        _docx_section(document, section)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _docx_section(document, section: DOCXArtifactSection | ArtifactSection) -> None:
    level = section.heading_level if isinstance(section, DOCXArtifactSection) else 1
    document.add_heading(section.heading, level=level)
    if isinstance(section, DOCXArtifactSection) and section.element_order:
        by_id = {
            item.element_id: (kind, item)
            for kind, collection in (("paragraph", section.paragraphs), ("bullet", section.bullet_points), ("metric", section.metrics), ("table", section.tables))
            for item in collection
            if item.element_id is not None
        }
        for element_id in section.element_order:
            kind, item = by_id[element_id]
            _docx_item(document, kind, item)
        for kind, collection in (("paragraph", section.paragraphs), ("bullet", section.bullet_points), ("metric", section.metrics), ("table", section.tables)):
            for item in collection:
                if item.element_id is None:
                    _docx_item(document, kind, item)
        return
    for item in section.paragraphs:
        _docx_item(document, "paragraph", item)
    for item in section.bullet_points:
        _docx_item(document, "bullet", item)
    if section.metrics:
        _docx_metrics_table(document, section.metrics)
    for item in section.tables:
        _docx_item(document, "table", item)


def _docx_item(document, kind: str, item) -> None:
    if kind == "paragraph":
        if item.element_type == "heading":
            document.add_heading(item.text, level=2)
        else:
            paragraph = document.add_paragraph(item.text)
            if item.element_type == "callout":
                paragraph.style = "Quote"
        document.add_paragraph(_source_label(item.source_references), style="Caption")
    elif kind == "bullet":
        document.add_paragraph(item.text, style="List Bullet")
        document.add_paragraph(_source_label(item.source_references), style="Caption")
    elif kind == "metric":
        _docx_metrics_table(document, [item])
    elif kind == "table":
        if item.caption:
            document.add_paragraph(item.caption, style="Caption")
        table = document.add_table(rows=1, cols=len(item.headers))
        table.style = "Table Grid"
        for cell, value in zip(table.rows[0].cells, item.headers):
            cell.text = value
        for row in item.rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                cell.text = value
        document.add_paragraph(_source_label(item.source_references), style="Caption")


def _docx_metrics_table(document, metrics) -> None:
    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, heading in zip(table.rows[0].cells, ("Metric", "Value", "Period", "Source")):
        cell.text = heading
    for item in metrics:
        cells = table.add_row().cells
        cells[0].text = item.name
        cells[1].text = f"{item.currency or ''}{item.value} {item.unit or ''}".strip()
        cells[2].text = item.reporting_period or ""
        cells[3].text = _source_label(item.source_references)


def _source_label(references) -> str:
    return "Source: " + ", ".join(reference.block_id or reference.section_id for reference in references)


def validate_rendered_output(content: bytes, target_format: str) -> None:
    if not content:
        raise ValueError("The renderer produced an empty file.")
    if target_format == "html":
        soup = BeautifulSoup(content, "html.parser")
        if soup.html is None or soup.title is None or soup.main is None or not soup.main.find(["section", "article", "aside", "nav"], recursive=True) and not soup.main.find("h2"):
            raise ValueError("The rendered HTML failed structural validation.")
        if soup.find("script") is not None:
            raise ValueError("Rendered HTML must not contain executable scripts.")
        return
    if target_format == "docx":
        document = Document(BytesIO(content))
        if not document.paragraphs or not any(paragraph.text.strip() for paragraph in document.paragraphs):
            raise ValueError("The rendered DOCX failed structural validation.")
        return
    if target_format == "pptx":
        validate_pptx_output(content)
        return
    raise ValueError("No renderer is available for this format.")
