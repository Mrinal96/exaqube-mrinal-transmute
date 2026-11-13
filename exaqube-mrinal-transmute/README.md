# Transmute

Transmute is an AI powered document transformation workspace for connecting source documents to new artefacts in a visual workflow. It supports five formats: PowerPoint (`.pptx`), Excel (`.xlsx`), Word (`.docx`), Mermaid (`.mmd`) and self contained HTML (`.html`). The product is intended to interpret source content and create a meaningfully different artefact, rather than perform a mechanical file conversion.

## Technology stack

- Frontend: React 19, TypeScript 5, Vite 8, Tailwind CSS 3, `@xyflow/react`, Lucide React and React Router.
- Backend: Python 3.12, FastAPI, Uvicorn, Pydantic 2 and Pydantic Settings.
- Deployment: separate frontend and backend containers with Docker Compose; Nginx serves the production frontend and proxies API and event requests.

## Architecture

The frontend owns canvas interaction and workflow editing state. The backend is organized around API routes, typed document/workflow models, a canonical intermediate representation, format specific readers, an LLM service boundary, DAG orchestration, output validation and persistent storage. The ingestion API validates and stores supported source documents, extracts their structure, and exposes metadata and IR. Interpretation and transformation planning use the LLM service; native artifact generation is implemented for HTML, DOCX and PPTX.

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

Interpretation and planning API operations are synchronous. They return a `run_id`; successful and failed operation outcome records, usage, and pricing details are persisted under the `outputs` volume. Input fingerprints reuse completed results. Optional idempotency keys are persisted and bound to the corresponding fingerprint. Per-fingerprint locks prevent duplicate provider calls within one backend process; they do not coordinate multiple workers or replicas.

Workflow definitions and run snapshots are persisted under the `outputs` volume. `POST /api/workflows` validates and creates a workflow; `POST /api/workflows/{workflow_id}/runs` starts execution and returns a run ID. Run status and node results are available from `GET /api/workflows/{workflow_id}/runs/{run_id}`; run history is available from `GET /api/workflows/{workflow_id}/runs`. The executor processes a validated DAG in topological order, supports branching, passes completed upstream artifacts to dependent nodes, and records node/run states and failures. Run states include queued, running, done and failed; node states include reading, interpreting, planning, rendering, validating, done, failed and blocked. A failed node blocks its downstream dependents while independent branches can continue. Execution is scheduled with FastAPI background tasks, not a durable worker queue, and nodes are not run in parallel.

`GET /api/events/workflows/{workflow_id}/runs/{run_id}` streams persisted run updates over Server-Sent Events and supports replay from a sequence ID. There is no workflow cancellation or restart/resume mechanism for an interrupted run.

`POST /api/documents/{document_id}/transformations` creates a native artifact for a supported target format. `GET /api/documents/{document_id}/outputs/{output_id}/download` downloads the persisted output.

Provider requests retry only classified retryable failures, up to `LLM_MAX_ATTEMPTS` (1-5, default 3), using bounded exponential backoff and provider timing hints. `LLM_MAX_RETRY_DELAY_SECONDS` defaults to 60 seconds and is capped at 60; a retry is skipped when the provider-requested wait exceeds the configured cap. Daily quota/billing errors, invalid provider JSON/schema output and permanent provider errors are not retried. Real-provider failures never fall back to mock mode.

Token usage is returned when the provider reports it. Estimated USD cost is calculated only when both `LLM_INPUT_COST_PER_MILLION_TOKENS`, `LLM_OUTPUT_COST_PER_MILLION_TOKENS`, and `LLM_PRICING_VERSION` are configured and token counts are present. Otherwise `estimated_cost` is `null`; the response includes the configured pricing rates/version, and no provider prices are hardcoded.

Initial backend tests can be run from `backend/` with `python -m pytest app/tests`. The ingestion suite creates small Office fixtures at runtime and does not require sample files in the repository.

## Current milestone capabilities

- Dark responsive workflow editor with draggable/zoomable canvas, minimap, controls, supported-format palette, document node states, properties and execution drawer.
- Validated upload for `.pptx`, `.xlsx`, `.docx`, `.mmd`, and `.html`, with a 10 MB limit, content-based type checking, and persistent per-document metadata and IR.
- PPTX, XLSX, DOCX, Mermaid, and HTML readers that preserve source locations, document order, tables, formulas, links, assets, and extraction warnings where supported.
- A Pydantic canonical IR with nested sections, text/table/formula/chart/diagram blocks, entity/fact/claim/relationship fields, asset references, and provenance.
- Upload progress, extraction feedback, structured errors, and an IR structure inspector in the existing workflow canvas.
- Health endpoint and same-origin frontend status check.
- LLM-backed semantic interpretation and target-specific transformation planning, with validated, separately persisted results and operation usage/cost metadata.
- Persisted workflow definitions and runs; validated DAG execution with topological ordering, branching, run/node states, downstream blocking on failure, and independent-branch continuation.
- SSE updates for workflow runs, including replay from a sequence ID, plus frontend Run Workflow integration and run-status refresh.
- Native HTML, DOCX, XLSX, MMD and editable PPTX artifact generation, output validation, persistent artifact storage and download endpoints. XLSX and MMD are deterministic exports from canonical IR and do not call an LLM; PPTX supports text, bullets, tables, metrics, and editable bar, line, and pie charts; image placeholders are rejected.
- Docker Compose setup with independent frontend/backend services and health checks.

## Known limitations

- HTML, DOCX and PPTX use target-specific LLM artifact contracts. XLSX and MMD are deterministic exports from canonical IR and do not apply transformation plans or user instructions, so those targets are exports rather than semantic conversions.
- Workflow nodes execute sequentially in one backend process through FastAPI background tasks. There is no durable job queue, parallel branch execution, cancellation endpoint, or automatic recovery/resume after a backend restart.
- Workflow definitions and run snapshots persist, but the frontend does not restore the saved workflow definition/canvas layout after a page reload. It can restore the last run reference and reload its status/events.
- PPTX charts are limited to validated bar, line, and single-series pie charts. Image placeholders remain unsupported. HTML chart and link plan components are explicitly rejected before artifact generation because the native HTML artifact contract does not yet carry their data.
- Per-fingerprint concurrency locks are process-local; use a durable coordination mechanism before running multiple backend workers or replicas.
- Embedded media are retained as source references rather than decoded or visually interpreted; remote HTML media are referenced but not downloaded.
- MMD output receives declaration, flowchart-direction, control-character, and subgraph-balance checks, not full Mermaid grammar validation; no Mermaid parser or CLI is installed in the backend image. Original MMD diagrams are preserved only when no additional IR structures need merging.
- XLSX formulas are written as executable formulas only when their source sheet/cell is known and the expression passes the writer's safe-function policy; other formulas are preserved as text with a workbook note. XLSX chart and diagram IR blocks are explicitly rejected.
- The upload endpoint does not run malware scanning. Storage is local and intended for this single-user assignment foundation.

