import { useState } from 'react'
import { ChevronDown, ChevronUp, Plus, Sparkles } from 'lucide-react'
import { formatColors, formatIcons, formats } from '../../utils/formats'
import type { Format } from '../../types/workflow'
import { Tooltip } from '../ui/Tooltip'
import '../../enhancements.css'

interface FormatPaletteProps {
  onAdd: (format: Format) => void
  /** Whether the palette can be collapsed. */
  collapsible?: boolean
}

/**
 * Format selection palette displayed over the canvas.
 * Lists all supported document formats with one-click add to canvas.
 */
export function FormatPalette({ onAdd, collapsible = true }: FormatPaletteProps) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div
      className="format-palette"
      role="region"
      aria-label="Document format palette"
    >
      <div className="palette-heading">
        <div>
          <strong>Formats</strong>
          <span>{collapsed ? `${formats.length} available` : 'Click to add a node'}</span>
        </div>
        {collapsible ? (
          <Tooltip content={collapsed ? 'Expand formats' : 'Collapse formats'}>
            <button
              type="button"
              className="icon-button"
              onClick={() => setCollapsed(!collapsed)}
              aria-label={collapsed ? 'Expand format palette' : 'Collapse format palette'}
              aria-expanded={!collapsed}
            >
              {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            </button>
          </Tooltip>
        ) : (
          <Tooltip content="Add a format node to the canvas">
            <button type="button" className="icon-button" aria-label="More formats">
              <Plus size={16} />
            </button>
          </Tooltip>
        )}
      </div>

      {!collapsed && (
        <>
          <div className="format-list">
            {formats.map(({ id, label, extension, description }) => {
              const Icon = formatIcons[id]
              return (
                <Tooltip key={id} content={description} position="right" delay={600}>
                  <button
                    type="button"
                    className="format-item"
                    onClick={() => onAdd(id)}
                    aria-label={`Add ${label} node to canvas`}
                  >
                    <span
                      className="palette-icon"
                      style={{
                        color: formatColors[id],
                        backgroundColor: `${formatColors[id]}16`,
                      }}
                    >
                      <Icon size={16} />
                    </span>
                    <span className="format-copy">
                      <strong>{label}</strong>
                      <small>{extension}</small>
                    </span>
                    <Plus className="format-add" size={14} />
                  </button>
                </Tooltip>
              )
            })}
          </div>

          <div className="palette-note">
            <span className="spark-mini">
              <Sparkles size={11} />
            </span>
            <span>
              Transformations use AI to create a new artefact from your content.
            </span>
          </div>
        </>
      )}
    </div>
  )
}
