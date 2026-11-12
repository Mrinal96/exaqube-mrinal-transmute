import type { Edge, Node } from '@xyflow/react'
import type { UsageSummary, LLMTokenUsage, ApiDecimal } from './interpretation'

export * from './workflow_api'

export type Format = 'pptx' | 'xlsx' | 'docx' | 'mmd' | 'html'

/**
 * Granular node execution lifecycle statuses for Transmute DAG workflows.
 */
export type NodeRunStatus =
  | 'idle'
  | 'queued'
  | 'reading'
  | 'interpreting'
  | 'rendering'
  | 'validating'
  | 'complete'
  | 'error'
  | 'cancelled'
  | 'blocked'

/**
 * RunStatus includes both granular DAG execution statuses and legacy alias states.
 */
export type RunStatus = NodeRunStatus | 'ready' | 'running'

export interface FormatInfo {
  id: Format
  label: string
  extension: string
  description: string
}

export interface DocumentNodeData extends Record<string, unknown> {
  format: Format
  filename: string
  status: RunStatus
  instruction: string
  direction: 'source' | 'output'
  /** Associated document ID from ingestion */
  documentId?: string
  /** Associated semantic interpretation ID (M2.2/M2.4) */
  interpretationId?: string
  /** Associated transformation plan ID (M2.3/M2.4) */
  planId?: string
  /** Generated artifact metadata ID (M3/M4) */
  artifactId?: string
  /** Download URL for generated artifact binary */
  downloadUrl?: string
  /** Source format feeding this output node */
  sourceFormat?: Format
  /** Specific error message if status is 'error' or 'blocked' */
  errorMessage?: string
  /** Execution progress percentage (0 - 100) */
  executionProgress?: number
  /** Backend run identifier */
  runId?: string
  /** Token usage statistics from LLM */
  usage?: UsageSummary | LLMTokenUsage | null
  /** Estimated cost of the operation */
  estimatedCost?: ApiDecimal | null
}

export type DocumentFlowNode = Node<DocumentNodeData, 'document'>
export type WorkflowEdge = Edge

export type DAGValidationErrorCode =
  | 'cycle_detected'
  | 'orphan_output'
  | 'missing_source'
  | 'incompatible_connection'
  | 'self_connection'
  | 'empty_workflow'

export interface DAGValidationError {
  code: DAGValidationErrorCode
  message: string
  nodeIds?: string[]
  edgeId?: string
}

export interface DAGValidationResult {
  isValid: boolean
  errors: DAGValidationError[]
  warnings: string[]
}
