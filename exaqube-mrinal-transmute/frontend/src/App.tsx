import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow, addEdge, useEdgesState, useNodesState, type Connection, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './ingestion.css'
import { Activity, AlertCircle, AlertTriangle, Brain, CheckCircle2, ChevronDown, ChevronRight, Cloud, Command, FileOutput, HelpCircle, LoaderCircle, PanelRightClose, Play, Save, Search, Share2, Sliders, Upload, Wand2, WandSparkles, X } from 'lucide-react'
import { Sidebar } from './components/layout/Sidebar'
import DocumentNode from './components/nodes/DocumentNode'
import { ExecutionPanel } from './components/panels/ExecutionPanel'
import { FormatPalette } from './components/panels/FormatPalette'
import { PropertiesPanel } from './components/panels/PropertiesPanel'
import { InterpretationPanel } from './components/panels/InterpretationPanel'
import { TransformationPlanPanel } from './components/panels/TransformationPlanPanel'
import type { DocumentFlowNode, Format, RunStatus } from './types/workflow'
import {
  createWorkflow,
  getDocumentIR,
  getHealth,
  getWorkflowRun,
  startWorkflowRun,
  subscribeToWorkflowRunEvents,
  uploadDocument,
  type DocumentFormat,
  type DocumentIR,
  type DocumentMetadata,
} from './services/api'
import type { DocumentInterpretation, TransformationPlan } from './types/interpretation'
import type { ArtifactOperationResponse } from './types/artifact'
import type { ExecutionLogEntry, ExecutionRun, ExecutionStatus } from './types/execution'
import type { WorkflowEvent, WorkflowRun } from './types/workflow_api'
import { serializeDAGToWorkflow, type SerializedDAGResult } from './utils/workflowSerializer'
import { formatColors } from './utils/formats'
import { DocumentInspector } from './components/panels/DocumentInspector'
import { UploadFeedback, type UploadPhase } from './components/panels/UploadFeedback'
import { TransformationPanel } from './components/panels/TransformationPanel'
import { validateConnectionCandidate, validateDAG } from './utils/dagValidation'

const nodeTypes = { document: DocumentNode }
const initialNodes: DocumentFlowNode[] = []

