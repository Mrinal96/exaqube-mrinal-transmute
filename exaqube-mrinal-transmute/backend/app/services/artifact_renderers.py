"""Native HTML and DOCX renderers plus output-file validation."""

from html import escape
from io import BytesIO

from bs4 import BeautifulSoup
from docx import Document

from app.models.artifacts import ArtifactSection, DOCXArtifactContent, HTMLArtifactContent
from app.services.pptx_writer import validate_pptx_output


MOCK_NOTICE = (
    "MOCK OUTPUT — no LLM interpretation or semantic transformation was performed. "
    "This file contains source content extracted from the uploaded document."
)


def render_html(content: HTMLArtifactContent, *, is_mock: bool) -> bytes:
    nav = "".join(
        f'<li><a href="#section-{index}">{escape(section.heading)}</a></li>'
        for index, section in enumerate(content.sections, start=1)
    )
    sections = "".join(
        _html_section(section, index)
        for index, section in enumerate(content.sections, start=1)
    )
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
<nav aria-label="Contents"><ul>{nav}</ul></nav><main>{sections}</main></body></html>"""
    return document.encode("utf-8")


def _html_section(section: ArtifactSection, index: int) -> str:
    paragraphs = "".join(
        f"<p>{escape(item.text)}{_html_sources(item.source_references)}</p>"
        for item in section.paragraphs
    )
    bullets = "".join(
        f"<li>{escape(item.text)}{_html_sources(item.source_references)}</li>"
        for item in section.bullet_points
    )
    bullet_html = f"<ul>{bullets}</ul>" if bullets else ""
    metrics = "".join(
        "<article class=\"metric\">"
        f"<span>{escape(item.name)}</span><strong>{escape(_metric_value(item))}</strong>"
        f"{_html_sources(item.source_references)}</article>"
        for item in section.metrics
    )
    metric_html = f'<div class="metrics">{metrics}</div>' if metrics else ""
    tables = "".join(_html_table(table) for table in section.tables)
    return (
        f'<section id="section-{index}"><h2>{escape(section.heading)}</h2>'
        f"{paragraphs}{bullet_html}{metric_html}{tables}</section>"
    )


def _html_table(table) -> str:
    caption = f"<caption>{escape(table.caption)}</caption>" if table.caption else ""
    headers = "".join(f"<th>{escape(value)}</th>" for value in table.headers)
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>"
        for row in table.rows
    )
    return f"<table>{caption}<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>{_html_sources(table.source_references)}"


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


def _docx_section(document, section: ArtifactSection) -> None:
    document.add_heading(section.heading, level=1)
    for item in section.paragraphs:
        document.add_paragraph(item.text)
        document.add_paragraph(_source_label(item.source_references), style="Caption")
    for item in section.bullet_points:
        document.add_paragraph(item.text, style="List Bullet")
        document.add_paragraph(_source_label(item.source_references), style="Caption")
    if section.metrics:
        table = document.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for cell, heading in zip(table.rows[0].cells, ("Metric", "Value", "Period", "Source")):
            cell.text = heading
        for item in section.metrics:
            cells = table.add_row().cells
            cells[0].text = item.name
            cells[1].text = f"{item.currency or ''}{item.value} {item.unit or ''}".strip()
            cells[2].text = item.reporting_period or ""
            cells[3].text = _source_label(item.source_references)
    for item in section.tables:
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


def _source_label(references) -> str:
    return "Source: " + ", ".join(reference.block_id or reference.section_id for reference in references)


def validate_rendered_output(content: bytes, target_format: str) -> None:
    if not content:
        raise ValueError("The renderer produced an empty file.")
    if target_format == "html":
        soup = BeautifulSoup(content, "html.parser")
        if soup.html is None or soup.title is None or soup.main is None or not soup.main.find("section"):
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
