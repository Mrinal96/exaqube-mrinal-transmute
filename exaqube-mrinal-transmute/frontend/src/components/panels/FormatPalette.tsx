import { Plus } from 'lucide-react'
import { formatColors, formatIcons, formats } from '../../utils/formats'
import type { Format } from '../../types/workflow'

interface FormatPaletteProps { onAdd: (format: Format) => void }

export function FormatPalette({ onAdd }: FormatPaletteProps) {
  return <div className="format-palette"><div className="palette-heading"><div><strong>Formats</strong><span>Click to add a node</span></div><button className="icon-button" aria-label="More formats"><Plus size={16} /></button></div><div className="format-list">{formats.map(({ id, label, extension }) => { const Icon = formatIcons[id]; return <button key={id} className="format-item" onClick={() => onAdd(id)}><span className="palette-icon" style={{ color: formatColors[id], backgroundColor: `${formatColors[id]}16` }}><Icon size={16} /></span><span className="format-copy"><strong>{label}</strong><small>{extension}</small></span><Plus className="format-add" size={14} /></button> })}</div><div className="palette-note"><SparklesMini /> Transformations use AI to create a new artefact from your content.</div></div>
}

function SparklesMini() { return <span className="spark-mini">✦</span> }

