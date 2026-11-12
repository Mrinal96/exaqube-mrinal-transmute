import type { RunStatus } from './workflow'

/**
 * Extended execution status type covering all pipeline phases.
 * Superset of RunStatus; components can use either.
 */
export type ExecutionStatus =
  | RunStatus
  | 'queued'
  | 'reading'
  | 'interpreting'
  | 'rendering'
  | 'validating'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'blocked'

/**
 * Represents a single log entry in the execution timeline.
 * Designed to be populated from future SSE events or mock data for empty-state rendering.
 */
export interface ExecutionLogEntry {
  /** Unique identifier for the log entry. */
  id: string
  /** Timestamp as ISO string. */
  timestamp: string
  /** Current phase/status of this step. */
  status: ExecutionStatus
  /** Human-readable message describing this step. */
  message: string
  /** Optional node ID this entry relates to. */
  nodeId?: string
  /** Optional node label for display. */
  nodeLabel?: string
  /** Optional duration in milliseconds. */
  durationMs?: number
  /** Optional error details for failed steps. */
  error?: string
  /** Optional structured details (key-value metadata). */
  details?: Record<string, string | number | boolean>
}

/**
 * Top-level execution run summary.
 * Models a single workflow execution attempt.
 */
export interface ExecutionRun {
  /** Unique run identifier. */
  id: string
  /** Overall run status. */
  status: ExecutionStatus
  /** ISO timestamp when the run started. */
  startedAt: string
  /** ISO timestamp when the run finished (if complete). */
  finishedAt?: string
  /** Total duration in milliseconds. */
  durationMs?: number
  /** Number of nodes processed. */
  nodesProcessed: number
  /** Total nodes in the workflow. */
  nodesTotal: number
  /** Estimated cost for this run. */
  estimatedCost?: number
  /** Ordered log entries for this run. */
  entries: ExecutionLogEntry[]
  /** Error message if the run failed. */
  error?: string
}

/**
 * All possible execution pipeline phases as a strict ordered sequence.
 * Used to render the pipeline stage indicator.
 */
export const EXECUTION_PHASES = [
  'queued',
  'reading',
  'interpreting',
  'rendering',
  'validating',
  'done',
] as const

export type ExecutionPhase = typeof EXECUTION_PHASES[number]

/**
 * Maps an execution phase to a human-readable description.
 */
export const phaseDescriptions: Record<ExecutionPhase, string> = {
  queued: 'Waiting to start processing',
  reading: 'Reading and parsing source documents',
  interpreting: 'AI interpreting document content',
  rendering: 'Generating output artefacts',
  validating: 'Validating generated outputs',
  done: 'Execution complete',
}
