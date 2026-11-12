import type {
  CreateInterpretationRequest,
  CreateTransformationPlanRequest,
  DocumentInterpretation,
  InterpretationListResponse,
  InterpretationOperationResponse,
  PlanListResponse,
  PlanOperationResponse,
  TransformationPlan,
} from '../types/interpretation'
import type { ArtifactOperationResponse, CreateArtifactRequest } from '../types/artifact'
import type {
  WorkflowDefinition,
  WorkflowDefinitionCreate,
  WorkflowEvent,
  WorkflowRun,
  WorkflowRunList,
  WorkflowRunRequest,
} from '../types/workflow_api'

export interface HealthResponse {
  name: string
  version: string
  status: string
  storage_available: boolean
  mock_llm: boolean
  llm_configured: boolean
}

export type DocumentFormat = 'pptx' | 'xlsx' | 'docx' | 'mmd' | 'html'

export interface DocumentMetadata {
  id: string
  filename: string
  format: DocumentFormat
  size_bytes: number
  sha256: string
  detected_mime: string
  uploaded_at: string
  extraction_status: 'complete'
  warnings: string[]
}

export interface IRBlock {
  id: string
  kind: 'text' | 'heading' | 'table' | 'list' | 'link' | 'formula' | 'diagram' | 'chart' | 'note'
  text: string
  level?: number | null
  table?: { headers: unknown[]; rows: unknown[][]; caption?: string | null } | null
  attributes: Record<string, unknown>
  source: {
    slide_number?: number | null
    sheet_name?: string | null
    cell_range?: string | null
    section_path: string[]
    paragraph_index?: number | null
    element_index?: number | null
    line_start?: number | null
    line_end?: number | null
    source_part?: string | null
  }
}

export interface IRSection {
  id: string
  title: string
  level: number
  order: number
  blocks: IRBlock[]
  children: IRSection[]
  source?: IRBlock['source'] | null
}

export interface DocumentIR {
  schema_version: string
  document_id: string
  source_format: DocumentFormat
  filename: string
  title: string
  metadata: Record<string, unknown>
  sections: IRSection[]
  blocks: IRBlock[]
  entities: Array<{ id: string; name: string; entity_type: string; attributes: Record<string, unknown>; source_locations: IRBlock['source'][] }>
  facts: Array<{ id: string; kind: string; subject: string; predicate: string; value: unknown; source_locations: IRBlock['source'][] }>
  metrics: Array<{ id: string; kind: string; subject: string; predicate: string; value: unknown; source_locations: IRBlock['source'][] }>
  claims: Array<{ id: string; kind: string; subject: string; predicate: string; value: unknown; source_locations: IRBlock['source'][] }>
  relationships: Array<{ source_entity_id: string; target_entity_id: string; relationship_type: string; source_locations: IRBlock['source'][] }>
  assets: Array<{ source_part: string; media_type?: string | null; size_bytes: number }>
  provenance: Array<{ extractor: string; extracted_at: string; source_format: string; details: Record<string, unknown> }>
  warnings: string[]
}

export type ApiErrorKind = 'validation' | 'provider' | 'network' | 'http' | 'response'

export class TransmuteApiError extends Error {
  constructor(
    message: string,
    readonly kind: ApiErrorKind,
    readonly status?: number,
    readonly code?: string,
    readonly requestId?: string,
  ) {
    super(message)
    this.name = 'TransmuteApiError'
  }
}

interface StructuredApiError {
  error?: {
    code?: string
    message?: string
    request_id?: string | null
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new TransmuteApiError(
      'The Transmute API could not be reached. Check the connection and try again.',
      'network',
    )
  }

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    payload = undefined
  }

  if (!response.ok) {
    const errorBody = isStructuredApiError(payload) ? payload.error : undefined
    const status = response.status
    const kind: ApiErrorKind = status === 422
      ? 'validation'
      : status === 502 || status === 503 || status === 504
        ? 'provider'
        : 'http'
    throw new TransmuteApiError(
      errorBody?.message ?? `The Transmute API request failed (${status}).`,
      kind,
      status,
      errorBody?.code,
      errorBody?.request_id ?? response.headers.get('X-Request-ID') ?? undefined,
    )
  }

  if (payload === undefined) {
    throw new TransmuteApiError('The Transmute API returned an unreadable response.', 'response', response.status)
  }
  return payload as T
}

