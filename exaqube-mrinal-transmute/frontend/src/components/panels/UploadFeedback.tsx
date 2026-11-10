import { AlertTriangle, CheckCircle2, LoaderCircle, X } from 'lucide-react'
import type { DocumentMetadata } from '../../services/api'

export type UploadPhase = 'uploading' | 'extracting' | 'complete' | 'error'

interface UploadFeedbackProps {
  phase: UploadPhase
  progress: number
  document?: DocumentMetadata
  error?: string
  onInspect: () => void
  onDismiss: () => void
}

export function UploadFeedback({ phase, progress, document, error, onInspect, onDismiss }: UploadFeedbackProps) {
  const active = phase === 'uploading' || phase === 'extracting'
  return <div className={`upload-feedback ${phase}`} role={phase === 'error' ? 'alert' : 'status'} aria-live="polite">
    <div className="upload-feedback-icon">{active ? <LoaderCircle className="upload-spinner" size={17} /> : phase === 'complete' ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}</div>
    <div className="upload-feedback-copy">
      <strong>{phase === 'uploading' ? `Uploading document · ${progress}%` : phase === 'extracting' ? 'Extracting document structure…' : phase === 'complete' ? `Extracted ${document?.filename ?? 'document'}` : 'Document upload failed'}</strong>
      {phase === 'uploading' && <div className="upload-progress-track"><i style={{ width: `${progress}%` }} /></div>}
      {phase === 'extracting' && <span>Reading slides, sheets, paragraphs, or diagram structure</span>}
      {phase === 'complete' && <span>{document?.format.toUpperCase()} · {formatBytes(document?.size_bytes ?? 0)} · Extraction complete</span>}
      {phase === 'error' && <span>{error}</span>}
    </div>
    {phase === 'complete' && <button className="inspect-ir-button" onClick={onInspect}>Inspect structure</button>}
    <button className="icon-button" onClick={onDismiss} aria-label="Dismiss upload status"><X size={15} /></button>
  </div>
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
