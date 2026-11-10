# Architecture notes

The web client sends uploads and future workflow API requests to the same origin. In production, Nginx proxies `/api/` to the FastAPI service. The API is split into route namespaces (`uploads`, `conversions`, `workflows`, `events`) and service modules so semantic transformation and DAG execution can be added without coupling the UI to file parsing details.

`POST /api/documents/upload` accepts at most 10 MiB, detects actual content type, extracts a source into the canonical Pydantic `DocumentIR`, and persists the original bytes, metadata, and IR together under a UUID directory in the upload volume. `GET /api/documents/{document_id}` returns metadata; `GET /api/documents/{document_id}/ir` returns the stored extraction. An upload is successful only after extraction and persistence complete.

The reader modules normalize the five source formats while recording locations such as slide numbers, sheet names and cell ranges, Word section paths, HTML element order, and Mermaid line numbers. The IR includes entity, fact, claim, relationship, asset, provenance, and warning fields. Readers preserve directly represented facts such as workbook formulas; they do not infer semantic claims or entities from prose. Original files remain stored alongside IR so embedded media references and future extraction needs remain traceable.

A future run should validate a workflow DAG, read and normalize the source, use a separately configured semantic interpretation stage, validate each generated output, and persist artefacts. This milestone does not invoke the LLM service or create conversion outputs.

