import type { Connection, Edge } from '@xyflow/react'
import type {
  DAGValidationError,
  DAGValidationResult,
  DocumentFlowNode,
} from '../types/workflow'

/**
 * Validates an individual connection candidate before the user creates an edge.
 */
export function validateConnectionCandidate(
  connection: Connection | Edge,
  nodes: DocumentFlowNode[],
  edges: Edge[],
): { valid: boolean; reason?: string } {
  if (!connection.source || !connection.target) {
    return { valid: false, reason: 'Source and target must both be specified.' }
  }

  // 1. Disallow self connections
  if (connection.source === connection.target) {
    return { valid: false, reason: 'A node cannot connect to itself.' }
  }

  const sourceNode = nodes.find((n) => n.id === connection.source)
  const targetNode = nodes.find((n) => n.id === connection.target)

  if (!sourceNode || !targetNode) {
    return { valid: false, reason: 'Connected nodes must exist in the canvas.' }
  }

  // 2. Disallow source-to-source connections
  if (sourceNode.data.direction === 'source' && targetNode.data.direction === 'source') {
    return { valid: false, reason: 'Cannot connect a source document directly to another source document.' }
  }

  // 3. Disallow duplicate edges
  const existingEdge = edges.find(
    (e) => e.source === connection.source && e.target === connection.target,
  )
  if (existingEdge) {
    return { valid: false, reason: 'This connection already exists.' }
  }

  // 4. Disallow connection that would introduce a cycle
  const wouldCreateCycle = hasCycleWithNewEdge(nodes, edges, connection.source, connection.target)
  if (wouldCreateCycle) {
    return { valid: false, reason: 'Connection rejected: DAG workflows cannot contain cycles.' }
  }

  return { valid: true }
}

/**
 * Checks if adding edge (sourceId -> targetId) introduces a cycle using DFS.
 */
function hasCycleWithNewEdge(
  nodes: DocumentFlowNode[],
  edges: Edge[],
  newSourceId: string,
  newTargetId: string,
): boolean {
  // Build adjacency list including candidate edge
  const adj = new Map<string, string[]>()
  for (const node of nodes) {
    adj.set(node.id, [])
  }
  for (const edge of edges) {
    if (adj.has(edge.source)) {
      adj.get(edge.source)!.push(edge.target)
    }
  }
  if (adj.has(newSourceId)) {
    adj.get(newSourceId)!.push(newTargetId)
  }

  // DFS cycle detection
  const visited = new Set<string>()
  const inStack = new Set<string>()

  function dfs(curr: string): boolean {
    visited.add(curr)
    inStack.add(curr)

    const neighbors = adj.get(curr) || []
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        if (dfs(neighbor)) return true
      } else if (inStack.has(neighbor)) {
        return true
      }
    }

    inStack.delete(curr)
    return false
  }

  for (const node of nodes) {
    if (!visited.has(node.id)) {
      if (dfs(node.id)) return true
    }
  }

  return false
}

/**
 * Validates the full DAG workflow on the canvas.
 * Checks for:
 * 1. Empty workflow
 * 2. Missing source nodes
 * 3. Cycles in the graph
 * 4. Disconnected / orphan output nodes
 * 5. Incompatible connections
 */
export function validateDAG(
  nodes: DocumentFlowNode[],
  edges: Edge[],
): DAGValidationResult {
  const errors: DAGValidationError[] = []
  const warnings: string[] = []

  // Check 1: Empty workflow
  if (nodes.length === 0) {
    return {
      isValid: false,
      errors: [
        {
          code: 'empty_workflow',
          message: 'The canvas is empty. Add a source document and target nodes.',
        },
      ],
      warnings: [],
    }
  }

  const sourceNodes = nodes.filter((n) => n.data.direction === 'source')
  const outputNodes = nodes.filter((n) => n.data.direction === 'output')

  // Check 2: Missing source nodes
  if (sourceNodes.length === 0 && outputNodes.length > 0) {
    errors.push({
      code: 'missing_source',
      message: 'Workflow contains output nodes but no source document. Upload a source document to execute.',
      nodeIds: outputNodes.map((n) => n.id),
    })
  }

  // Check 3: Cycle detection across all edges
  const adj = new Map<string, string[]>()
  const inDegree = new Map<string, number>()
  for (const node of nodes) {
    adj.set(node.id, [])
    inDegree.set(node.id, 0)
  }

  for (const edge of edges) {
    if (edge.source === edge.target) {
      errors.push({
        code: 'self_connection',
        message: `Self-connection detected on node "${edge.source}".`,
        nodeIds: [edge.source],
        edgeId: edge.id,
      })
    }

    if (adj.has(edge.source) && adj.has(edge.target)) {
      adj.get(edge.source)!.push(edge.target)
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1)
    }
  }

  const visited = new Set<string>()
  const inStack = new Set<string>()
  const cycleNodes: string[] = []

  function detectCyclesDFS(curr: string, path: string[]): boolean {
    visited.add(curr)
    inStack.add(curr)
    path.push(curr)

    const neighbors = adj.get(curr) || []
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        if (detectCyclesDFS(neighbor, path)) return true
      } else if (inStack.has(neighbor)) {
        const cycleStartIndex = path.indexOf(neighbor)
        cycleNodes.push(...path.slice(cycleStartIndex))
        return true
      }
    }

    path.pop()
    inStack.delete(curr)
    return false
  }

  for (const node of nodes) {
    if (!visited.has(node.id)) {
      if (detectCyclesDFS(node.id, [])) {
        errors.push({
          code: 'cycle_detected',
          message: 'Cycle detected in workflow. Directed Acyclic Graphs cannot contain feedback loops.',
          nodeIds: Array.from(new Set(cycleNodes)),
        })
        break
      }
    }
  }

  // Check 4: Disconnected / orphan output nodes
  // Trace reachability from any source node
  const reachableFromSource = new Set<string>()
  function markReachable(sourceId: string) {
    const queue = [sourceId]
    while (queue.length > 0) {
      const current = queue.shift()!
      if (!reachableFromSource.has(current)) {
        reachableFromSource.add(current)
        for (const next of adj.get(current) || []) {
          queue.push(next)
        }
      }
    }
  }

  for (const sNode of sourceNodes) {
    markReachable(sNode.id)
  }

  const orphanOutputs: string[] = []
  for (const outNode of outputNodes) {
    const incomingCount = inDegree.get(outNode.id) || 0
    if (incomingCount === 0 || !reachableFromSource.has(outNode.id)) {
      orphanOutputs.push(outNode.id)
    }
  }

  if (orphanOutputs.length > 0) {
    errors.push({
      code: 'orphan_output',
      message: `${orphanOutputs.length} output node${
        orphanOutputs.length > 1 ? 's are' : ' is'
      } disconnected from any source document.`,
      nodeIds: orphanOutputs,
    })
  }

  // Check 5: Warnings for unused source documents
  for (const sNode of sourceNodes) {
    const outgoing = adj.get(sNode.id) || []
    if (outgoing.length === 0) {
      warnings.push(`Source document "${sNode.data.filename}" is not connected to any output transformations.`)
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
  }
}
