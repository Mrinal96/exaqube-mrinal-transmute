import type { DocumentFormat } from '../services/api'
import type { ArtifactMetadata } from './artifact'
import type { LLMTokenUsage } from './interpretation'

export type WorkflowNodeKind = 'source' | 'interpretation' | 'planning' | 'transformation' | 'output'

export interface WorkflowNodeDefinition {
  id: string
  kind: WorkflowNodeKind
  source_format?: DocumentFormat | null
  target_format?: DocumentFormat | null
  document_id?: string | null
  interpretation_id?: string | null
  instruction?: string
}

export interface WorkflowEdgeDefinition {
  source: string
  target: string
}

export interface WorkflowDefinitionCreate {
  name?: string
  nodes: WorkflowNodeDefinition[]
  edges: WorkflowEdgeDefinition[]
}

export interface WorkflowDefinition {
  id: string
  name: string
  nodes: WorkflowNodeDefinition[]
  edges: WorkflowEdgeDefinition[]
}

export interface WorkflowRunRequest {
  document_id?: string | null
}

export type BackendRunStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export type BackendNodeStatus =
  | 'queued'
  | 'reading'
  | 'interpreting'
  | 'planning'
  | 'rendering'
  | 'validating'
  | 'done'
  | 'failed'
  | 'blocked'

export interface WorkflowNodeResult {
  node_id: string
  kind: WorkflowNodeKind
  status: BackendNodeStatus
  dependencies: string[]
  document_id?: string | null
  interpretation_id?: string | null
  plan_id?: string | null
  output?: ArtifactMetadata | null
  download_url?: string | null
  usage?: LLMTokenUsage | null
  error_code?: string | null
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface WorkflowEvent {
  sequence: number
  timestamp: string
  event: string
  status: string
  node_id?: string | null
  message: string
}

export interface WorkflowOutputReference {
  node_id: string
  output: ArtifactMetadata
  download_url: string
}

export interface WorkflowRun {
  run_id: string
  workflow_id: string
  request_id: string
  status: BackendRunStatus
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
  node_results: Record<string, WorkflowNodeResult>
  final_outputs: WorkflowOutputReference[]
  events: WorkflowEvent[]
}

export interface WorkflowRunList {
  items: WorkflowRun[]
  count: number
}
