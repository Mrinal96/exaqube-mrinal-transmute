import { useState, type ReactNode } from 'react'
import type { Edge } from '@xyflow/react'
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Download,
  FileText,
  GitFork,
  Hash,
  Info,
  Link2,
  Sparkles,
  X,
} from 'lucide-react'
import type { DocumentFlowNode } from '../../types/workflow'
import { formatColors, formatIcons, formats } from '../../utils/formats'
import { EmptyState } from '../ui/EmptyState'
import { StatusIndicator } from '../ui/StatusIndicator'
import { Tooltip } from '../ui/Tooltip'
import type { DocumentMetadata, DocumentIR } from '../../services/api'
import '../../enhancements.css'

interface PropertiesPanelProps {
  selectedNode?: DocumentFlowNode
  onInstructionChange: (nodeId: string, value: string) => void
  /** Optional metadata from the upload response, keyed by node ID. */
  documentMetadata?: Record<string, DocumentMetadata>
  /** Optional IR data for the selected document, keyed by node ID. */
  documentIRs?: Record<string, DocumentIR>
  /** Optional callback when user clicks close panel. */
  onClose?: () => void
  /** Canvas edges to inspect incoming/outgoing connections. */
  edges?: Edge[]
  /** All canvas nodes to resolve connection names. */
  allNodes?: DocumentFlowNode[]
}

