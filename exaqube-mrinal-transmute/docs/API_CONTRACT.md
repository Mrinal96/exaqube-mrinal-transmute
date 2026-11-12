# Workflow DAG API Contract

Workflow definitions and run snapshots are stored under the backend `STORAGE_ROOT/outputs/workflows` directory. Rendered artifacts continue to use the existing artifact store under `STORAGE_ROOT/outputs/artifacts`; in Docker Compose both are covered by the `outputs` volume.

All endpoints use the configured API prefix (default `/api`) and JSON request/response bodies, except the SSE stream.

## Transformation plan destination contract

DOCX transformation plans use schema version `2.0` and the current transformation prompt version `transformation_v9`. A DOCX output structure contains only its sections and nested elements; these objects do not contain `mapping_ids`. Every `content_mappings[]` item has one required `destination` with `target_type` set to `doc_section` or `doc_element`, and `target_id` set to the exact declared `section_id` or `element_id`. A mapping is placed only through this destination. For PPTX, XLSX, MMD, and HTML, every mapping ID must appear exactly once in the output structure, and its `destination.target_type` and `destination.target_id` must match the precise structure location containing it. The API rejects mismatched or unknown destinations, duplicate mapping IDs, missing destinations, invalid source references, and incomplete semantic accounting.

Previously persisted DOCX plans that use the old outline `mapping_ids` contract are not silently converted. Reading such a plan returns `409 Conflict` with `error.code = "incompatible_stored_plan"`; other target formats retain their existing plan schema version.

## Workflow node model

`WorkflowDefinition` responses contain `id`, `name`, `nodes`, and `edges`. Each node contains:

| Field | Meaning |
| --- | --- |
| `id` | Unique ID within the workflow. |
| `kind` | `source`, `interpretation`, `planning`, `transformation`, or `output`. |
| `document_id` | Required on source nodes or supplied at run start to bind unassigned source nodes. |
| `source_format` | Optional assertion checked against the uploaded source. |
| `target_format` | Required for `planning` and `transformation` nodes; one of `pptx`, `xlsx`, `docx`, `mmd`, `html`. |
| `interpretation_id` | Optional stored interpretation ID for an interpretation node. If omitted, the existing InterpretationService creates/reuses one. |
| `instruction` | Optional node-specific instructions, max 8,000 characters. |

An edge is `{ "source": "node-id", "target": "node-id" }`. Supported connections are source→interpretation, source→transformation, interpretation→planning, interpretation→transformation, planning→transformation, and transformation→output. A transformation must have exactly one upstream source and interpretation and may have at most one upstream plan. An output node must have exactly one transformation dependency. Definitions must include an output node.

## Create and retrieve workflows

### `POST /api/workflows` — 201 Created

Request:

```json
{
  "name": "HTML to Word",
  "nodes": [
    {"id": "source", "kind": "source", "document_id": "<document-uuid>", "source_format": "html"},
    {"id": "interpret", "kind": "interpretation"},
    {"id": "plan", "kind": "planning", "target_format": "docx", "instruction": "Create a concise report."},
    {"id": "render", "kind": "transformation", "target_format": "docx"},
    {"id": "output", "kind": "output"}
  ],
  "edges": [
    {"source": "source", "target": "interpret"},
    {"source": "interpret", "target": "plan"},
    {"source": "plan", "target": "render"},
    {"source": "render", "target": "output"}
  ]
}
```

The response is the persisted `WorkflowDefinition`, including a server-generated UUID `id`. A source node may omit `document_id`; in that case provide it in the run request.

### `GET /api/workflows/{workflow_id}` — 200 OK

Returns the persisted definition. Unknown workflow IDs return 404; malformed IDs return 400.

## Start, inspect, and list runs

### `POST /api/workflows/{workflow_id}/runs` — 202 Accepted

Request (all fields optional; send `{}` when nodes already contain their document IDs):

```json
{"document_id": "<document-uuid>"}
```

`document_id` binds source nodes whose definition omitted that field. The response is the initial persisted `WorkflowRun` snapshot with status `queued`, a new `run_id`, `request_id`, queued node results, and the first event. The response includes a `Location` header for the status URL. Execution continues as a FastAPI background task.

### `GET /api/workflows/{workflow_id}/runs/{run_id}` — 200 OK

Returns the latest persisted run snapshot:

- Run status: `queued`, `running`, `done`, or `failed`.
- Per-node status: `queued`, `reading`, `interpreting`, `planning`, `rendering`, `validating`, `done`, `failed`, or `blocked`.
- `node_results`: dependencies, source document ID, interpretation/plan IDs, token usage, sanitized error information, intermediate artifact metadata, and download URL where an artifact exists.
- `final_outputs`: `{node_id, output, download_url}` references for artifacts that passed output-node validation.
- `events`: ordered, persisted event records with sequence numbers and timestamps.

### `GET /api/workflows/{workflow_id}/runs` — 200 OK

Returns `{ "items": [...], "count": n }` for persisted runs, newest first.

## Execution events

### `GET /api/events/workflows/{workflow_id}/runs/{run_id}` — `text/event-stream`

The SSE stream replays persisted events after the optional `after` query parameter or `Last-Event-ID` header, then polls for subsequent events until the run reaches a terminal state. Each event includes an SSE `id`, an event name, and JSON `data`. Nginx buffering is disabled for `/api` proxy traffic.

## Download outputs

Each completed output node contains `download_url`, and each final artifact appears in `final_outputs`. Download uses the existing API:

### `GET /api/documents/{document_id}/outputs/{output_id}/download`

Returns the native file with its generated filename. Artifacts remain available after backend restarts as long as the Compose `outputs` volume is retained.

## Validation and execution behavior

- Invalid definitions return 422 with `error.code = "invalid_workflow"`; checks include duplicate/missing IDs, missing dependencies, duplicate/self edges, incompatible connections, and cycles.
- Missing workflows/runs return 404. Missing or invalid uploaded documents use the existing document API error behavior.
- Nodes execute in stable topological order. Each downstream node receives typed outputs from its dependency nodes (IR, interpretation, optional plan, or artifact metadata). A failed node marks its dependent descendants `blocked`; independent branches continue. Overall run status is `failed` if any node failed or was blocked.
- A planning node calls the existing PlanningService. Its persisted plan is passed to the existing artifact transformation service as generation guidance. Interpretation and artifacts remain in their existing separate stores.
- Native artifact rendering is currently registered for HTML, DOCX, and PPTX. XLSX and MMD remain planning-only and fail with `target_renderer_unavailable`; no success artifact is fabricated. See [Artifact contract architecture](ARTIFACT_CONTRACTS.md) for the schema, prompt, writer, validation, and versioning contract.
- Execution is sequential within a run. There is no cancellation, resume, parallel branch scheduler, or cross-process job queue. FastAPI background tasks are process-local; run state itself is persistent, but an abrupt process termination can leave a run `running` without a worker to resume it.
