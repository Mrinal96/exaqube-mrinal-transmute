import { ArrowDownRight, ArrowUpRight, CircleHelp, FileText, Info, Sparkles } from 'lucide-react'
import type { DocumentFlowNode } from '../../types/workflow'
import { formatColors, formatIcons, formats } from '../../utils/formats'

interface PropertiesPanelProps { selectedNode?: DocumentFlowNode; onInstructionChange: (nodeId: string, value: string) => void }

export function PropertiesPanel({ selectedNode, onInstructionChange }: PropertiesPanelProps) {
  const node = selectedNode
  const info = node ? formats.find((format) => format.id === node.data.format)! : undefined
  const Icon = node ? formatIcons[node.data.format] : FileText
  return <aside className="properties-panel"><div className="properties-header"><div><span>CONFIGURATION</span><h3>Properties</h3></div><button className="icon-button" aria-label="Properties help"><CircleHelp size={16} /></button></div>
    {node ? <><div className="selected-file"><div className="selected-icon" style={{ color: formatColors[node.data.format], backgroundColor: `${formatColors[node.data.format]}16` }}><Icon size={18} /></div><div><strong>{node.data.filename}</strong><span>{info?.label} · {info?.extension}</span></div></div>
      <div className="property-group"><label>NODE STATUS</label><div className="property-value status-value"><i className="status-dot" />{node.data.status === 'idle' ? 'Waiting for source' : node.data.status}</div></div>
      <div className="property-group"><label>CONVERSION</label><div className="format-route"><div><ArrowUpRight size={13} /><span>Source</span><b>{node.data.direction === 'source' ? info?.id.toUpperCase() : '—'}</b></div><ArrowDownRight size={14} /><div><ArrowDownRight size={13} /><span>Target</span><b>{node.data.direction === 'output' ? info?.id.toUpperCase() : '—'}</b></div></div></div>
      <div className="property-group"><label>INSTRUCTION <span>OPTIONAL</span></label><textarea placeholder="Describe what you want the new artefact to communicate…" value={node.data.instruction} onChange={(event) => onInstructionChange(node.id, event.target.value)} /></div>
      <div className="property-group"><label>OUTPUT METADATA</label><div className="metadata-empty"><Info size={15} /><span>Output details will appear after a workflow is run.</span></div></div>
      <div className="semantic-note"><Sparkles size={14} /><span>Transmute interprets your content to create a useful new artefact.</span></div>
    </> : <div className="properties-empty"><div className="empty-illustration"><FileText size={22} /></div><strong>Select a node</strong><span>Choose a document on the canvas to view and edit its properties.</span></div>}
  </aside>
}

