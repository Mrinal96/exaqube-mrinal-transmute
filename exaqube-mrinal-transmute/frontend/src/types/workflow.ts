import type { Edge, Node } from '@xyflow/react'

export type Format = 'pptx' | 'xlsx' | 'docx' | 'mmd' | 'html'
export type RunStatus = 'idle' | 'ready' | 'running' | 'complete' | 'error'

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
}

export type DocumentFlowNode = Node<DocumentNodeData, 'document'>
export type WorkflowEdge = Edge

