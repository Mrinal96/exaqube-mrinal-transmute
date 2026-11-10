import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow, addEdge, useEdgesState, useNodesState, type Connection, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './ingestion.css'
import { Activity, AlertCircle, ChevronDown, ChevronRight, Cloud, Command, HelpCircle, PanelRightClose, Play, Save, Search, Share2, Upload, WandSparkles, X } from 'lucide-react'
import { Sidebar } from './components/layout/Sidebar'
import DocumentNode from './components/nodes/DocumentNode'
import { ExecutionPanel } from './components/panels/ExecutionPanel'
import { FormatPalette } from './components/panels/FormatPalette'
import { PropertiesPanel } from './components/panels/PropertiesPanel'
import type { DocumentFlowNode, Format } from './types/workflow'
import { getDocumentIR, getHealth, uploadDocument, type DocumentIR, type DocumentMetadata } from './services/api'
import { formatColors } from './utils/formats'
import { DocumentInspector } from './components/panels/DocumentInspector'
import { UploadFeedback, type UploadPhase } from './components/panels/UploadFeedback'

const nodeTypes = { document: DocumentNode }
const initialNodes: DocumentFlowNode[] = []

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState<DocumentFlowNode>(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selected, setSelected] = useState<string>()
  const [panelOpen, setPanelOpen] = useState(true)
  const [logOpen, setLogOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [apiConnected, setApiConnected] = useState(false)
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>()
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState<string>()
  const [uploadedDocument, setUploadedDocument] = useState<DocumentMetadata>()
  const [documentIR, setDocumentIR] = useState<DocumentIR>()
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const selectedNode = nodes.find((node) => node.id === selected)
  const addNode = useCallback((format: Format, direction: 'source' | 'output' = 'output') => {
    const id = `${format}-${Date.now()}`
    const formatLabel = format.toUpperCase()
    const data = { format, filename: direction === 'source' ? `Untitled source.${format}` : `New ${formatLabel} output.${format}`, status: 'idle' as const, instruction: '', direction }
    const offset = nodes.length * 56
    setNodes((current) => [...current, { id, type: 'document', position: { x: 280 + offset, y: 150 + offset }, data }])
    setSelected(id)
    setNotice('Node added to canvas')
    window.setTimeout(() => setNotice(''), 2400)
  }, [nodes.length, setNodes])
  const onConnect = useCallback((connection: Connection) => {
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
  }, [setEdges])
  const updateInstruction = useCallback((nodeId: string, instruction: string) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, instruction } } : node))
  }, [setNodes])
  const onRun = () => { setNotice('Workflow execution is not available in this milestone.'); window.setTimeout(() => setNotice(''), 3500) }
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
    setUploadPhase('uploading')
    setUploadProgress(0)
    setUploadError(undefined)
    setUploadedDocument(undefined)
    setDocumentIR(undefined)
    try {
      const uploaded = await uploadDocument(file, (percent) => {
        setUploadProgress(percent)
        if (percent >= 100) setUploadPhase('extracting')
      })
      setUploadedDocument(uploaded)
      const id = uploaded.id
      setNodes((current) => [...current, { id, type: 'document', position: { x: 280 + current.length * 56, y: 150 + current.length * 56 }, data: { format: uploaded.format, filename: uploaded.filename, status: 'ready', instruction: '', direction: 'source' } }])
      setSelected(id)
      const ir = await getDocumentIR(uploaded.id)
      setDocumentIR(ir)
      setUploadPhase('complete')
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Document upload or extraction failed.')
      setUploadPhase('error')
    }
  }
  const emptyState = useMemo(() => nodes.length === 0, [nodes.length])

  return <div className="app-shell"><Sidebar onNew={() => { setNodes([]); setEdges([]); setSelected(undefined) }} />
    <main className="main-area"><header className="topbar"><div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} /><strong>Untitled workflow</strong><button className="icon-button"><ChevronDown size={14} /></button><span className="draft-tag">DRAFT</span></div><div className="topbar-actions"><div className="save-state"><Cloud size={15} /><span>In-memory draft</span></div><div className="divider" /><div className="cost-estimate"><span>EST. COST</span><strong>$0.00</strong></div><button className="button-secondary" onClick={() => setNotice('Sharing will be available when workflow saving is implemented.')}><Share2 size={14} /> Share</button><button className="run-button" onClick={onRun}><Play size={13} fill="currentColor" /> Run workflow <kbd>Ctrl+Enter</kbd></button><button className="icon-button top-help"><HelpCircle size={17} /></button></div></header>
      <input ref={fileInput} type="file" accept=".pptx,.xlsx,.docx,.mmd,.html" hidden onChange={(event) => { void handleUpload(event.target.files?.[0]); event.target.value = '' }} />
      <div className="workspace"><section className="canvas-column"><div className="canvas-toolbar"><div className="canvas-label"><span className="canvas-status-dot" />WORKFLOW CANVAS<span className="canvas-count">{nodes.length} {nodes.length === 1 ? 'node' : 'nodes'}</span></div><div className="canvas-actions"><button onClick={() => fileInput.current?.click()}><Upload size={14} /> Upload</button><button onClick={() => setNotice('Workflow saving is planned for a future milestone.')}><Save size={14} /> Save</button><button aria-label="Search canvas"><Search size={15} /></button></div></div>
        <UploadFeedback phase={uploadPhase} progress={uploadProgress} document={uploadedDocument} error={uploadError} onInspect={() => setInspectorOpen(true)} onDismiss={() => setUploadPhase(undefined)} />
        <div className="flow-wrap"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, node) => setSelected(node.id)} onPaneClick={() => setSelected(undefined)} fitView minZoom={0.35} maxZoom={1.5} defaultEdgeOptions={{ type: 'smoothstep' }} proOptions={{ hideAttribution: true }}>
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#272a32" /><MiniMap pannable zoomable nodeColor={(node) => { const format = (node.data as { format?: Format }).format; return format ? formatColors[format] : '#777' }} maskColor="rgba(13,15,20,0.72)" /><Controls showInteractive={false} /></ReactFlow>
          {emptyState && <div className="canvas-empty"><div className="empty-icon-stack"><span><WandSparkles size={20} /></span><i /><b>*</b></div><span className="eyebrow">YOUR CREATIVE WORKSPACE</span><h1>Ideas in.<br /><em>New artefacts out.</em></h1><p>Connect your documents in a visual workflow. Transmute reads between the lines to create something genuinely useful.</p><div className="empty-actions"><button className="upload-button" onClick={() => fileInput.current?.click()}><Upload size={15} /> Upload a document</button><button className="choose-format" onClick={() => addNode('pptx')}>Choose a format <ChevronDown size={14} /></button></div><span className="empty-hint"><AlertCircle size={12} /> Conversions are not enabled yet. Your work stays on this canvas.</span><div className="shortcut-hint"><Command size={12} /> Add a format from the panel <span>·</span> Drag to connect nodes</div></div>}
        </div><FormatPalette onAdd={(format) => addNode(format)} /><ExecutionPanel expanded={logOpen} onToggle={() => setLogOpen(!logOpen)} />
      </section>
      {panelOpen ? <PropertiesPanel selectedNode={selectedNode} onInstructionChange={updateInstruction} /> : <button className="reopen-properties" onClick={() => setPanelOpen(true)}><PanelRightClose size={16} /> Properties</button>}
      </div>
      <footer className="statusbar"><span>{apiConnected ? <Activity size={13} /> : <AlertCircle size={13} />} {apiConnected ? 'API online' : 'API unavailable'}</span><span>API <i className={`api-dot ${apiConnected ? '' : 'offline'}`} /> {apiConnected ? 'Connected locally' : 'Retrying connection'}</span><span className="status-right">Transmute preview <b>v0.1.0</b><button className="icon-button" onClick={() => setPanelOpen(!panelOpen)} aria-label="Toggle properties"><PanelRightClose size={14} /></button></span></footer>
    </main>
    {inspectorOpen && documentIR && <DocumentInspector document={documentIR} onClose={() => setInspectorOpen(false)} />}
    {notice && <div className="toast"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14} /></button></div>}
  </div>
}




