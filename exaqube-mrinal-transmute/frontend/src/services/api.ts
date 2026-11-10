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
  relationships: Array<{ source_entity_id: string; target_entity_id: string; relationship_type: string; source_locations: IRBlock['source'][] }>
  assets: Array<{ source_part: string; media_type?: string | null; size_bytes: number }>
  provenance: Array<{ extractor: string; extracted_at: string; source_format: string; details: Record<string, unknown> }>
  warnings: string[]
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

