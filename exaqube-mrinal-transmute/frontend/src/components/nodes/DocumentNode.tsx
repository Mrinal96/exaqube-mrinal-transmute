import { memo, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  AlertCircle,
  ArrowRight,
  Ban,
  Check,
  ChevronRight,
  Clock3,
  Download,
  Edit3,
  Eye,
  FileCode,
  LoaderCircle,
  MoreHorizontal,
  RotateCcw,
  Sliders,
  Sparkles,
  Trash2,
  Upload,
  X,
  XCircle,
} from 'lucide-react'
import type { DocumentFlowNode, RunStatus } from '../../types/workflow'
import { formatColors, formatIcons, formats } from '../../utils/formats'
import { downloadArtifact, type DocumentFormat } from '../../services/api'

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

function DocumentNode({ id, data, selected }: NodeProps<DocumentFlowNode>) {
  const info = formats.find((format) => format.id === data.format)!
  const Icon = formatIcons[data.format]
  const color = formatColors[data.format]
  const isInput = data.direction === 'source'
  const sourceFormatInfo = data.sourceFormat ? formats.find((f) => f.id === data.sourceFormat) : null

  const statusInfo = getStatusDetails(data.status, isInput, data.errorMessage)
  const isComplete = data.status === 'complete'
  const canDownload = isComplete && Boolean(data.downloadUrl)

  // Interactive menu & instruction state
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [showFormatSubmenu, setShowFormatSubmenu] = useState(false)
  const [isEditingInstruction, setIsEditingInstruction] = useState(false)
  const [instructionDraft, setInstructionDraft] = useState(data.instruction || '')

  const menuRef = useRef<HTMLDivElement>(null)
  const instructionInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!isEditingInstruction) {
      setInstructionDraft(data.instruction || '')
    }
  }, [data.instruction, isEditingInstruction])

  useEffect(() => {
    if (isEditingInstruction && instructionInputRef.current) {
      instructionInputRef.current.focus()
      instructionInputRef.current.select()
    }
  }, [isEditingInstruction])

  // Close menu on outside click or Escape
  useEffect(() => {
    if (!isMenuOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsMenuOpen(false)
        setShowFormatSubmenu(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMenuOpen(false)
        setShowFormatSubmenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isMenuOpen])

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

  const handlePreview = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!data.downloadUrl) return
    window.dispatchEvent(
      new CustomEvent('transmute-preview-artifact', {
        detail: {
          nodeId: id,
          downloadUrl: data.downloadUrl,
          filename: data.filename,
          format: data.format,
        },
      }),
    )
  }

  const handleSaveInstruction = () => {
    window.dispatchEvent(
      new CustomEvent('transmute-update-instruction', {
        detail: { nodeId: id, instruction: instructionDraft },
      }),
    )
    setIsEditingInstruction(false)
  }

  const handleOpenProperties = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsMenuOpen(false)
    window.dispatchEvent(
      new CustomEvent('transmute-select-node', {
        detail: { nodeId: id },
      }),
    )
  }

  const handleInspectIR = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsMenuOpen(false)
    window.dispatchEvent(
      new CustomEvent('transmute-inspect-node', {
        detail: { nodeId: id, documentId: data.documentId || id },
      }),
    )
  }

  const handleDeleteNode = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsMenuOpen(false)
    window.dispatchEvent(
      new CustomEvent('transmute-delete-node', {
        detail: { nodeId: id },
      }),
    )
  }

  const handleChangeFormat = (newFormat: DocumentFormat, e: React.MouseEvent) => {
    e.stopPropagation()
    setIsMenuOpen(false)
    setShowFormatSubmenu(false)
    window.dispatchEvent(
      new CustomEvent('transmute-change-format', {
        detail: { nodeId: id, format: newFormat },
      }),
    )
  }

  const handleClearOutput = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsMenuOpen(false)
    window.dispatchEvent(
      new CustomEvent('transmute-clear-artifact', {
        detail: { nodeId: id },
      }),
    )
  }

  return (
    <article
      className={`document-node ${selected ? 'selected' : ''}`}
      style={{ '--node-accent': color } as CSSProperties}
      data-node-id={data.documentId || id}
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
        <div className="relative flex items-center" ref={menuRef}>
          <button
            type="button"
            className="icon-button node-menu nodrag"
            aria-label="Node options"
            aria-expanded={isMenuOpen}
            onClick={(e) => {
              e.stopPropagation()
              setIsMenuOpen((prev) => !prev)
              setShowFormatSubmenu(false)
            }}
          >
            <MoreHorizontal size={17} />
          </button>

          {isMenuOpen && (
            <div
              className="node-dropdown-menu nodrag"
              onClick={(e) => e.stopPropagation()}
            >
              {isInput ? (
                <>
                  <button
                    type="button"
                    className="node-dropdown-item"
                    onClick={handleInspectIR}
                  >
                    <FileCode size={13} className="text-accent flex-none" />
                    <span>Inspect Extracted IR</span>
                  </button>
                  <button
                    type="button"
                    className="node-dropdown-item"
                    onClick={handleOpenProperties}
                  >
                    <Sliders size={13} className="flex-none" />
                    <span>Configure Properties</span>
                  </button>
                  <div className="node-dropdown-divider" />
                  <button
                    type="button"
                    className="node-dropdown-item danger"
                    onClick={handleDeleteNode}
                  >
                    <Trash2 size={13} className="flex-none" />
                    <span>Delete Node</span>
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="node-dropdown-item"
                    onClick={(e) => {
                      e.stopPropagation()
                      setIsMenuOpen(false)
                      handleOpenProperties(e)
                      setIsEditingInstruction(true)
                    }}
                  >
                    <Edit3 size={13} className="text-accent flex-none" />
                    <span>Edit Prompt Instruction</span>
                  </button>
                  <button
                    type="button"
                    className="node-dropdown-item justify-between"
                    onClick={(e) => {
                      e.stopPropagation()
                      setShowFormatSubmenu((prev) => !prev)
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <RotateCcw size={13} className="flex-none" />
                      <span>Change Target Format</span>
                    </div>
                    <ChevronRight size={12} className="text-text-muted flex-none" />
                  </button>
                  {showFormatSubmenu && (
                    <div className="node-format-submenu">
                      {formats.map((fmt) => (
                        <button
                          key={fmt.id}
                          type="button"
                          className={`node-format-option ${data.format === fmt.id ? 'active' : ''}`}
                          onClick={(e) => handleChangeFormat(fmt.id, e)}
                        >
                          <span
                            className="w-2 h-2 rounded-full mr-1.5 flex-none"
                            style={{ backgroundColor: formatColors[fmt.id] }}
                          />
                          <span className="font-semibold uppercase">{fmt.id}</span>
                          <span className="text-text-faint text-3xs ml-1">({fmt.label})</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    className="node-dropdown-item"
                    onClick={handleOpenProperties}
                  >
                    <Sliders size={13} className="flex-none" />
                    <span>Configure Properties</span>
                  </button>
                  {(data.artifactId || data.downloadUrl || data.status === 'error') && (
                    <button
                      type="button"
                      className="node-dropdown-item"
                      onClick={handleClearOutput}
                    >
                      <RotateCcw size={13} className="flex-none" />
                      <span>Clear Output Artifact</span>
                    </button>
                  )}
                  {canDownload && (
                    <button
                      type="button"
                      className="node-dropdown-item"
                      onClick={(e) => {
                        setIsMenuOpen(false)
                        void handleDownload(e)
                      }}
                    >
                      <Download size={13} className="flex-none" />
                      <span>Download Artifact</span>
                    </button>
                  )}
                  {isComplete && (
                    <button
                      type="button"
                      className="node-dropdown-item"
                      onClick={(e) => {
                        setIsMenuOpen(false)
                        handlePreview(e)
                      }}
                    >
                      <Eye size={13} className="flex-none" />
                      <span>Preview Artifact</span>
                    </button>
                  )}
                  <div className="node-dropdown-divider" />
                  <button
                    type="button"
                    className="node-dropdown-item danger"
                    onClick={handleDeleteNode}
                  >
                    <Trash2 size={13} className="flex-none" />
                    <span>Delete Node</span>
                  </button>
                </>
              )}
            </div>
          )}
        </div>
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
        isEditingInstruction ? (
          <div
            className="node-instruction-editing nodrag"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={instructionInputRef}
              type="text"
              className="node-instruction-input"
              placeholder="Describe layout & emphasis…"
              value={instructionDraft}
              onChange={(e) => setInstructionDraft(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation()
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handleSaveInstruction()
                } else if (e.key === 'Escape') {
                  setIsEditingInstruction(false)
                  setInstructionDraft(data.instruction || '')
                }
              }}
            />
            <button
              type="button"
              className="icon-button instruction-btn save-btn nodrag"
              title="Save instruction (Enter)"
              onClick={(e) => {
                e.stopPropagation()
                handleSaveInstruction()
              }}
            >
              <Check size={12} />
            </button>
            <button
              type="button"
              className="icon-button instruction-btn cancel-btn nodrag"
              title="Cancel (Esc)"
              onClick={(e) => {
                e.stopPropagation()
                setIsEditingInstruction(false)
                setInstructionDraft(data.instruction || '')
              }}
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="node-instruction nodrag clickable text-left w-full"
            title={data.instruction ? `Prompt: ${data.instruction}` : 'Click to add an instruction or edit properties'}
            onClick={(e) => {
              e.stopPropagation()
              window.dispatchEvent(new CustomEvent('transmute-select-node', { detail: { nodeId: id } }))
              setIsEditingInstruction(true)
            }}
          >
            <Sparkles size={12} className="flex-none text-accent" />
            <span className="truncate flex-1">
              {data.instruction || 'Add an instruction to guide the transformation'}
            </span>
            <Edit3 size={11} className="instruction-edit-icon flex-none" />
          </button>
        )
      )}

      <footer className="node-actions">
        <button
          type="button"
          className="nodrag"
          disabled={!isComplete}
          onClick={handlePreview}
          title={isComplete ? 'Preview generated artifact' : 'Preview available once complete'}
          aria-label="Preview output"
        >
          <Eye size={13} /> Preview
        </button>
        <button
          type="button"
          className="nodrag"
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
