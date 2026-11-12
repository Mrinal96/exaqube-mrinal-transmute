import type { Edge } from '@xyflow/react'
import type { DocumentFlowNode, Format } from '../types/workflow'
import type {
  WorkflowDefinitionCreate,
  WorkflowEdgeDefinition,
  WorkflowNodeDefinition,
} from '../types/workflow_api'

export interface SerializedDAGResult {
  definition: WorkflowDefinitionCreate
  /** Maps backend internal node IDs (e.g. plan-output1, render-output1) to canvas node IDs */
  nodeToCanvasMap: Map<string, string>
  /** Maps canvas node IDs to all backend node IDs that represent its pipeline execution */
  canvasToNodesMap: Map<string, string[]>
}

/**
 * Serializes the current React Flow canvas nodes and edges into the backend
 * WorkflowDefinitionCreate payload adhering to docs/API_CONTRACT.md.
 *
 * Each connected source -> target pipeline branch is expanded into the typed DAG:
 *   source (document_id, source_format)
 *     -> interpretation
 *       -> planning (target_format, instruction)
 *         -> transformation (target_format, instruction)
 *           -> output (id matches canvas output node id)
 */
export function serializeDAGToWorkflow(
  nodes: DocumentFlowNode[],
  edges: Edge[],
  defaultDocumentId?: string,
  workflowName: string = 'Transmute Workflow',
): SerializedDAGResult {
  const backendNodes: WorkflowNodeDefinition[] = []
  const backendEdges: WorkflowEdgeDefinition[] = []
  const nodeToCanvasMap = new Map<string, string>()
  const canvasToNodesMap = new Map<string, string[]>()

  const sourceNodes = nodes.filter((n) => n.data.direction === 'source')
  const outputNodes = nodes.filter((n) => n.data.direction === 'output')

  // Track created interpretation nodes per source node ID so branched outputs reuse the same interpretation
  const interpretationNodeIds = new Map<string, string>()

  // 1. Process Source Nodes
  for (const src of sourceNodes) {
    const docId = src.data.documentId || defaultDocumentId || null
    const sourceNodeDef: WorkflowNodeDefinition = {
      id: src.id,
      kind: 'source',
      source_format: src.data.format,
      document_id: docId,
    }
    backendNodes.push(sourceNodeDef)
    nodeToCanvasMap.set(src.id, src.id)

    const associatedNodes = [src.id]

    // Create corresponding interpretation node for this source
    const interpId = `interp-${src.id}`
    interpretationNodeIds.set(src.id, interpId)

    const interpNodeDef: WorkflowNodeDefinition = {
      id: interpId,
      kind: 'interpretation',
    }
    if (src.data.interpretationId) {
      interpNodeDef.interpretation_id = src.data.interpretationId
    }
    backendNodes.push(interpNodeDef)
    backendEdges.push({ source: src.id, target: interpId })

    nodeToCanvasMap.set(interpId, src.id)
    associatedNodes.push(interpId)
    canvasToNodesMap.set(src.id, associatedNodes)
  }

  // 2. Process Output Nodes
  for (const out of outputNodes) {
    // Find the canvas edge feeding this output node
    const incomingEdge = edges.find((e) => e.target === out.id)
    const sourceCanvasId = incomingEdge ? incomingEdge.source : sourceNodes[0]?.id

    const interpId = sourceCanvasId ? interpretationNodeIds.get(sourceCanvasId) : undefined
    if (!interpId) {
      throw new Error(`Output node "${out.data.filename}" is not connected to a valid source document.`)
    }

    const planId = `plan-${out.id}`
    const renderId = `render-${out.id}`
    const outputId = out.id // Output node ID matches canvas node ID for direct correlation!

    const targetFormat = out.data.format as Format
    const instruction = out.data.instruction || ''

    // Planning node
    const planNodeDef: WorkflowNodeDefinition = {
      id: planId,
      kind: 'planning',
      target_format: targetFormat,
      instruction,
    }

    // Transformation node
    const renderNodeDef: WorkflowNodeDefinition = {
      id: renderId,
      kind: 'transformation',
      target_format: targetFormat,
      instruction,
    }

    // Final Output node
    const outputNodeDef: WorkflowNodeDefinition = {
      id: outputId,
      kind: 'output',
    }

    backendNodes.push(planNodeDef, renderNodeDef, outputNodeDef)

    // Pipeline edges: interp -> plan -> render -> output
    backendEdges.push(
      { source: interpId, target: planId },
      { source: planId, target: renderId },
      { source: renderId, target: outputId },
    )

    // Map internal backend nodes to this canvas output node
    nodeToCanvasMap.set(planId, out.id)
    nodeToCanvasMap.set(renderId, out.id)
    nodeToCanvasMap.set(outputId, out.id)

    canvasToNodesMap.set(out.id, [planId, renderId, outputId])
  }

  return {
    definition: {
      name: workflowName,
      nodes: backendNodes,
      edges: backendEdges,
    },
    nodeToCanvasMap,
    canvasToNodesMap,
  }
}
