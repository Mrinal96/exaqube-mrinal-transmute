"""Extract slide-ordered content from PowerPoint presentations."""

from io import BytesIO
from zipfile import ZipFile

from pptx import Presentation

from app.models.intermediate import AssetReference, DocumentIR, SourceLocation, TableData
from app.readers.common import base_ir, make_block, make_section
from app.readers.errors import ExtractionLimitError

MAX_SLIDES = 40


def read_pptx(content: bytes, document_id: str, filename: str) -> DocumentIR:
    presentation = Presentation(BytesIO(content))
    slide_count = len(presentation.slides)
    if slide_count > MAX_SLIDES:
        raise ExtractionLimitError(f"Presentation has {slide_count} slides; the maximum is {MAX_SLIDES}.")

    core = presentation.core_properties
    ir = base_ir(
        document_id,
        filename,
        "pptx",
        "pptx_reader",
        title=core.title or "",
        metadata={"slide_count": slide_count, "author": core.author or "", "subject": core.subject or "", "created": core.created.isoformat() if core.created else None},
    )
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_title = slide.shapes.title.text.strip() if slide.shapes.title and slide.shapes.title.text else f"Slide {slide_number}"
        location = SourceLocation(slide_number=slide_number, source_part=f"ppt/slides/slide{slide_number}.xml")
        section = make_section(f"slide-{slide_number}", slide_title, order=slide_number - 1, source=location)
        ir.sections.append(section)
        if slide.shapes.title and slide.shapes.title.text.strip():
            section.blocks.append(make_block(f"slide-{slide_number}-title", "heading", slide_title, location, level=1))
        for shape_index, shape in enumerate(slide.shapes):
            shape_location = SourceLocation(slide_number=slide_number, element_index=shape_index, source_part=f"ppt/slides/slide{slide_number}.xml")
            if shape.has_text_frame and shape.text.strip() and not (shape == slide.shapes.title):
                section.blocks.append(make_block(f"slide-{slide_number}-text-{shape_index}", "text", shape.text.strip(), shape_location, attributes={"shape_type": str(shape.shape_type)}))
            if shape.has_table:
                table = shape.table
                matrix = [[cell.text.strip() for cell in row.cells] for row in table.rows]
                headers = matrix[0] if matrix else []
                section.blocks.append(make_block(
                    f"slide-{slide_number}-table-{shape_index}", "table", source=shape_location,
                    table=TableData(headers=headers, rows=matrix[1:] if matrix else []),
                    attributes={"row_count": len(matrix), "column_count": len(headers)},
                ))
            if shape.has_chart:
                chart = shape.chart
                chart_data = []
                for plot in chart.plots:
                    categories = [str(category.label) for category in plot.categories]
                    for series in plot.series:
                        chart_data.append({"series": series.name, "categories": categories, "values": list(series.values)})
                section.blocks.append(make_block(
                    f"slide-{slide_number}-chart-{shape_index}", "chart", source=shape_location,
                    attributes={
                        "title": chart.chart_title.text_frame.text.strip() if chart.has_title else "",
                        "chart_type": str(chart.chart_type),
                        "series": chart_data,
                    },
                ))
        try:
            notes_frame = slide.notes_slide.notes_text_frame
            notes = notes_frame.text.strip() if notes_frame else ""
            if notes:
                section.blocks.append(make_block(f"slide-{slide_number}-notes", "note", notes, location))
        except (AttributeError, KeyError):
            ir.warnings.append(f"Notes for slide {slide_number} could not be read.")

    with ZipFile(BytesIO(content)) as archive:
        for part in archive.namelist():
            if part.startswith("ppt/media/") and not part.endswith("/"):
                info = archive.getinfo(part)
                ir.assets.append(AssetReference(source_part=part, size_bytes=info.file_size))
    if ir.assets:
        ir.warnings.append("Embedded presentation media are referenced in the IR; image and audio contents are not interpreted.")
    if not ir.title:
        ir.title = next((section.title for section in ir.sections if section.title != "Slide 1"), filename)
    return ir
