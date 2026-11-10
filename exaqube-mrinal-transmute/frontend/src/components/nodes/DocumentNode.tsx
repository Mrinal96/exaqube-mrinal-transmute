import { memo, type CSSProperties } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { AlertCircle, ArrowRight, Check, Clock3, Download, Eye, LoaderCircle, MoreHorizontal, Sparkles, Upload } from 'lucide-react'
import type { DocumentFlowNode } from '../../types/workflow'
import { formatColors, formatIcons, formats } from '../../utils/formats'

function DocumentNode({ data, selected }: NodeProps<DocumentFlowNode>) {
  const info = formats.find((format) => format.id === data.format)!
  const Icon = formatIcons[data.format]
  const color = formatColors[data.format]
  const isInput = data.direction === 'source'
  return (
    <article className={`document-node ${selected ? 'selected' : ''}`} style={{ '--node-accent': color } as CSSProperties}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <header className="node-header">
        <span className="format-icon" style={{ color, backgroundColor: `${color}16` }}><Icon size={17} /></span>
        <span className="node-kind">{isInput ? 'SOURCE DOCUMENT' : 'TRANSFORMED OUTPUT'}</span>
        <button className="icon-button node-menu" aria-label="Node options"><MoreHorizontal size={17} /></button>
      </header>
      <div className="node-file">
        <strong>{data.filename}</strong>
        <span>{info.label} <i>·</i> {info.extension.slice(1).toUpperCase()}</span>
      </div>
      <div className="node-status">
        {data.status === 'complete' ? <Check size={13} /> : data.status === 'error' ? <AlertCircle className="error-icon" size={13} /> : data.status === 'running' ? <LoaderCircle className="spin" size={13} /> : <Clock3 size={13} />}
        <span>{data.status === 'complete' ? 'Ready to preview' : data.status === 'error' ? 'Needs attention' : data.status === 'running' ? 'Processing' : isInput ? 'Uploaded · source ready' : 'Waiting for source'}</span>
        {data.status === 'running' && <span className="progress-track"><i /></span>}
      </div>
      {!isInput && <div className="node-instruction"><Sparkles size={12} /><span>{data.instruction || 'Add an instruction to guide the transformation'}</span></div>}
      <footer className="node-actions">
        <button type="button" disabled aria-label="Preview output"><Eye size={13} /> Preview</button>
        <button type="button" disabled aria-label="Download output"><Download size={13} /> Download</button>
      </footer>
      {isInput && <span className="source-port"><Upload size={10} /> INPUT</span>}
      <Handle type="source" position={Position.Right} className="flow-handle" />
      {isInput && <span className="edge-caption"><ArrowRight size={11} /> CONNECT TO TRANSFORM</span>}
    </article>
  )
}

export default memo(DocumentNode)



