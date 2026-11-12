# Transmute

Transmute is an AI powered document transformation workspace for connecting source documents to new artefacts in a visual workflow. It supports five formats: PowerPoint (`.pptx`), Excel (`.xlsx`), Word (`.docx`), Mermaid (`.mmd`) and self contained HTML (`.html`). The product is intended to interpret source content and create a meaningfully different artefact, rather than perform a mechanical file conversion.

## Technology stack

- Frontend: React 19, TypeScript 5, Vite 8, Tailwind CSS 3, `@xyflow/react`, Lucide React and React Router.
- Backend: Python 3.12, FastAPI, Uvicorn, Pydantic 2 and Pydantic Settings.
- Deployment: separate frontend and backend containers with Docker Compose; Nginx serves the production frontend and proxies API and event requests.

## Architecture

The frontend owns canvas interaction and workflow editing state. The backend is organized around API routes, typed document/workflow models, a canonical intermediate representation, format specific readers, an LLM service boundary, DAG orchestration, output validation and persistent storage. The ingestion API validates and stores supported source documents, extracts their structure, and exposes metadata and IR. Semantic transformations are deliberately not implemented, and no output is presented as converted.

Nginx exposes the backend at `/health` and `/api/*` on the same origin as the frontend. Docker Compose uses a named volume for uploads and outputs and waits for backend health before starting the frontend.

## Folder structure

```text
frontend/       React application, canvas components and production Nginx config
backend/app/    FastAPI routes, core configuration, models and service boundaries
samples/        Sample input/output artefact locations
docs/           Design and architecture notes
docker-compose.yml
.env.example
```

## Start with Docker

1. Install Docker Desktop with its WSL2 integration enabled.
2. Optionally copy `.env.example` to `.env` and configure the LLM settings. Leave `MOCK_LLM=true` for a local setup without a provider. Mock results are explicitly labeled and contain no synthetic semantic analysis.
3. From the project root run:

   ```sh
   docker compose up --build
   ```

4. Open <http://localhost:3000>. The API is available at <http://localhost:8000/health> and through the frontend at <http://localhost:3000/health>.

The backend health response reports application name/version, API status, storage availability, mock mode and whether all LLM connection settings are configured. `llm_configured` does not imply that a live provider call has been made.

## Document ingestion API

- `POST /api/documents/upload` — multipart field `file`; validates both extension and detected package/content, extracts the IR, then persists the original upload plus metadata and IR.
- `GET /api/documents/{document_id}` — returns format, filename, size, detected MIME type, SHA-256, upload time, extraction status and warnings.
- `GET /api/documents/{document_id}/ir` — returns the canonical, source-located intermediate representation.

Uploads are capped at 10 MiB. PPTX files are limited to 40 slides and XLSX workbooks to 5,000 used rows in total across sheets. Error responses have the shape `{"error":{"code":"...","message":"...","request_id":"..."}}`. Source bytes and JSON sidecars are stored together in the persistent `uploads` volume under the generated UUID.

For local development, run the backend from `backend/` with `uvicorn app.main:app --reload --port 8000` after installing `requirements.txt`. Run the frontend from `frontend/` with `npm install` and `npm run dev`; the Vite proxy defaults to `localhost:8000` and accepts `VITE_API_PROXY_TARGET` when the backend runs elsewhere.

## Interpretation and planning APIs (M2.4)

- `POST /api/documents/{document_id}/interpretations` accepts optional `instructions` and `idempotency_key`; it loads the stored IR server-side, invokes interpretation synchronously, and returns an interpretation, reuse flag, run ID, token usage, and optional cost metadata.
- `GET /api/documents/{document_id}/interpretations` lists stored interpretations; `GET /api/documents/{document_id}/interpretations/{interpretation_id}` retrieves one while checking document ownership.
- `POST /api/documents/{document_id}/interpretations/{interpretation_id}/plans` accepts a required `target_format` and optional `instructions`/`idempotency_key`. It uses the server-stored IR and interpretation and returns the plan, reuse flag, run ID, usage, and optional cost metadata.
- `GET /api/documents/{document_id}/interpretations/{interpretation_id}/plans` lists plans for an interpretation; `GET /api/documents/{document_id}/plans` lists plans for a document; `GET /api/documents/{document_id}/plans/{plan_id}` retrieves a plan after checking its document association.