function isStructuredApiError(value: unknown): value is StructuredApiError {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const error = value.error
  if (typeof error !== 'object' || error === null || Array.isArray(error)) return false
  const code = 'code' in error ? error.code : undefined
  const message = 'message' in error ? error.message : undefined
  const requestId = 'request_id' in error ? error.request_id : undefined
  return (code === undefined || typeof code === 'string')
    && (message === undefined || typeof message === 'string')
    && (requestId === undefined || requestId === null || typeof requestId === 'string')
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch('/health')
  if (!response.ok) throw new Error(`Health check failed (${response.status})`)
  return response.json() as Promise<HealthResponse>
}

export function uploadDocument(file: File, onProgress: (percent: number) => void): Promise<DocumentMetadata> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', '/api/documents/upload')
    request.responseType = 'json'
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
    }
    request.onerror = () => reject(new Error('Upload could not reach the Transmute API. Check the connection and try again.'))
    request.onabort = () => reject(new Error('Upload was cancelled.'))
    request.onload = () => {
      const body = request.response as DocumentMetadata | { error?: { message?: string } } | null
      if (request.status >= 200 && request.status < 300 && body && 'id' in body) {
        resolve(body)
        return
      }
      const message = body && 'error' in body ? body.error?.message : undefined
      reject(new Error(message || `Upload failed (${request.status || 'unknown status'}).`))
    }
    const formData = new FormData()
    formData.append('file', file)
    request.send(formData)
  })
}

export async function getDocumentIR(documentId: string): Promise<DocumentIR> {
  const response = await fetch(`/api/documents/${encodeURIComponent(documentId)}/ir`)
  const body = await response.json().catch(() => ({})) as DocumentIR | { error?: { message?: string } }
  if (!response.ok) {
    const message = 'error' in body ? body.error?.message : undefined
    throw new Error(message || `Could not load extracted structure (${response.status}).`)
  }
  return body as DocumentIR
}

/** Create an interpretation from the backend's stored IR; no result is fabricated client-side. */
export function createInterpretation(
  documentId: string,
  request: CreateInterpretationRequest = {},
): Promise<InterpretationOperationResponse> {
  return requestJson(
    `/api/documents/${encodeURIComponent(documentId)}/interpretations`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) },
  )
}

export function listInterpretations(documentId: string): Promise<InterpretationListResponse> {
  return requestJson(`/api/documents/${encodeURIComponent(documentId)}/interpretations`)
}

export function getInterpretation(
  documentId: string,
  interpretationId: string,
): Promise<DocumentInterpretation> {
  return requestJson(
    `/api/documents/${encodeURIComponent(documentId)}/interpretations/${encodeURIComponent(interpretationId)}`,
  )
}

export function createTransformationPlan(
  documentId: string,
  interpretationId: string,
  request: CreateTransformationPlanRequest,
): Promise<PlanOperationResponse> {
  return requestJson(
    `/api/documents/${encodeURIComponent(documentId)}/interpretations/${encodeURIComponent(interpretationId)}/plans`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) },
  )
}

export function listPlansForInterpretation(
  documentId: string,
  interpretationId: string,
): Promise<PlanListResponse> {
  return requestJson(
    `/api/documents/${encodeURIComponent(documentId)}/interpretations/${encodeURIComponent(interpretationId)}/plans`,
  )
}

export function listPlansForDocument(documentId: string): Promise<PlanListResponse> {
  return requestJson(`/api/documents/${encodeURIComponent(documentId)}/plans`)
}

export function getTransformationPlan(documentId: string, planId: string): Promise<TransformationPlan> {
  return requestJson(
    `/api/documents/${encodeURIComponent(documentId)}/plans/${encodeURIComponent(planId)}`,
  )
}