type RightPanelTab = 'properties' | 'interpretation' | 'plan' | 'transform'

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState<DocumentFlowNode>(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selected, setSelected] = useState<string>()
  const [panelOpen, setPanelOpen] = useState(true)
  const [rightTab, setRightTab] = useState<RightPanelTab>('properties')
  const [activeInterpretation, setActiveInterpretation] = useState<DocumentInterpretation | null>(null)
  const [activePlan, setActivePlan] = useState<TransformationPlan | null>(null)
  const [logOpen, setLogOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [apiConnected, setApiConnected] = useState(false)
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>()
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState<string>()
  const [uploadedDocument, setUploadedDocument] = useState<DocumentMetadata>()
  const [documentIR, setDocumentIR] = useState<DocumentIR>()
  const [documentsMap, setDocumentsMap] = useState<Record<string, DocumentMetadata>>({})
  const [documentIRMap, setDocumentIRMap] = useState<Record<string, DocumentIR>>({})
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [currentRun, setCurrentRun] = useState<ExecutionRun | undefined>()
  const [runHistory, setRunHistory] = useState<ExecutionRun[]>(() => {
    try {
      const saved = localStorage.getItem('transmute_run_history')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })
  const [isRunning, setIsRunning] = useState(false)
  const [savedWorkflowId, setSavedWorkflowId] = useState<string | null>(null)
  const [isSaved, setIsSaved] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const sseCleanupRef = useRef<(() => void) | null>(null)
  const activeNodeMapRef = useRef<Map<string, string>>(new Map())
  const fileInput = useRef<HTMLInputElement>(null)
  const selectedNode = nodes.find((node) => node.id === selected)

  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes)
      setIsSaved(false)
    },
    [onNodesChange],
  )

  const handleEdgesChange = useCallback(
    (changes: Parameters<typeof onEdgesChange>[0]) => {
      onEdgesChange(changes)
      setIsSaved(false)
      const hasRemoval = changes.some((c) => c.type === 'remove')
      if (hasRemoval) {
        setTimeout(() => {
          setEdges((currentEdges) => {
            setNodes((currentNodes) =>
              currentNodes.map((n) => {
                if (n.data.direction !== 'output') return n
                const hasIncoming = currentEdges.some((e) => e.target === n.id)
                if (!hasIncoming && n.data.status === 'ready') {
                  return {
                    ...n,
                    data: {
                      ...n.data,
                      sourceFormat: undefined,
                      status: 'idle' as const,
                    },
                  }
                }
                return n
              }),
            )
            return currentEdges
          })
        }, 0)
      }
    },
    [onEdgesChange, setEdges, setNodes],
  )

  const addNode = useCallback((format: Format, direction: 'source' | 'output' = 'output') => {
    const id = `${format}-${Date.now()}`
    const formatLabel = format.toUpperCase()
    const data = { format, filename: direction === 'source' ? `Untitled source.${format}` : `New ${formatLabel} output.${format}`, status: 'idle' as const, instruction: '', direction }
    const offset = nodes.length * 56
    setNodes((current) => [...current, { id, type: 'document', position: { x: 280 + offset, y: 150 + offset }, data }])
    setSelected(id)
    setIsSaved(false)
    setNotice('Node added to canvas')
    window.setTimeout(() => setNotice(''), 2400)
  }, [nodes.length, setNodes])

  const onConnect = useCallback((connection: Connection) => {
    const candidate = validateConnectionCandidate(connection, nodes, edges)
    if (!candidate.valid) {
      setNotice(candidate.reason || 'Invalid connection.')
      window.setTimeout(() => setNotice(''), 3500)
      return
    }

    const sourceNode = nodes.find((n) => n.id === connection.source)
    const edge: Edge = {
      id: `edge-${crypto.randomUUID()}`,
      source: connection.source,
      target: connection.target,
      sourceHandle: connection.sourceHandle,
      targetHandle: connection.targetHandle,
      type: 'smoothstep',
      animated: true,
      style: { stroke: '#8270e6', strokeWidth: 1.6 },
    }
    setEdges((current) => addEdge(edge, current))
    if (sourceNode && connection.target) {
      setNodes((current) =>
        current.map((n) =>
          n.id === connection.target
            ? {
                ...n,
                data: {
                  ...n.data,
                  sourceFormat: sourceNode.data.format,
                  status: n.data.status === 'idle' ? ('ready' as const) : n.data.status,
                },
              }
            : n,
        ),
      )
    }
    setIsSaved(false)
  }, [nodes, edges, setEdges, setNodes])

  const dagValidation = useMemo(() => validateDAG(nodes, edges), [nodes, edges])

  const updateInstruction = useCallback((nodeId: string, instruction: string) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, instruction } } : node))
    setIsSaved(false)
  }, [setNodes])

  const handleClearLogs = useCallback(() => {
    setCurrentRun((prev) => (prev ? { ...prev, entries: [] } : undefined))
  }, [])

  // Sync snapshot and terminal execution outputs from backend into canvas state
  const syncFinalWorkflowRun = useCallback(
    async (workflowId: string, runId: string) => {
      try {
        const run: WorkflowRun = await getWorkflowRun(workflowId, runId)
        const isStillActive = run.status === 'queued' || run.status === 'running'
        setIsRunning(isStillActive)

        const startedAt = run.started_at || run.created_at
        const finishedAt = run.finished_at || undefined
        const durationMs =
          startedAt && finishedAt
            ? new Date(finishedAt).getTime() - new Date(startedAt).getTime()
            : undefined

        const runStatus: ExecutionStatus =
          run.status === 'done' ? 'done' : run.status === 'failed' ? 'failed' : run.status

        const completedRun: ExecutionRun = {
          id: run.run_id,
          status: runStatus,
          startedAt,
          finishedAt,
          durationMs,
          nodesProcessed: Object.values(run.node_results).filter((n) => n.status === 'done').length,
          nodesTotal: Object.keys(run.node_results).length,
          entries: run.events.map((e) => ({
            id: `evt-${e.sequence}`,
            timestamp: e.timestamp,
            status: (e.status === 'done'
              ? 'done'
              : e.status === 'failed'
                ? 'failed'
                : e.status === 'blocked'
                  ? 'blocked'
                  : e.status === 'reading'
                    ? 'reading'
                    : e.status === 'interpreting'
                      ? 'interpreting'
                      : e.status === 'rendering'
                        ? 'rendering'
                        : e.status === 'validating'
                          ? 'validating'
                          : 'running') as ExecutionStatus,
            message: e.message,
            nodeId: e.node_id ?? undefined,
            error: e.status === 'failed' || e.status === 'blocked' ? e.message : undefined,
          })),
        }

        setCurrentRun(completedRun)
        if (!isStillActive) {
          setRunHistory((prev) => [completedRun, ...prev.filter((r) => r.id !== completedRun.id)].slice(0, 25))
        }

        // Apply final outputs and node results to canvas nodes
        setNodes((current) =>
          current.map((node) => {
            // Check if node is an output node with final output
            const finalOut = run.final_outputs.find((fo) => fo.node_id === node.id)
            if (finalOut) {
              const nodeResult = run.node_results[node.id]
              return {
                ...node,
                data: {
                  ...node.data,
                  status: 'complete' as const,
                  format: finalOut.output.target_format as Format,
                  filename: finalOut.output.filename,
                  artifactId: finalOut.output.output_id,
                  downloadUrl: finalOut.download_url,
                  runId: run.run_id,
                  usage: nodeResult?.usage,
                  estimatedCost: null,
                  errorMessage: undefined,
                },
              }
            }

            // Check if node failed or blocked
            const nodeResult = run.node_results[node.id]
            if (nodeResult) {
              if (nodeResult.status === 'blocked') {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    status: 'blocked' as const,
                    runId: run.run_id,
                    errorMessage: nodeResult.error_message || 'Blocked by upstream failure.',
                  },
                }
              }
              if (nodeResult.status === 'failed') {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    status: 'error' as const,
                    runId: run.run_id,
                    errorMessage: nodeResult.error_message || nodeResult.error_code || 'Node execution failed.',
                  },
                }
              }
              if (nodeResult.status === 'done' && node.data.direction === 'source') {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    status: 'ready' as const,
                    runId: run.run_id,
                  },
                }
              }
            }

            return node
          }),
        )

        if (run.status === 'done') {
          setNotice(`Workflow completed successfully! ${run.final_outputs.length} artifact(s) ready.`)
          window.setTimeout(() => setNotice(''), 4500)
        } else if (run.status === 'failed') {
          setNotice('Workflow execution failed or was blocked. Check the execution panel for details.')
          window.setTimeout(() => setNotice(''), 5500)
        }
      } catch (err) {
        console.error('Failed to sync workflow run snapshot', err)
      }
    },
    [setNodes],
  )

  // Attach SSE stream listener for real-time status and logs
  const attachWorkflowEventsStream = useCallback(
    (workflowId: string, runId: string, nodeToCanvasMap: Map<string, string>, startAfter = 0) => {
      if (sseCleanupRef.current) {
        sseCleanupRef.current()
        sseCleanupRef.current = null
      }

      const teardown = subscribeToWorkflowRunEvents(
        workflowId,
        runId,
        (event: WorkflowEvent) => {
          const entryStatus: ExecutionStatus =
            event.status === 'reading'
              ? 'reading'
              : event.status === 'interpreting'
                ? 'interpreting'
                : event.status === 'planning'
                  ? 'interpreting'
                  : event.status === 'rendering'
                    ? 'rendering'
                    : event.status === 'validating'
                      ? 'validating'
                      : event.status === 'done'
                        ? 'done'
                        : event.status === 'failed'
                          ? 'failed'
                          : event.status === 'blocked'
                            ? 'blocked'
                            : 'running'

          const canvasNodeId = event.node_id ? nodeToCanvasMap.get(event.node_id) : undefined

          setCurrentRun((prev) => {
            if (!prev) return prev
            const isFinished = event.event === 'run_completed'
            const nextStatus: ExecutionStatus = isFinished
              ? (event.status as ExecutionStatus)
              : event.event === 'run_started'
                ? 'running'
                : prev.status

            const newEntry: ExecutionLogEntry = {
              id: `evt-${event.sequence}-${event.event}`,
              timestamp: event.timestamp,
              status: entryStatus,
              message: event.message,
              nodeId: event.node_id ?? undefined,
              nodeLabel: canvasNodeId ?? event.node_id ?? undefined,
              error: event.status === 'failed' || event.status === 'blocked' ? event.message : undefined,
            }

            return {
              ...prev,
              status: nextStatus,
              finishedAt: isFinished ? event.timestamp : prev.finishedAt,
              durationMs:
                isFinished && prev.startedAt
                  ? new Date(event.timestamp).getTime() - new Date(prev.startedAt).getTime()
                  : prev.durationMs,
              entries: [...prev.entries, newEntry],
            }
          })

          // Update canvas nodes based on real node events
          if (event.node_id) {
            const targetCanvasId = canvasNodeId
            if (targetCanvasId) {
              setNodes((current) =>
                current.map((node) => {
                  if (node.id !== targetCanvasId) return node

                  if (event.event === 'node_started') {
                    const nodeStatus: RunStatus =
                      event.status === 'reading'
                        ? 'reading'
                        : event.status === 'interpreting'
                          ? 'interpreting'
                          : event.status === 'planning'
                            ? 'interpreting'
                            : event.status === 'rendering'
                              ? 'rendering'
                              : event.status === 'validating'
                                ? 'validating'
                                : 'running'
                    return { ...node, data: { ...node.data, status: nodeStatus, errorMessage: undefined } }
                  }

                  if (event.event === 'node_completed') {
                    if (event.node_id === targetCanvasId) {
                      return { ...node, data: { ...node.data, status: 'complete', errorMessage: undefined } }
                    }
                    return node
                  }

                  if (event.event === 'node_failed') {
                    return { ...node, data: { ...node.data, status: 'error', errorMessage: event.message } }
                  }

                  if (event.event === 'node_blocked') {
                    return { ...node, data: { ...node.data, status: 'blocked', errorMessage: event.message } }
                  }

                  return node
                }),
              )
            }
          }

          if (event.event === 'run_completed') {
            setIsRunning(false)
            void syncFinalWorkflowRun(workflowId, runId)
          }
        },
        {
          after: startAfter,
          onEnd: () => {
            setIsRunning(false)
            void syncFinalWorkflowRun(workflowId, runId)
          },
          onError: () => {
            void syncFinalWorkflowRun(workflowId, runId)
          },
        },
      )

      sseCleanupRef.current = teardown
    },
    [setNodes, syncFinalWorkflowRun],
  )

  // Persist current workflow DAG definition to backend API
  const handleSave = useCallback(async () => {
    if (isSaving || isRunning) return

    const validation = validateDAG(nodes, edges)
    if (!validation.isValid) {
      const firstError = validation.errors[0]
      setNotice(`Cannot save invalid DAG: ${firstError.message}`)
      window.setTimeout(() => setNotice(''), 4500)
      return
    }

    const sourceNodes = nodes.filter((n) => n.data.direction === 'source')
    const outputNodes = nodes.filter((n) => n.data.direction === 'output')

    if (sourceNodes.length === 0 || outputNodes.length === 0) {
      setNotice('The workflow requires at least one source document and one output node.')
      window.setTimeout(() => setNotice(''), 4000)
      return
    }

    const primaryDocId =
      uploadedDocument?.id ||
      sourceNodes.find((n) => n.data.documentId)?.data.documentId ||
      sourceNodes[0]?.data.documentId ||
      sourceNodes[0]?.id

    setIsSaving(true)
    try {
      const workflowName = uploadedDocument?.filename
        ? `Workflow: ${uploadedDocument.filename}`
        : 'Transmute DAG Workflow'
      const serialized = serializeDAGToWorkflow(nodes, edges, primaryDocId, workflowName)
      const workflow = await createWorkflow(serialized.definition)
      setSavedWorkflowId(workflow.id)
      setIsSaved(true)
      setNotice(`Workflow saved successfully (${workflow.id.slice(0, 8)})`)
      window.setTimeout(() => setNotice(''), 4000)
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Failed to save workflow.'
      console.error('Failed to save workflow', err)
      setNotice(`Save failed: ${errMsg}`)
      window.setTimeout(() => setNotice(''), 5000)
    } finally {
      setIsSaving(false)
    }
  }, [nodes, edges, isSaving, isRunning, uploadedDocument])

  // Trigger DAG execution via backend API contract
  const onRun = useCallback(async () => {
    if (isRunning) {
      setNotice('A workflow execution is already in progress.')
      window.setTimeout(() => setNotice(''), 3000)
      return
    }

    const validation = validateDAG(nodes, edges)
    if (!validation.isValid) {
      const firstError = validation.errors[0]
      setNotice(`DAG Validation: ${firstError.message}`)
      setLogOpen(true)
      window.setTimeout(() => setNotice(''), 4500)
      return
    }

    const sourceNodes = nodes.filter((n) => n.data.direction === 'source')
    const outputNodes = nodes.filter((n) => n.data.direction === 'output')

    if (sourceNodes.length === 0 || outputNodes.length === 0) {
      setNotice('The workflow requires at least one source document and one output node.')
      window.setTimeout(() => setNotice(''), 4000)
      return
    }

    const primaryDocId =
      uploadedDocument?.id ||
      sourceNodes.find((n) => n.data.documentId)?.data.documentId ||
      sourceNodes[0]?.data.documentId ||
      sourceNodes[0]?.id
    if (!primaryDocId) {
      setNotice('Please upload a source document before running the workflow.')
      window.setTimeout(() => setNotice(''), 4000)
      return
    }

    if (sseCleanupRef.current) {
      sseCleanupRef.current()
      sseCleanupRef.current = null
    }

    setIsRunning(true)
    setLogOpen(true)

    // Mark nodes as queued
    setNodes((current) =>
      current.map((n) => ({
        ...n,
        data: {
          ...n.data,
          status: 'queued' as const,
          errorMessage: undefined,
          artifactId: undefined,
          downloadUrl: undefined,
        },
      })),
    )

    const initialEntry: ExecutionLogEntry = {
      id: `entry-${Date.now()}-0`,
      timestamp: new Date().toISOString(),
      status: 'queued',
      message: 'Serializing workflow definition and validating DAG topology…',
    }

    const startTimestamp = new Date().toISOString()
    const runSummary: ExecutionRun = {
      id: 'initializing...',
      status: 'queued',
      startedAt: startTimestamp,
      nodesProcessed: 0,
      nodesTotal: nodes.length,
      entries: [initialEntry],
    }
    setCurrentRun(runSummary)

    let serialized: SerializedDAGResult
    try {
      serialized = serializeDAGToWorkflow(
        nodes,
        edges,
        primaryDocId,
        uploadedDocument?.filename ? `Workflow: ${uploadedDocument.filename}` : 'Transmute DAG Workflow',
      )
      activeNodeMapRef.current = serialized.nodeToCanvasMap
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Failed to serialize workflow definition.'
      setIsRunning(false)
      setNotice(errMsg)
      setCurrentRun((prev) =>
        prev
          ? {
              ...prev,
              status: 'failed',
              error: errMsg,
              entries: [
                ...prev.entries,
                {
                  id: `entry-${Date.now()}-err`,
                  timestamp: new Date().toISOString(),
                  status: 'failed',
                  message: errMsg,
                  error: errMsg,
                },
              ],
            }
          : undefined,
      )
      return
    }

    let workflow
    try {
      workflow = await createWorkflow(serialized.definition)
      setSavedWorkflowId(workflow.id)
      setIsSaved(true)
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Workflow creation failed.'
      setIsRunning(false)
      setNotice(`Workflow validation error: ${errMsg}`)
      setCurrentRun((prev) =>
        prev
          ? {
              ...prev,
              status: 'failed',
              error: errMsg,
              entries: [
                ...prev.entries,
                {
                  id: `entry-${Date.now()}-err`,
                  timestamp: new Date().toISOString(),
                  status: 'failed',
                  message: `Backend validation rejected the workflow: ${errMsg}`,
                  error: errMsg,
                },
              ],
            }
          : undefined,
      )
      setNodes((current) =>
        current.map((n) => ({
          ...n,
          data: { ...n.data, status: 'error' as const, errorMessage: errMsg },
        })),
      )
      return
    }

    let run: WorkflowRun
    try {
      run = await startWorkflowRun(workflow.id, { document_id: primaryDocId })
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Failed to start workflow execution.'
      setIsRunning(false)
      setNotice(errMsg)
      setCurrentRun((prev) =>
        prev
          ? {
              ...prev,
              status: 'failed',
              error: errMsg,
              entries: [
                ...prev.entries,
                {
                  id: `entry-${Date.now()}-err`,
                  timestamp: new Date().toISOString(),
                  status: 'failed',
                  message: errMsg,
                  error: errMsg,
                },
              ],
            }
          : undefined,
      )
      return
    }

    try {
      localStorage.setItem(
        'transmute_last_workflow_run',
        JSON.stringify({ workflowId: workflow.id, runId: run.run_id }),
      )
    } catch {
      // ignore
    }

    const runIdStr = run.run_id
    setCurrentRun({
      id: runIdStr,
      status: 'queued',
      startedAt: run.created_at,
      nodesProcessed: 0,
      nodesTotal: nodes.length,
      entries: [
        initialEntry,
        {
          id: `entry-${Date.now()}-run`,
          timestamp: new Date().toISOString(),
          status: 'queued',
          message: `Workflow persisted (${workflow.id.slice(0, 8)}) and execution queued (${runIdStr.slice(0, 8)}).`,
        },
      ],
    })

    attachWorkflowEventsStream(workflow.id, runIdStr, serialized.nodeToCanvasMap)
  }, [nodes, edges, isRunning, uploadedDocument, attachWorkflowEventsStream, setNodes])

  // Restore persisted workflow run on page load or reconnection
  useEffect(() => {
    const saved = localStorage.getItem('transmute_last_workflow_run')
    if (!saved) return
    try {
      const { workflowId, runId } = JSON.parse(saved) as { workflowId: string; runId: string }
      if (!workflowId || !runId) return

      void (async () => {
        try {
          const run = await getWorkflowRun(workflowId, runId)
          await syncFinalWorkflowRun(workflowId, runId)

          if (run.status === 'queued' || run.status === 'running') {
            setIsRunning(true)
            setLogOpen(true)
            attachWorkflowEventsStream(workflowId, runId, activeNodeMapRef.current, run.events.length)
          }
        } catch {
          localStorage.removeItem('transmute_last_workflow_run')
        }
      })()
    } catch {
      localStorage.removeItem('transmute_last_workflow_run')
    }
  }, [syncFinalWorkflowRun, attachWorkflowEventsStream])

  // Teardown SSE subscription on unmount
  useEffect(() => {
    return () => {
      if (sseCleanupRef.current) {
        sseCleanupRef.current()
        sseCleanupRef.current = null
      }
    }
  }, [])

  // Keyboard shortcuts: Ctrl+Enter runs workflow, Ctrl+S saves workflow
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        void onRun()
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault()
        void handleSave()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onRun, handleSave])
  useEffect(() => {
    let active = true
    const check = async () => {
      try { await getHealth(); if (active) setApiConnected(true) }
      catch { if (active) setApiConnected(false) }
    }
    void check()
    const interval = window.setInterval(() => void check(), 30000)
    return () => { active = false; window.clearInterval(interval) }
  }, [])
  const handleUpload = async (file?: File) => {
    if (!file) return
    const extension = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() : undefined
    if (!extension || !['pptx', 'xlsx', 'docx', 'mmd', 'html'].includes(extension)) {
      setUploadError('Choose a PPTX, XLSX, DOCX, MMD, or HTML document.')
      setUploadPhase('error')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadError('The maximum upload size is 10 MB.')
      setUploadPhase('error')
      return
    }

    // 1. Teardown any running SSE stream
    if (sseCleanupRef.current) {
      sseCleanupRef.current()
      sseCleanupRef.current = null
    }

    // 2. Archive previous currentRun in runHistory before clearing
    if (currentRun && currentRun.id !== 'initializing...') {
      setRunHistory((prev) =>
        prev.some((r) => r.id === currentRun.id) ? prev : [currentRun, ...prev],
      )
    }

    // 3. Clear active workflow/run state for the new document
    setCurrentRun(undefined)
    setIsRunning(false)
    setSavedWorkflowId(null)
    setIsSaved(false)
    activeNodeMapRef.current.clear()
    localStorage.removeItem('transmute_last_workflow_run')

    // 4. Reset upload and document states
    setUploadPhase('uploading')
    setUploadProgress(0)
    setUploadError(undefined)
    setUploadedDocument(undefined)
    setDocumentIR(undefined)
    setActiveInterpretation(null)
    setActivePlan(null)
    setInspectorOpen(false)

    try {
      const uploaded = await uploadDocument(file, (percent) => {
        setUploadProgress(percent)
        if (percent >= 100) setUploadPhase('extracting')
      })
      setUploadPhase('extracting')
      setUploadedDocument(uploaded)
      setDocumentsMap((prev) => ({ ...prev, [uploaded.id]: uploaded }))

      const id = uploaded.id
      setNodes((current) => [
        ...current,
        {
          id,
          type: 'document',
          position: { x: 280 + current.length * 56, y: 150 + current.length * 56 },
          data: {
            format: uploaded.format,
            filename: uploaded.filename,
            status: 'ready' as const,
            instruction: '',
            direction: 'source' as const,
            documentId: id,
          },
        },
      ])
      setSelected(id)

      const ir = await getDocumentIR(uploaded.id)
      setDocumentIR(ir)
      setDocumentIRMap((prev) => ({ ...prev, [uploaded.id]: ir }))
      setUploadPhase('complete')
      setNotice(`Source document ready: ${uploaded.filename}`)
      window.setTimeout(() => setNotice(''), 3500)
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Document upload or extraction failed.')
      setUploadPhase('error')
    }
  }

  // Handle node selection on canvas with cross-document isolation
  const handleNodeClick = useCallback(
    (nodeId: string) => {
      setSelected(nodeId)
      setPanelOpen(true)
      setRightTab('properties')

      const clickedNode = nodes.find((n) => n.id === nodeId)
      if (!clickedNode) return

      // If clicked node is a source node, switch active document metadata & IR
      if (clickedNode.data.direction === 'source') {
        const docId = clickedNode.data.documentId || clickedNode.id
        if (documentsMap[docId]) {
          setUploadedDocument(documentsMap[docId])
        }
        if (documentIRMap[docId]) {
          setDocumentIR(documentIRMap[docId])
        }
      } else if (clickedNode.data.direction === 'output') {
        // If clicked node is an output node, find upstream source document
        const incomingEdge = edges.find((e) => e.target === nodeId)
        if (incomingEdge) {
          const upstreamDocId = incomingEdge.source
          if (documentsMap[upstreamDocId]) {
            setUploadedDocument(documentsMap[upstreamDocId])
          }
          if (documentIRMap[upstreamDocId]) {
            setDocumentIR(documentIRMap[upstreamDocId])
          }
        }
      }

      // If not actively running a workflow, scope ExecutionPanel's currentRun to the clicked node
      if (!isRunning) {
        let associatedRunId: string | undefined = clickedNode.data.runId
        if (!associatedRunId && clickedNode.data.direction === 'source') {
          // Check if any connected output node has a run
          const outgoing = edges.filter((e) => e.source === nodeId)
          const outputWithRun = outgoing
            .map((e) => nodes.find((n) => n.id === e.target))
            .find((n) => Boolean(n?.data.runId))
          associatedRunId = outputWithRun?.data.runId
        }

        if (associatedRunId) {
          const matchingRun = runHistory.find((r) => r.id === associatedRunId)
          if (matchingRun) {
            setCurrentRun(matchingRun)
            return
          }
        }
        // If this document or node has no run associated, reset Execution panel to empty/ready
        setCurrentRun(undefined)
      }
    },
    [nodes, edges, documentsMap, documentIRMap, isRunning, runHistory],
  )

  const emptyState = useMemo(() => nodes.length === 0, [nodes.length])

  // Resolve the active source document for interpretation, planning, and transformation
  const activeSourceDocument = useMemo(() => {
    if (!selectedNode) return uploadedDocument
    if (selectedNode.data.direction === 'source') {
      const docId = selectedNode.data.documentId || selectedNode.id
      return documentsMap[docId] || (selectedNode.id === uploadedDocument?.id ? uploadedDocument : undefined)
    }
    // If an output node is selected, find the upstream source document feeding it
    const incomingEdge = edges.find((e) => e.target === selectedNode.id)
    if (incomingEdge) {
      const upstreamDocId = incomingEdge.source
      return documentsMap[upstreamDocId] || (upstreamDocId === uploadedDocument?.id ? uploadedDocument : undefined)
    }
    return uploadedDocument
  }, [selectedNode, uploadedDocument, documentsMap, edges])

  // Resolve the active target output node connected to the source document
  const activeTargetNode = useMemo(() => {
    if (selectedNode && selectedNode.data.direction === 'output') {
      return selectedNode
    }
    const sourceId = selectedNode?.data.direction === 'source' ? selectedNode.id : uploadedDocument?.id
    if (sourceId) {
      const outgoing = edges.filter((e) => e.source === sourceId)
      const connectedOutputs = outgoing
        .map((e) => nodes.find((n) => n.id === e.target))
        .filter((n): n is DocumentFlowNode => Boolean(n && n.data.direction === 'output'))

      if (connectedOutputs.length > 0) {
        return connectedOutputs[0]
      }
    }
    return undefined
  }, [selectedNode, uploadedDocument?.id, edges, nodes])

  const targetDocId = activeSourceDocument?.id || uploadedDocument?.id
  const targetDocFilename = activeSourceDocument?.filename || uploadedDocument?.filename

  // Transformation to canvas node synchronization handlers
  const handleTransformationStart = useCallback((targetNodeId?: string) => {
    const targetId = targetNodeId || activeTargetNode?.id
    if (!targetId) return
    setNodes((current) =>
      current.map((n) =>
        n.id === targetId
          ? {
              ...n,
              data: {
                ...n.data,
                status: 'rendering',
                errorMessage: undefined,
              },
            }
          : n,
      ),
    )
  }, [activeTargetNode?.id, setNodes])

  const handleTransformationSuccess = useCallback((response: ArtifactOperationResponse, targetNodeId?: string) => {
    const targetId = targetNodeId || activeTargetNode?.id
    if (targetId) {
      setNodes((current) =>
        current.map((n) =>
          n.id === targetId
            ? {
                ...n,
                data: {
                  ...n.data,
                  status: 'complete',
                  format: response.output.target_format as Format,
                  filename: response.output.filename,
                  artifactId: response.output.output_id,
                  downloadUrl: response.download_url,
                  runId: response.run_id,
                  usage: response.usage,
                  estimatedCost: response.estimated_cost,
                  errorMessage: undefined,
                },
              }
            : n,
        ),
      )
      setNotice(`Transformation complete: ${response.output.filename}`)
      window.setTimeout(() => setNotice(''), 3500)
    } else if (uploadedDocument) {
      // If no output node was on canvas yet, spawn and connect one
      const newId = `${response.output.target_format}-${Date.now()}`
      const sourceNode = nodes.find((n) => n.id === uploadedDocument.id)
      const position = sourceNode
        ? { x: sourceNode.position.x + 320, y: sourceNode.position.y }
        : { x: 300, y: 150 }

      const newNode: DocumentFlowNode = {
        id: newId,
        type: 'document',
        position,
        data: {
          format: response.output.target_format as Format,
          filename: response.output.filename,
          status: 'complete',
          instruction: '',
          direction: 'output',
          artifactId: response.output.output_id,
          downloadUrl: response.download_url,
          runId: response.run_id,
          usage: response.usage,
          estimatedCost: response.estimated_cost,
          sourceFormat: uploadedDocument.format,
        },
      }
      setNodes((current) => [...current, newNode])
      if (sourceNode) {
        setEdges((current) => [
          ...current,
          {
            id: `edge-${crypto.randomUUID()}`,
            source: sourceNode.id,
            target: newId,
            type: 'smoothstep',
            animated: true,
            style: { stroke: '#8270e6', strokeWidth: 1.6 },
          },
        ])
      }
      setNotice(`Transformation complete: ${response.output.filename}`)
      window.setTimeout(() => setNotice(''), 3500)
    }
  }, [activeTargetNode?.id, uploadedDocument, nodes, setNodes, setEdges])

  const handleTransformationError = useCallback((errorMsg: string, targetNodeId?: string) => {
    const targetId = targetNodeId || activeTargetNode?.id
    if (targetId) {
      setNodes((current) =>
        current.map((n) =>
          n.id === targetId
            ? {
                ...n,
                data: {
                  ...n.data,
                  status: 'error',
                  errorMessage: errorMsg,
                },
              }
            : n,
        ),
      )
    }
  }, [activeTargetNode?.id, setNodes])

  const handleClearArtifact = useCallback((targetNodeId?: string) => {
    const targetId = targetNodeId || activeTargetNode?.id
    if (targetId) {
      setNodes((current) =>
        current.map((n) => {
          if (n.id !== targetId) return n
          if (!n.data.artifactId && !n.data.downloadUrl && n.data.status !== 'error') return n
          return {
            ...n,
            data: {
              ...n.data,
              status: 'idle',
              artifactId: undefined,
              downloadUrl: undefined,
              runId: undefined,
              usage: undefined,
              estimatedCost: undefined,
              errorMessage: undefined,
              filename: `New ${n.data.format.toUpperCase()} output.${n.data.format}`,
            },
          }
        }),
      )
    }
  }, [activeTargetNode?.id, setNodes])

  const handleInstructionsChange = useCallback((instruction: string, targetNodeId?: string) => {
    const targetId = targetNodeId || activeTargetNode?.id
    if (targetId) {
      setNodes((current) =>
        current.map((n) =>
          n.id === targetId ? { ...n, data: { ...n.data, instruction } } : n,
        ),
      )
    }
  }, [activeTargetNode?.id, setNodes])

  const handleTargetFormatChange = useCallback((format: DocumentFormat, targetNodeId?: string) => {
    const targetId = targetNodeId || activeTargetNode?.id
    if (targetId) {
      setNodes((current) =>
        current.map((n) =>
          n.id === targetId
            ? {
                ...n,
                data: {
                  ...n.data,
                  format: format as Format,
                  filename: `New ${format.toUpperCase()} output.${format}`,
                },
              }
            : n,
        ),
      )
    }
  }, [activeTargetNode?.id, setNodes])

  // Listen to custom events dispatched from canvas nodes
  useEffect(() => {
    const handleNoticeEvent = (e: Event) => {
      const customEvent = e as CustomEvent<string>
      if (customEvent.detail) {
        setNotice(customEvent.detail)
        window.setTimeout(() => setNotice(''), 4500)
      }
    }

    const handleSelectNodeEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ nodeId: string }>
      if (customEvent.detail?.nodeId) {
        handleNodeClick(customEvent.detail.nodeId)
      }
    }

    const handleInspectNodeEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ nodeId: string; documentId?: string }>
      if (customEvent.detail) {
        const docId = customEvent.detail.documentId || customEvent.detail.nodeId
        if (documentsMap[docId]) {
          setUploadedDocument(documentsMap[docId])
        }
        if (documentIRMap[docId]) {
          setDocumentIR(documentIRMap[docId])
        }
        setInspectorOpen(true)
      }
    }

    const handleDeleteNodeEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ nodeId: string }>
      const nodeId = customEvent.detail?.nodeId
      if (nodeId) {
        setNodes((current) => current.filter((n) => n.id !== nodeId))
        setEdges((current) => current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId))
        setSelected((prev) => (prev === nodeId ? undefined : prev))
        setIsSaved(false)
        setNotice('Node removed from canvas.')
        window.setTimeout(() => setNotice(''), 3000)
      }
    }

    const handleChangeFormatEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ nodeId: string; format: DocumentFormat }>
      if (customEvent.detail?.nodeId && customEvent.detail?.format) {
        handleTargetFormatChange(customEvent.detail.format, customEvent.detail.nodeId)
        setIsSaved(false)
        setNotice(`Target format changed to ${customEvent.detail.format.toUpperCase()}`)
        window.setTimeout(() => setNotice(''), 3000)
      }
    }

    const handleClearArtifactEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ nodeId: string }>
      if (customEvent.detail?.nodeId) {
        handleClearArtifact(customEvent.detail.nodeId)
        setIsSaved(false)
        setNotice('Output artifact cleared.')
        window.setTimeout(() => setNotice(''), 3000)
      }
    }

    const handleUpdateInstructionEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ nodeId: string; instruction: string }>
      if (customEvent.detail?.nodeId !== undefined) {
        updateInstruction(customEvent.detail.nodeId, customEvent.detail.instruction)
        setIsSaved(false)
      }
    }

    const handlePreviewArtifactEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{ downloadUrl?: string; filename?: string; format?: string }>
      if (customEvent.detail?.downloadUrl) {
        window.open(customEvent.detail.downloadUrl, '_blank')
        setNotice(`Previewing ${customEvent.detail.filename || 'artifact'}`)
        window.setTimeout(() => setNotice(''), 3500)
      }
    }

    window.addEventListener('transmute-notice', handleNoticeEvent)
    window.addEventListener('transmute-select-node', handleSelectNodeEvent)
    window.addEventListener('transmute-inspect-node', handleInspectNodeEvent)
    window.addEventListener('transmute-delete-node', handleDeleteNodeEvent)
    window.addEventListener('transmute-change-format', handleChangeFormatEvent)
    window.addEventListener('transmute-clear-artifact', handleClearArtifactEvent)
    window.addEventListener('transmute-update-instruction', handleUpdateInstructionEvent)
    window.addEventListener('transmute-preview-artifact', handlePreviewArtifactEvent)

    return () => {
      window.removeEventListener('transmute-notice', handleNoticeEvent)
      window.removeEventListener('transmute-select-node', handleSelectNodeEvent)
      window.removeEventListener('transmute-inspect-node', handleInspectNodeEvent)
      window.removeEventListener('transmute-delete-node', handleDeleteNodeEvent)
      window.removeEventListener('transmute-change-format', handleChangeFormatEvent)
      window.removeEventListener('transmute-clear-artifact', handleClearArtifactEvent)
      window.removeEventListener('transmute-update-instruction', handleUpdateInstructionEvent)
      window.removeEventListener('transmute-preview-artifact', handlePreviewArtifactEvent)
    }
  }, [
    handleNodeClick,
    documentsMap,
    documentIRMap,
    setNodes,
    setEdges,
    handleTargetFormatChange,
    handleClearArtifact,
    updateInstruction,
  ])

  return <div className="app-shell"><Sidebar onNew={() => {
    if (sseCleanupRef.current) {
      sseCleanupRef.current()
      sseCleanupRef.current = null
    }
    localStorage.removeItem('transmute_last_workflow_run')
    setIsRunning(false)
    setSavedWorkflowId(null)
    setIsSaved(false)
    setCurrentRun(undefined)
    setDocumentsMap({})
    setDocumentIRMap({})
    setNodes([])
    setEdges([])
    setSelected(undefined)
    setUploadedDocument(undefined)
    setDocumentIR(undefined)
    setActiveInterpretation(null)
    setActivePlan(null)
    setUploadPhase(undefined)
  }} />
    <main className="main-area"><header className="topbar"><div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} /><strong>Untitled workflow</strong><button className="icon-button"><ChevronDown size={14} /></button><span className="draft-tag">DRAFT</span></div><div className="topbar-actions">{isSaved && savedWorkflowId ? (<div className="save-state saved" title={`Workflow ID: ${savedWorkflowId}`}><CheckCircle2 size={15} className="text-success" /><span className="text-success font-medium">Saved</span></div>) : (<div className="save-state" title="Changes not yet saved to backend"><Cloud size={15} /><span>In-memory draft</span></div>)}<div className="divider" /><div className="cost-estimate"><span>EST. COST</span><strong>Not configured</strong></div><button className="button-secondary" onClick={() => setNotice('Sharing will be available when workflow saving is implemented.')}><Share2 size={14} /> Share</button><button className="run-button" onClick={() => void onRun()} disabled={isRunning} title={isRunning ? 'Execution in progress' : 'Run workflow DAG (Ctrl+Enter)'}>{isRunning ? <LoaderCircle size={13} className="spin" /> : <Play size={13} fill="currentColor" />} {isRunning ? 'Running…' : 'Run workflow'} <kbd>Ctrl+Enter</kbd></button><button className="icon-button top-help"><HelpCircle size={17} /></button></div></header>
      <input ref={fileInput} type="file" accept=".pptx,.xlsx,.docx,.mmd,.html" hidden onChange={(event) => { void handleUpload(event.target.files?.[0]); event.target.value = '' }} />
      <div className="workspace"><section className="canvas-column"><div className="canvas-toolbar"><div className="canvas-label"><span className="canvas-status-dot" />WORKFLOW CANVAS<span className="canvas-count">{nodes.length} {nodes.length === 1 ? 'node' : 'nodes'}</span>{nodes.length > 0 && (<div className={`canvas-validation-badge flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-mono ml-2 border ${dagValidation.isValid ? 'bg-success/10 text-success border-success/30' : 'bg-error/10 text-error border-error/30'}`} title={dagValidation.isValid ? 'DAG is acyclic and valid for execution' : dagValidation.errors.map((e) => e.message).join('\n')}>{dagValidation.isValid ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}<span>{dagValidation.isValid ? 'DAG valid' : `${dagValidation.errors.length} issue${dagValidation.errors.length > 1 ? 's' : ''}`}</span></div>)}</div><div className="canvas-actions"><button onClick={() => fileInput.current?.click()}><Upload size={14} /> Upload</button><button type="button" onClick={() => void handleSave()} disabled={isSaving || isRunning} title="Save workflow definition to backend (Ctrl+S)">{isSaving ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />} Save</button><button aria-label="Search canvas"><Search size={15} /></button></div></div>
        {uploadPhase !== undefined && <UploadFeedback phase={uploadPhase} progress={uploadProgress} document={uploadedDocument} error={uploadError} onInspect={() => setInspectorOpen(true)} onDismiss={() => setUploadPhase(undefined)} />}
        <div className="flow-wrap"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange} onConnect={onConnect} isValidConnection={(connection) => validateConnectionCandidate(connection, nodes, edges).valid} onNodeClick={(_, node) => handleNodeClick(node.id)} onPaneClick={() => setSelected(undefined)} fitView minZoom={0.35} maxZoom={1.5} defaultEdgeOptions={{ type: 'smoothstep' }} proOptions={{ hideAttribution: true }}>
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#272a32" /><MiniMap pannable zoomable nodeColor={(node) => { const format = (node.data as { format?: Format }).format; return format ? formatColors[format] : '#777' }} maskColor="rgba(13,15,20,0.72)" /><Controls showInteractive={false} /></ReactFlow>
          {emptyState && <div className="canvas-empty"><div className="empty-icon-stack"><span><WandSparkles size={20} /></span><i /><b>*</b></div><span className="eyebrow">YOUR CREATIVE WORKSPACE</span><h1>Ideas in.<br /><em>New artefacts out.</em></h1><p>Connect your documents in a visual workflow. Transmute reads between the lines to create something genuinely useful.</p><div className="empty-actions"><button className="upload-button" onClick={() => fileInput.current?.click()}><Upload size={15} /> Upload a document</button><button className="choose-format" onClick={() => addNode('pptx')}>Choose a format <ChevronDown size={14} /></button></div><span className="empty-hint"><AlertCircle size={12} /> Conversions are not enabled yet. Your work stays on this canvas.</span><div className="shortcut-hint"><Command size={12} /> Add a format from the panel <span>·</span> Drag to connect nodes</div></div>}
        </div><FormatPalette onAdd={(format) => addNode(format)} /><ExecutionPanel expanded={logOpen} onToggle={() => setLogOpen(!logOpen)} currentRun={currentRun} runHistory={runHistory} onClearLogs={handleClearLogs} onSelectRun={(run) => setCurrentRun(run)} />
      </section>
      {panelOpen ? (
        <div className="flex flex-col border-l border-border bg-surface-overlay w-[310px] flex-none z-10">
          <div className="flex items-center border-b border-border bg-surface-raised px-2 pt-2 gap-1 text-2xs font-mono select-none">
            <button
              type="button"
              onClick={() => setRightTab('properties')}
              className={`px-2.5 py-1.5 rounded-t font-semibold transition-colors flex items-center gap-1.5 ${
                rightTab === 'properties'
                  ? 'bg-surface-overlay text-accent-lighter border-t-2 border-accent'
                  : 'text-text-muted hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              <Sliders size={12} />
              Properties
            </button>
            <button
              type="button"
              onClick={() => setRightTab('interpretation')}
              className={`px-2.5 py-1.5 rounded-t font-semibold transition-colors flex items-center gap-1.5 ${
                rightTab === 'interpretation'
                  ? 'bg-surface-overlay text-accent-lighter border-t-2 border-accent'
                  : 'text-text-muted hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              <Brain size={12} />
              Interpretation
              {activeInterpretation && <span className="w-1.5 h-1.5 rounded-full bg-accent" />}
            </button>
            <button
              type="button"
              onClick={() => setRightTab('plan')}
              className={`px-2.5 py-1.5 rounded-t font-semibold transition-colors flex items-center gap-1.5 ${
                rightTab === 'plan'
                  ? 'bg-surface-overlay text-accent-lighter border-t-2 border-accent'
                  : 'text-text-muted hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              <Wand2 size={12} />
              Plan
              {activePlan && <span className="w-1.5 h-1.5 rounded-full bg-success" />}
            </button>
            <button
              type="button"
              onClick={() => setRightTab('transform')}
              className={`px-2.5 py-1.5 rounded-t font-semibold transition-colors flex items-center gap-1.5 ${
                rightTab === 'transform'
                  ? 'bg-surface-overlay text-accent-lighter border-t-2 border-accent'
                  : 'text-text-muted hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              <FileOutput size={12} />
              Transform
            </button>
            <button
              type="button"
              onClick={() => setPanelOpen(false)}
              className="icon-button ml-auto"
              aria-label="Close panel"
            >
              <PanelRightClose size={14} />
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {rightTab === 'properties' && (
              <PropertiesPanel
                selectedNode={selectedNode}
                onInstructionChange={updateInstruction}
                documentMetadata={documentsMap}
                documentIRs={documentIRMap}
                edges={edges}
                allNodes={nodes}
              />
            )}
            {rightTab === 'interpretation' && (
              <InterpretationPanel
                documentId={targetDocId}
                documentFilename={targetDocFilename}
                activeInterpretation={activeInterpretation}
                onInterpretationSelected={(interp) => {
                  setActiveInterpretation(interp)
                }}
              />
            )}
            {rightTab === 'plan' && (
              <TransformationPlanPanel
                documentId={targetDocId}
                interpretation={activeInterpretation}
                activePlan={activePlan}
                onPlanSelected={setActivePlan}
              />
            )}
            <div className={rightTab === 'transform' ? 'h-full' : 'hidden'}>
              <TransformationPanel
                document={activeSourceDocument}
                interpretation={activeInterpretation}
                targetNode={activeTargetNode}
                onTransformationStart={handleTransformationStart}
                onTransformationSuccess={handleTransformationSuccess}
                onTransformationError={handleTransformationError}
                onClearArtifact={handleClearArtifact}
                onInstructionsChange={handleInstructionsChange}
                onTargetFormatChange={handleTargetFormatChange}
              />
            </div>
          </div>
        </div>
      ) : (
        <button className="reopen-properties" onClick={() => setPanelOpen(true)}>
          <PanelRightClose size={16} /> Panels
        </button>
      )}
      </div>
      <footer className="statusbar"><span>{apiConnected ? <Activity size={13} /> : <AlertCircle size={13} />} {apiConnected ? 'API online' : 'API unavailable'}</span><span>API <i className={`api-dot ${apiConnected ? '' : 'offline'}`} /> {apiConnected ? 'Connected locally' : 'Retrying connection'}</span><span className="status-right">Transmute preview <b>v0.1.0</b><button className="icon-button" onClick={() => setPanelOpen(!panelOpen)} aria-label="Toggle properties"><PanelRightClose size={14} /></button></span></footer>
    </main>
    {inspectorOpen && (documentIR || (selectedNode && documentIRMap[selectedNode.id])) && (
      <DocumentInspector
        document={documentIR || documentIRMap[selectedNode!.id]}
        onClose={() => setInspectorOpen(false)}
      />
    )}
    {notice && <div className="toast"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14} /></button></div>}
  </div>
}
