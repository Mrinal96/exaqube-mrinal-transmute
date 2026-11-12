import { MapPin } from 'lucide-react'
import type { SourceReference, SourceLocation } from '../../types/interpretation'

interface SourceReferenceListProps {
  references: SourceReference[]
  maxVisible?: number
}

export function formatSourceLocation(loc?: SourceLocation | null): string {
  if (!loc) return ''
  const parts: string[] = []
  if (loc.slide_number !== null && loc.slide_number !== undefined) {
    parts.push(`Slide ${loc.slide_number}`)
  }
  if (loc.sheet_name) {
    parts.push(loc.sheet_name + (loc.cell_range ? ` (${loc.cell_range})` : ''))
  }
  if (loc.section_path && loc.section_path.length > 0) {
    parts.push(loc.section_path.join(' > '))
  }
  if (loc.line_start !== null && loc.line_start !== undefined) {
    parts.push(`L${loc.line_start}${loc.line_end ? `–${loc.line_end}` : ''}`)
  }
  if (loc.paragraph_index !== null && loc.paragraph_index !== undefined) {
    parts.push(`¶${loc.paragraph_index}`)
  }
  if (loc.source_part) {
    parts.push(loc.source_part)
  }
  return parts.join(' · ') || 'Document source'
}

export function SourceReferenceList({ references, maxVisible = 3 }: SourceReferenceListProps) {
  if (!references || references.length === 0) return null

  const visible = references.slice(0, maxVisible)
  const remaining = references.length - maxVisible

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
      {visible.map((ref, idx) => {
        const text = formatSourceLocation(ref.source_location)
        return (
          <span
            key={idx}
            className="inline-flex items-center gap-1 rounded bg-surface-active px-1.5 py-0.5 font-mono text-2xs text-text-muted border border-border-subtle"
            title={`Block: ${ref.block_id ?? 'n/a'}, Section: ${ref.section_id ?? 'n/a'}`}
          >
            <MapPin size={9} className="text-accent-subtle flex-none" />
            <span className="truncate max-w-[200px]">{text}</span>
          </span>
        )
      })}
      {remaining > 0 && (
        <span className="font-mono text-2xs text-text-faint">
          +{remaining} more
        </span>
      )}
    </div>
  )
}
