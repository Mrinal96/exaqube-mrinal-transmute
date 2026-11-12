import { memo, type CSSProperties } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  AlertCircle,
  ArrowRight,
  Ban,
  Check,
  Clock3,
  Download,
  Eye,
  LoaderCircle,
  MoreHorizontal,
  Sparkles,
  Upload,
  XCircle,
} from 'lucide-react'
import type { DocumentFlowNode, RunStatus } from '../../types/workflow'
import { formatColors, formatIcons, formats } from '../../utils/formats'
import { downloadArtifact } from '../../services/api'

function getStatusDetails(status: RunStatus, isInput: boolean, errorMessage?: string) {
  switch (status) {
    case 'complete':
      return {
        icon: <Check size={13} className="text-success flex-none" />,
        label: 'Ready to preview',
        isSpinning: false,
      }
    case 'error':
      return {
        icon: <AlertCircle size={13} className="text-error flex-none" />,
        label: errorMessage || 'Failed · needs attention',
        isSpinning: false,
      }
    case 'blocked':
      return {
        icon: <Ban size={13} className="text-warning flex-none" />,
        label: errorMessage || 'Blocked by upstream error',
        isSpinning: false,
      }
    case 'cancelled':
      return {
        icon: <XCircle size={13} className="text-text-muted flex-none" />,
        label: 'Cancelled',
        isSpinning: false,
      }
    case 'queued':
      return {
        icon: <Clock3 size={13} className="text-text-muted flex-none" />,
        label: 'Queued in DAG',
        isSpinning: false,
      }
    case 'reading':
      return {
        icon: <LoaderCircle size={13} className="spin text-accent flex-none" />,
        label: 'Reading & parsing source',
        isSpinning: true,
      }
    case 'interpreting':
      return {
        icon: <LoaderCircle size={13} className="spin text-accent flex-none" />,
        label: 'Interpreting semantics (M2.2)',
        isSpinning: true,
      }
    case 'rendering':
      return {
        icon: <LoaderCircle size={13} className="spin text-accent flex-none" />,
        label: 'Rendering native artifact (M3)',
        isSpinning: true,
      }
    case 'validating':
      return {
        icon: <LoaderCircle size={13} className="spin text-accent flex-none" />,
        label: 'Validating artifact output',
        isSpinning: true,
      }
    case 'running':
      return {
        icon: <LoaderCircle size={13} className="spin text-accent flex-none" />,
        label: 'Processing…',
        isSpinning: true,
      }
    case 'ready':
      return {
        icon: <Check size={13} className="text-success flex-none" />,
        label: isInput ? 'Uploaded · source ready' : 'Connected · ready to transform',
        isSpinning: false,
      }
    case 'idle':
    default:
      return {
        icon: <Clock3 size={13} className="text-text-muted flex-none" />,
        label: isInput ? 'Uploaded · source ready' : 'Waiting for source input',
        isSpinning: false,
      }
  }
}

function DocumentNode({ data, selected }: NodeProps<DocumentFlowNode>) {
  const info = formats.find((format) => format.id === data.format)!
  const Icon = formatIcons[data.format]
  const color = formatColors[data.format]
  const isInput = data.direction === 'source'
  const sourceFormatInfo = data.sourceFormat ? formats.find((f) => f.id === data.sourceFormat) : null

  const statusInfo = getStatusDetails(data.status, isInput, data.errorMessage)
  const isComplete = data.status === 'complete'
  const canDownload = isComplete && Boolean(data.downloadUrl)

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!data.downloadUrl) return
    try {
      await downloadArtifact(data.downloadUrl, data.filename)
    } catch (err) {
      window.dispatchEvent(
        new CustomEvent('transmute-notice', {
          detail: err instanceof Error ? err.message : 'Artifact download failed.',
        }),
      )
    }
  }

  return (
    <article
      className={`document-node ${selected ? 'selected' : ''}`}
      style={{ '--node-accent': color } as CSSProperties}
      data-node-id={data.documentId}
      data-status={data.status}
    >
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <header className="node-header">
        <span className="format-icon" style={{ color, backgroundColor: `${color}16` }}>
          <Icon size={17} />
        </span>
        <span className="node-kind">
          {isInput ? 'SOURCE DOCUMENT' : `TRANSFORMED OUTPUT (${info.extension.toUpperCase()})`}
        </span>
        <button type="button" className="icon-button node-menu" aria-label="Node options">
          <MoreHorizontal size={17} />
        </button>
      </header>

      <div className="node-file">
        <strong title={data.filename}>{data.filename}</strong>
        <span>
          {info.label} <i>·</i> {info.extension.slice(1).toUpperCase()}
          {!isInput && sourceFormatInfo && (
            <span className="text-text-faint ml-1">
              (from {sourceFormatInfo.label})
            </span>
          )}
        </span>
      </div>

      <div className="node-status">
        {statusInfo.icon}
        <span className="truncate" title={statusInfo.label}>{statusInfo.label}</span>
        {statusInfo.isSpinning && <span className="progress-track"><i /></span>}
      </div>

      {!isInput && (
        <div className="node-instruction" title={data.instruction || 'No specific prompt instructions'}>
          <Sparkles size={12} className="flex-none" />
          <span className="truncate">
            {data.instruction || 'Add an instruction to guide the transformation'}
          </span>
        </div>
      )}

      <footer className="node-actions">
        <button
          type="button"
          disabled={!isComplete}
          title={isComplete ? 'Preview generated artifact' : 'Preview available once complete'}
          aria-label="Preview output"
        >
          <Eye size={13} /> Preview
        </button>
        <button
          type="button"
          disabled={!canDownload}
          onClick={handleDownload}
          title={canDownload ? 'Download output file' : 'Output file available once complete'}
          aria-label="Download output"
        >
          <Download size={13} /> Download
        </button>
      </footer>

      {isInput && <span className="source-port"><Upload size={10} /> INPUT</span>}
      <Handle type="source" position={Position.Right} className="flow-handle" />
      {isInput && <span className="edge-caption"><ArrowRight size={11} /> CONNECT TO TRANSFORM</span>}
    </article>
  )
}

export default memo(DocumentNode)