Operations are synchronous. They return a `run_id`; successful and failed operation outcome records, usage, and pricing details are persisted under the `outputs` volume. No queued, rendering, cancellation, or workflow execution status is exposed. Input fingerprints reuse completed results. Optional idempotency keys are persisted and bound to the corresponding fingerprint. Per-fingerprint locks prevent duplicate provider calls within one backend process; they do not coordinate multiple workers or replicas.

Provider requests retry only classified retryable failures, up to `LLM_MAX_ATTEMPTS` (1–5, default 3), using bounded exponential backoff and valid `Retry-After` hints. A retry is skipped when the provider's requested wait exceeds `LLM_MAX_RETRY_DELAY_SECONDS` (default 10, maximum 30), so the client never retries earlier than a valid server hint. Invalid provider JSON/schema output and permanent provider errors are not retried. Real-provider failures never fall back to mock mode.

Token usage is returned when the provider reports it. Estimated USD cost is calculated only when both `LLM_INPUT_COST_PER_MILLION_TOKENS`, `LLM_OUTPUT_COST_PER_MILLION_TOKENS`, and `LLM_PRICING_VERSION` are configured and token counts are present. Otherwise `estimated_cost` is `null`; the response includes the configured pricing rates/version, and no provider prices are hardcoded.

Initial backend tests can be run from `backend/` with `python -m pytest app/tests`. The ingestion suite creates small Office fixtures at runtime and does not require sample files in the repository.

## Current milestone capabilities

- Dark responsive workflow editor with draggable/zoomable canvas, minimap, controls, supported-format palette, document node states, properties and execution drawer.
- Validated upload for `.pptx`, `.xlsx`, `.docx`, `.mmd`, and `.html`, with a 10 MB limit, content-based type checking, and persistent per-document metadata and IR.
- PPTX, XLSX, DOCX, Mermaid, and HTML readers that preserve source locations, document order, tables, formulas, links, assets, and extraction warnings where supported.
- A Pydantic canonical IR with nested sections, text/table/formula/chart/diagram blocks, entity/fact/claim/relationship fields, asset references, and provenance.
- Upload progress, extraction feedback, structured errors, and an IR structure inspector in the existing workflow canvas.
- Health endpoint and same-origin frontend status check.
- Modular backend foundations for workflows, conversions, SSE events, logging, validation and semantic transformation. Interpretation and planning APIs are available; DAG execution and event streaming remain unimplemented.
- Docker Compose setup with independent frontend/backend services and health checks.

## Known limitations

- Workflow persistence, DAG execution and SSE event streaming are not yet implemented.
- The Run workflow action explains that execution is unavailable. Preview and download actions remain disabled until real outputs exist.
- Interpretation and planning APIs execute synchronously. Workflow execution, DAG scheduling, event streaming, cancellation and output writers remain unimplemented.
- Per-fingerprint concurrency locks are process-local; use a durable coordination mechanism before running multiple backend workers or replicas.
- The node canvas is currently in-memory and resets on page reload. Workflow controls and recent workflows are visual foundations.
- Embedded media are retained as source references rather than decoded or visually interpreted; remote HTML media are referenced but not downloaded.
- HTML and Mermaid checks verify text encoding and recognizable content/declarations; they do not implement full standards validators for either grammar.
- The upload endpoint does not run malware scanning. Storage is local and intended for this single-user assignment foundation.
- The build and Docker startup must be verified in an environment with Node.js, Python 3.12 and Docker Desktop installed.