/** Generate and persist a native target document using the stored source IR and interpretation. */
export function createArtifactTransformation(
  documentId: string,
  request: CreateArtifactRequest,
): Promise<ArtifactOperationResponse> {
  return requestJson(
    `/api/documents/${encodeURIComponent(documentId)}/transformations`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) },
  )
}

/** Download a persisted artifact returned by the backend, surfacing structured API errors. */
export async function downloadArtifact(downloadUrl: string, filename: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(downloadUrl)
  } catch {
    throw new TransmuteApiError(
      'The output could not be reached. Check the connection and try again.',
      'network',
    )
  }

  if (!response.ok) {
    let payload: unknown
    try { payload = await response.json() } catch { payload = undefined }
    const errorBody = isStructuredApiError(payload) ? payload.error : undefined
    const status = response.status
    const kind: ApiErrorKind = status === 422
      ? 'validation'
      : status === 502 || status === 503 || status === 504
        ? 'provider'
        : 'http'
    throw new TransmuteApiError(
      errorBody?.message ?? `The output download failed (${status}).`,
      kind,
      status,
      errorBody?.code,
      errorBody?.request_id ?? response.headers.get('X-Request-ID') ?? undefined,
    )
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}

/** Validate and persist a workflow definition under the backend workflow store. */
export function createWorkflow(workflow: WorkflowDefinitionCreate): Promise<WorkflowDefinition> {
  return requestJson<WorkflowDefinition>('/api/workflows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(workflow),
  })
}

/** Retrieve a persisted workflow definition by ID. */
export function getWorkflow(workflowId: string): Promise<WorkflowDefinition> {
  return requestJson<WorkflowDefinition>(`/api/workflows/${encodeURIComponent(workflowId)}`)
}

/** Start an asynchronous DAG execution run for a workflow. */
export function startWorkflowRun(
  workflowId: string,
  request?: WorkflowRunRequest,
): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(`/api/workflows/${encodeURIComponent(workflowId)}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request ?? {}),
  })
}

/** Inspect the latest persisted snapshot of a workflow run. */
export function getWorkflowRun(workflowId: string, runId: string): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(
    `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`,
  )
}

/** List persisted runs for a workflow, newest first. */
export function listWorkflowRuns(workflowId: string): Promise<WorkflowRunList> {
  return requestJson<WorkflowRunList>(`/api/workflows/${encodeURIComponent(workflowId)}/runs`)
}

/**
 * Subscribe to the server-sent events (SSE) stream for real-time workflow run events.
 * Returns a teardown function that closes the EventSource and cleans up listeners.
 */
export function subscribeToWorkflowRunEvents(
  workflowId: string,
  runId: string,
  onEvent: (event: WorkflowEvent) => void,
  options?: {
    after?: number
    onEnd?: () => void
    onError?: (err: Event) => void
  },
): () => void {
  const query = options?.after !== undefined && options.after > 0 ? `?after=${options.after}` : ''
  const url = `/api/events/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}${query}`
  const eventSource = new EventSource(url)

  const handleCustomEvent = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as WorkflowEvent
      onEvent(data)
    } catch (err) {
      console.error('Failed to parse workflow SSE event data', err, e.data)
    }
  }

  const eventNames = [
    'run_queued',
    'run_started',
    'node_started',
    'node_completed',
    'node_failed',
    'node_blocked',
    'run_completed',
  ]

  for (const name of eventNames) {
    eventSource.addEventListener(name, handleCustomEvent as EventListener)
  }

  eventSource.onmessage = handleCustomEvent

  eventSource.addEventListener('end', () => {
    eventSource.close()
    options?.onEnd?.()
  })

  eventSource.onerror = (err) => {
    options?.onError?.(err)
  }

  return () => {
    for (const name of eventNames) {
      eventSource.removeEventListener(name, handleCustomEvent as EventListener)
    }
    eventSource.close()
  }
}