/** Collapsible property group with label. */
function PropertyGroup({
  label,
  hint,
  defaultOpen = true,
  children,
}: {
  label: string
  hint?: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="property-group">
      <label>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1 bg-transparent p-0 text-inherit cursor-pointer"
          aria-expanded={open}
        >
          {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          {label}
        </button>
        {hint && <span>{hint}</span>}
      </label>
      {open && children}
    </div>
  )
}

export function PropertiesPanel({
  selectedNode,
  onInstructionChange,
  documentMetadata = {},
  documentIRs = {},
  onClose,
  edges = [],
  allNodes = [],
}: PropertiesPanelProps) {
  const node = selectedNode
  const info = node ? formats.find((format) => format.id === node.data.format)! : undefined
  const Icon = node ? formatIcons[node.data.format] : FileText
  const metadata = node ? documentMetadata[node.id] : undefined
  const ir = node ? documentIRs[node.id] : undefined

  // Connections
  const incomingEdges = edges.filter((e) => e.target === node?.id)
  const outgoingEdges = edges.filter((e) => e.source === node?.id)
  const incomingNodes = incomingEdges
    .map((e) => allNodes.find((n) => n.id === e.source))
    .filter(Boolean) as DocumentFlowNode[]
  const outgoingNodes = outgoingEdges
    .map((e) => allNodes.find((n) => n.id === e.target))
    .filter(Boolean) as DocumentFlowNode[]

  return (
    <aside className="properties-panel" aria-label="Properties inspector">
      <div className="properties-header">
        <div>
          <span>CONFIGURATION</span>
          <h3>Properties</h3>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip content="Properties inspector — view and configure the selected node">
            <button className="icon-button" aria-label="Properties help">
              <CircleHelp size={16} />
            </button>
          </Tooltip>
          {onClose && (
            <Tooltip content="Close properties panel">
              <button
                className="icon-button"
                onClick={onClose}
                aria-label="Close properties panel"
              >
                <X size={16} />
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      {node ? (
        <>
          {/* ── Selected file header ── */}
          <div className="selected-file">
            <div
              className="selected-icon"
              style={{
                color: formatColors[node.data.format],
                backgroundColor: `${formatColors[node.data.format]}16`,
              }}
            >
              <Icon size={18} />
            </div>
            <div>
              <strong title={node.data.filename}>{node.data.filename}</strong>
              <span>
                {info?.label} · {info?.extension}
              </span>
            </div>
          </div>

          {/* ── Node status ── */}
          <PropertyGroup label="NODE STATUS">
            <div className="property-value status-value">
              <StatusIndicator status={node.data.status} variant="dot" />
              {node.data.status === 'idle'
                ? 'Waiting for source'
                : node.data.status === 'ready'
                  ? 'Extraction complete'
                  : node.data.status}
            </div>
          </PropertyGroup>

          {/* ── Document ID (if uploaded) ── */}
          {metadata && (
            <PropertyGroup label="DOCUMENT ID">
              <div className="property-value">
                <Hash size={11} className="flex-none text-text-muted" />
                <Tooltip content={node.id} position="bottom">
                  <code
                    className="truncate font-mono text-xs text-text-secondary cursor-default"
                    title={node.id}
                  >
                    {node.id.slice(0, 8)}…{node.id.slice(-4)}
                  </code>
                </Tooltip>
              </div>
            </PropertyGroup>
          )}

          {/* ── Upload metadata (if available) ── */}
          {metadata && (
            <PropertyGroup label="UPLOAD DETAILS">
              <div className="flex flex-col gap-1.5 rounded border border-border-muted bg-surface-input p-2.5">
                <MetadataRow label="Size" value={formatBytes(metadata.size_bytes)} />
                <MetadataRow label="Type" value={metadata.detected_mime} />
                <MetadataRow
                  label="Uploaded"
                  value={formatDate(metadata.uploaded_at)}
                />
                <MetadataRow
                  label="SHA-256"
                  value={metadata.sha256.slice(0, 12) + '…'}
                  title={metadata.sha256}
                />
                {metadata.warnings.length > 0 && (
                  <MetadataRow
                    label="Warnings"
                    value={`${metadata.warnings.length} extraction note${metadata.warnings.length > 1 ? 's' : ''}`}
                    className="text-warning"
                  />
                )}
              </div>
            </PropertyGroup>
          )}

          {/* ── IR summary (if available) ── */}
          {ir && (
            <PropertyGroup label="EXTRACTED STRUCTURE">
              <div className="flex flex-col gap-1.5 rounded border border-border-muted bg-surface-input p-2.5">
                {ir.title && <MetadataRow label="Title" value={ir.title} />}
                <MetadataRow label="Schema" value={`v${ir.schema_version}`} />
                <MetadataRow label="Sections" value={String(countSections(ir.sections))} />
                <MetadataRow
                  label="Blocks"
                  value={String(countBlocks(ir.sections) + ir.blocks.length)}
                />
                <MetadataRow label="Entities" value={String(ir.entities.length)} />
                <MetadataRow label="Facts" value={String(ir.facts.length)} />
                <MetadataRow label="Assets" value={String(ir.assets.length)} />
              </div>
            </PropertyGroup>
          )}

          {/* ── Conversion route ── */}
          <PropertyGroup label="FORMAT & ROUTE">
            <div className="format-route">
              <div>
                <ArrowUpRight size={13} />
                <span>Source</span>
                <b>
                  {node.data.direction === 'source'
                    ? info?.id.toUpperCase()
                    : incomingNodes.length > 0
                      ? incomingNodes.map((n) => n.data.format.toUpperCase()).join(', ')
                      : 'None'}
                </b>
              </div>
              <ArrowDownRight size={14} />
              <div>
                <ArrowDownRight size={13} />
                <span>Target</span>
                <b>
                  {node.data.direction === 'output'
                    ? info?.id.toUpperCase()
                    : outgoingNodes.length > 0
                      ? outgoingNodes.map((n) => n.data.format.toUpperCase()).join(', ')
                      : '—'}
                </b>
              </div>
            </div>
          </PropertyGroup>

          {/* ── Graph Connections ── */}
          <PropertyGroup label="GRAPH CONNECTIONS" hint={`${incomingNodes.length} in · ${outgoingNodes.length} out`}>
            <div className="flex flex-col gap-2 rounded border border-border-muted bg-surface-input p-2 text-2xs font-mono">
              <div>
                <span className="text-text-faint uppercase block text-3xs mb-1 flex items-center gap-1">
                  <Link2 size={10} /> Incoming from ({incomingNodes.length})
                </span>
                {incomingNodes.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {incomingNodes.map((inNode) => (
                      <span
                        key={inNode.id}
                        className="rounded bg-surface-card px-1.5 py-0.5 text-text-secondary border border-border-subtle truncate max-w-[200px]"
                        title={inNode.data.filename}
                      >
                        {inNode.data.filename} ({inNode.data.format.toUpperCase()})
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-text-muted italic">
                    {node.data.direction === 'source' ? 'Root source document' : 'Disconnected (needs source connection)'}
                  </span>
                )}
              </div>

              <div className="border-t border-border-subtle pt-1.5">
                <span className="text-text-faint uppercase block text-3xs mb-1 flex items-center gap-1">
                  <GitFork size={10} /> Feeds into ({outgoingNodes.length})
                </span>
                {outgoingNodes.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {outgoingNodes.map((outNode) => (
                      <span
                        key={outNode.id}
                        className="rounded bg-surface-card px-1.5 py-0.5 text-text-secondary border border-border-subtle truncate max-w-[200px]"
                        title={outNode.data.filename}
                      >
                        {outNode.data.filename} ({outNode.data.format.toUpperCase()})
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-text-muted italic">
                    {node.data.direction === 'output' ? 'Terminal output node' : 'Not connected to any transformations'}
                  </span>
                )}
              </div>
            </div>
          </PropertyGroup>

          {/* ── Instruction ── */}
          <PropertyGroup label="TRANSFORMATION INSTRUCTION" hint="PROMPT">
            <div className="space-y-1">
              <textarea
                placeholder="Describe what you want the new artefact to communicate…"
                value={node.data.instruction}
                onChange={(event) => onInstructionChange(node.id, event.target.value)}
                aria-label="Transformation instruction"
                className="w-full"
              />
              <div className="flex justify-between text-3xs font-mono text-text-faint">
                <span>Guides layout & emphasis</span>
                <span>{node.data.instruction.length} chars</span>
              </div>
            </div>
          </PropertyGroup>

          {/* ── Output metadata ── */}
          <PropertyGroup label="OUTPUT ARTIFACT METADATA">
            {node.data.artifactId || node.data.downloadUrl ? (
              <div className="flex flex-col gap-1.5 rounded border border-border-muted bg-surface-input p-2.5">
                {node.data.artifactId && <MetadataRow label="Artifact ID" value={node.data.artifactId} />}
                {node.data.planId && <MetadataRow label="Plan ID" value={node.data.planId} />}
                <MetadataRow label="Status" value={node.data.status} />
                {node.data.downloadUrl && (
                  <div className="pt-1 border-t border-border-subtle">
                    <a
                      href={node.data.downloadUrl}
                      download={node.data.filename}
                      className="flex items-center justify-center gap-1.5 rounded bg-accent px-2 py-1 text-2xs font-semibold text-text-inverse hover:bg-accent-hover"
                    >
                      <Download size={11} /> Download Artifact
                    </a>
                  </div>
                )}
              </div>
            ) : (
              <div className="metadata-empty">
                <Info size={15} />
                <span>Output artifact details will appear after workflow execution.</span>
              </div>
            )}
          </PropertyGroup>

          {/* ── Semantic note ── */}
          <div className="semantic-note">
            <Sparkles size={14} />
            <span>
              Transmute interprets your content to create a useful new artefact.
            </span>
          </div>
        </>
      ) : (
        <EmptyState
          icon={FileText}
          title="Select a node"
          description="Choose a document on the canvas to view and edit its properties."
          className="h-[calc(100%-65px)]"
        />
      )}
    </aside>
  )
}

/* ── Sub-components ── */

function MetadataRow({
  label,
  value,
  title,
  className = '',
}: {
  label: string
  value: string
  title?: string
  className?: string
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="font-mono text-2xs text-text-faint uppercase tracking-wider flex-none">
        {label}
      </span>
      <span
        className={`truncate text-right font-mono text-xs text-text-secondary ${className}`}
        title={title ?? value}
      >
        {value}
      </span>
    </div>
  )
}

/* ── Helpers ── */

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function countSections(sections: DocumentIR['sections']): number {
  return sections.reduce(
    (total, section) => total + 1 + countSections(section.children),
    0,
  )
}

function countBlocks(sections: DocumentIR['sections']): number {
  return sections.reduce(
    (total, section) =>
      total + section.blocks.length + countBlocks(section.children),
    0,
  )
}
