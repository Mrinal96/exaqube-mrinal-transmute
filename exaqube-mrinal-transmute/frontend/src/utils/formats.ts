import { FileSpreadsheet, FileText, FileType2, Presentation, Workflow, type LucideIcon } from 'lucide-react'
import type { Format, FormatInfo } from '../types/workflow'

export const formats: FormatInfo[] = [
  { id: 'pptx', label: 'PowerPoint', extension: '.pptx', description: 'Presentation' },
  { id: 'xlsx', label: 'Spreadsheet', extension: '.xlsx', description: 'Workbook' },
  { id: 'docx', label: 'Report', extension: '.docx', description: 'Word document' },
  { id: 'mmd', label: 'Mermaid', extension: '.mmd', description: 'Diagram source' },
  { id: 'html', label: 'HTML page', extension: '.html', description: 'Interactive page' },
]

export const formatColors: Record<Format, string> = {
  pptx: '#e78955', xlsx: '#54bd91', docx: '#6ea5ed', mmd: '#b39cf2', html: '#49c5c5',
}

export const formatIcons: Record<Format, LucideIcon> = {
  pptx: Presentation,
  xlsx: FileSpreadsheet,
  docx: FileText,
  mmd: Workflow,
  html: FileType2,
}

