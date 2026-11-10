from io import BytesIO

import pytest
from docx import Document as WordDocument
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pptx import Presentation

from app.config import Settings
from app.main import app
from app.models.documents import DocumentFormat
from app.models.intermediate import DocumentIR


def make_pptx(slides: int = 1) -> bytes:
    presentation = Presentation()
    for index in range(slides):
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = f"Slide {index + 1} heading"
        slide.placeholders[1].text = "A traceable slide paragraph."
        table = slide.shapes.add_table(2, 2, 0, 0, 2_000_000, 1_000_000).table
        table.cell(0, 0).text = "Metric"
        table.cell(0, 1).text = "Value"
        table.cell(1, 0).text = "Revenue"
        table.cell(1, 1).text = "$12"
    output = BytesIO()
    presentation.save(output)
    return output.getvalue()


def make_xlsx(rows: int = 2) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Metrics"
    sheet.append(["Metric", "Value", "Total"])
    for row in range(2, rows + 1):
        sheet.append([f"Item {row}", row * 2, f"=SUM(B{row}:B{row})"])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def make_docx() -> bytes:
    document = WordDocument()
    document.core_properties.title = "Ingestion report"
    document.add_heading("Overview", level=1)
    document.add_paragraph("A paragraph with source provenance.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Owner"
    table.cell(0, 1).text = "Status"
    table.cell(1, 0).text = "Sam"
    table.cell(1, 1).text = "Ready"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


SAMPLES = {
    "pptx": make_pptx,
    "xlsx": make_xlsx,
    "docx": make_docx,
    "mmd": lambda: b"flowchart TD\n  A[Start] --> B[Review]\n",
    "html": lambda: b"<!doctype html><html lang='en'><head><title>Plan</title></head><body><h1>Plan</h1><p>Review <a href='/guide'>the guide</a>.</p><table><tr><th>Step</th></tr><tr><td>Review</td></tr></table></body></html>",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.api import uploads

    monkeypatch.setattr(uploads, "get_settings", lambda: Settings(storage_root=tmp_path, max_upload_size_mb=10))
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("extension", ["pptx", "xlsx", "docx", "mmd", "html"])
def test_upload_and_ir_round_trip_all_supported_formats(client, extension):
    response = client.post(
        "/api/documents/upload",
        files={"file": (f"sample.{extension}", SAMPLES[extension](), "application/octet-stream")},
    )
    assert response.status_code == 201
    metadata = response.json()
    assert metadata["format"] == extension
    assert metadata["extraction_status"] == "complete"
    assert metadata["size_bytes"] > 0
    assert len(metadata["id"]) == 36

    document_response = client.get(f"/api/documents/{metadata['id']}")
    ir_response = client.get(f"/api/documents/{metadata['id']}/ir")
    assert document_response.status_code == 200
    assert ir_response.status_code == 200
    ir = DocumentIR.model_validate(ir_response.json())
    assert ir.document_id == metadata["id"]
    assert ir.source_format == extension
    assert ir.provenance


def test_reader_extraction_preserves_structure_and_locations(client):
    pptx = client.post("/api/documents/upload", files={"file": ("deck.pptx", make_pptx(), "")}).json()
    pptx_ir = client.get(f"/api/documents/{pptx['id']}/ir").json()
    assert pptx_ir["sections"][0]["title"] == "Slide 1 heading"
    assert any(block["kind"] == "table" for block in pptx_ir["sections"][0]["blocks"])
    assert pptx_ir["sections"][0]["source"]["slide_number"] == 1

    xlsx = client.post("/api/documents/upload", files={"file": ("metrics.xlsx", make_xlsx(), "")}).json()
    xlsx_ir = client.get(f"/api/documents/{xlsx['id']}/ir").json()
    assert xlsx_ir["sections"][0]["title"] == "Metrics"
    assert any(block["kind"] == "formula" for block in xlsx_ir["sections"][0]["blocks"])

    docx = client.post("/api/documents/upload", files={"file": ("report.docx", make_docx(), "")}).json()
    docx_ir = client.get(f"/api/documents/{docx['id']}/ir").json()
    assert docx_ir["sections"][0]["title"] == "Overview"
    assert any(block["kind"] == "table" for block in docx_ir["sections"][0]["blocks"])

    html = client.post("/api/documents/upload", files={"file": ("plan.html", SAMPLES["html"](), "")}).json()
    html_ir = client.get(f"/api/documents/{html['id']}/ir").json()
    assert html_ir["title"] == "Plan"
    assert any(block["kind"] == "link" for section in html_ir["sections"] for block in section["blocks"])
    assert any(block["kind"] == "table" for section in html_ir["sections"] for block in section["blocks"])

    mmd = client.post("/api/documents/upload", files={"file": ("map.mmd", SAMPLES["mmd"](), "")}).json()
    mmd_ir = client.get(f"/api/documents/{mmd['id']}/ir").json()
    assert mmd_ir["metadata"]["diagram_type"].lower() == "flowchart"
    assert mmd_ir["sections"][0]["blocks"][0]["source"]["line_start"] == 1


def test_unsupported_file_type_returns_structured_error(client):
    response = client.post("/api/documents/upload", files={"file": ("notes.pdf", b"%PDF-1.7", "application/pdf")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_format"
    assert "PPTX" in response.json()["error"]["message"]


@pytest.mark.parametrize("filename,content", [
    ("broken.pptx", b"not an Office zip"),
    ("wrong.html", b"just plain text"),
    ("broken.mmd", b"this is not a Mermaid diagram"),
])
def test_invalid_or_mismatched_content_is_rejected(client, filename, content):
    response = client.post("/api/documents/upload", files={"file": (filename, content, "application/octet-stream")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"invalid_office_package", "invalid_file_content"}


def test_declared_extension_must_match_detected_content(client):
    response = client.post("/api/documents/upload", files={"file": ("fake.docx", SAMPLES["html"](), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "file_type_mismatch"


def test_upload_size_is_limited_to_ten_megabytes(client):
    response = client.post("/api/documents/upload", files={"file": ("large.mmd", b" " * (10 * 1024 * 1024 + 1), "text/plain")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_presentation_slide_limit(client):
    response = client.post("/api/documents/upload", files={"file": ("too-many.pptx", make_pptx(41), "")})
    assert response.status_code == 422
    assert "maximum is 40" in response.json()["error"]["message"]


def test_spreadsheet_row_limit(client):
    response = client.post("/api/documents/upload", files={"file": ("too-many.xlsx", make_xlsx(5001), "")})
    assert response.status_code == 422
    assert "maximum is 5000" in response.json()["error"]["message"]


def test_missing_document_returns_structured_not_found(client):
    response = client.get("/api/documents/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


def test_ir_schema_rejects_missing_provenance_fields():
    with pytest.raises(ValueError):
        DocumentIR.model_validate({"source_format": DocumentFormat.HTML.value})
