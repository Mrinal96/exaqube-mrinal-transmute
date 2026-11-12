import { useState } from 'react'
import { AlertTriangle, FileText, Link2, X } from 'lucide-react'
import type { DocumentIR, IRBlock, IRSection } from '../../services/api'

interface DocumentInspectorProps {
  document: DocumentIR
  onClose: () => void
}

export function DocumentInspector({ document, onClose }: DocumentInspectorProps) {
  const blockCount = countBlocks(document.sections) + document.blocks.length
  return <div className="inspector-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="document-inspector" role="dialog" aria-modal="true" aria-labelledby="inspector-title">
      <header className="inspector-header"><div className="inspector-file-icon"><FileText size={18} /></div><div className="inspector-title-copy"><span>CANONICAL INTERMEDIATE REPRESENTATION</span><h2 id="inspector-title">{document.title || document.filename}</h2><p>{document.filename} <i>·</i> {document.source_format.toUpperCase()} <i>·</i> {blockCount} extracted blocks</p></div><button className="icon-button" onClick={onClose} aria-label="Close inspector"><X size={18} /></button></header>
      <div className="inspector-summary"><div><span>DOCUMENT ID</span><code>{document.document_id}</code></div><div><span>IR SCHEMA</span><code>v{document.schema_version}</code></div><div><span>SECTIONS</span><code>{countSections(document.sections)}</code></div><div><span>METRICS</span><code>{document.metrics.length}</code></div><div><span>CLAIMS</span><code>{document.claims.length}</code></div><div><span>ASSETS</span><code>{document.assets.length}</code></div></div>
      {document.warnings.length > 0 && <div className="inspector-warnings"><AlertTriangle size={15} /><div><strong>Extraction notes</strong>{document.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div></div>}
      <div className="inspector-content"><div className="inspector-content-heading"><strong>Extracted structure</strong><span>Original order and source locations are retained</span></div>
        {document.sections.length > 0 ? document.sections.map((section) => <SectionView key={section.id} section={section} depth={0} />) : document.blocks.map((block) => <BlockView key={block.id} block={block} />)}
        {document.sections.length === 0 && document.blocks.length === 0 && <div className="inspector-empty">No readable text blocks were found. Original file bytes remain stored.</div>}
      </div>
      <footer className="inspector-footer"><span>Extracted by {document.provenance[0]?.extractor ?? 'Transmute reader'} · No LLM interpretation was used</span><button onClick={onClose}>Done</button></footer>
    </section>
  </div>
}

function SectionView({ section, depth }: { section: IRSection; depth: number }) {
  return <section className="ir-section" style={{ marginLeft: Math.min(depth, 5) * 12 }}>
    <header><span className="ir-section-level">{section.level}</span><strong>{section.title}</strong><small>{section.blocks.length} blocks</small></header>
    {section.blocks.map((block) => <BlockView key={block.id} block={block} />)}
    {section.children.map((child) => <SectionView key={child.id} section={child} depth={depth + 1} />)}
  </section>
}

function BlockView({ block }: { block: IRBlock }) {
  const [showAllRows, setShowAllRows] = useState(false)
  const table = block.table
  const rawItems = block.attributes.items
  const items = isStringArray(rawItems) ? rawItems : undefined
  const visibleRows = table ? (showAllRows ? table.rows : table.rows.slice(0, 20)) : []
  const location = block.source.slide_number ? `Slide ${block.source.slide_number}`
    : block.source.sheet_name ? `${block.source.sheet_name}${block.source.cell_range ? ` · ${block.source.cell_range}` : ''}`
      : block.source.line_start ? `Lines ${block.source.line_start}–${block.source.line_end ?? block.source.line_start}`
        : block.source.paragraph_index ? `Paragraph ${block.source.paragraph_index}`
          : block.source.source_part ?? (block.source.element_index ? `Element ${block.source.element_index}` : '')
  return <article className="ir-block"><div className="ir-block-heading"><span>{block.kind}</span>{location && <small>{location}</small>}</div>
    {block.text && <pre>{block.text}</pre>}
    {typeof block.attributes.href === 'string' && <div className="ir-link"><Link2 size={12} /><span>{block.text || 'Link target'}</span><code>{block.attributes.href}</code></div>}
    {table && <div className="ir-table-wrap"><table><thead><tr>{table.headers.map((header, index) => <th key={index}>{formatValue(header)}</th>)}</tr></thead><tbody>{visibleRows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, columnIndex) => <td key={columnIndex}>{formatValue(cell)}</td>)}</tr>)}</tbody></table>{table.rows.length > 20 && <button className="ir-show-rows" onClick={() => setShowAllRows(!showAllRows)}>{showAllRows ? 'Show first 20 rows' : `Show all ${table.rows.length} rows`}</button>}</div>}
    {Array.isArray(block.attributes.series) && <pre>{JSON.stringify(block.attributes.series, null, 2)}</pre>}
    {items && <ol>{items.map((item, index) => <li key={index}>{item}</li>)}</ol>}
  </article>
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item: unknown) => typeof item === 'string')
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function countBlocks(sections: IRSection[]): number {
  return sections.reduce((total, section) => total + section.blocks.length + countBlocks(section.children), 0)
}

function countSections(sections: IRSection[]): number {
  return sections.reduce((total, section) => total + 1 + countSections(section.children), 0)
}
