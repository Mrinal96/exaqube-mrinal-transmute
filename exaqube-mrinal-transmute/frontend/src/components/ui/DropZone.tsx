import { useState, useCallback, useRef, type DragEvent, type ReactNode, type ChangeEvent } from 'react'
import { Upload, AlertCircle, FileUp } from 'lucide-react'

const SUPPORTED_EXTENSIONS = ['pptx', 'xlsx', 'docx', 'mmd', 'html'] as const
const MAX_SIZE_BYTES = 10 * 1024 * 1024

interface DropZoneProps {
  /** Called with the validated file when a valid document is dropped. */
  onFileDrop: (file: File) => void
  /** Called when an invalid file is dropped. Receives the rejection reason. */
  onReject?: (reason: string) => void
  /** Whether the drop zone is disabled (e.g. during an active upload). */
  disabled?: boolean
  /** Additional class names for the wrapper. */
  className?: string
  /** Custom children to render inside the drop zone. */
  children?: ReactNode
}

type DropState = 'idle' | 'valid' | 'invalid'

/**
 * Drag-and-drop file upload zone for the workflow canvas.
 * Validates file extension and size on drag-over for instant feedback.
 * Designed as an overlay that activates when files are dragged over the canvas.
 */
export function DropZone({
  onFileDrop,
  onReject,
  disabled = false,
  className = '',
  children,
}: DropZoneProps) {
  const [dropState, setDropState] = useState<DropState>('idle')
  const dragCounter = useRef(0)

  const getExtension = (filename: string): string => {
    const parts = filename.split('.')
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
  }

  const validateFile = useCallback((file: File): string | null => {
    const ext = getExtension(file.name)
    if (!SUPPORTED_EXTENSIONS.includes(ext as typeof SUPPORTED_EXTENSIONS[number])) {
      return `Unsupported format (.${ext || '?'}). Use PPTX, XLSX, DOCX, MMD, or HTML.`
    }
    if (file.size > MAX_SIZE_BYTES) {
      return `File is too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum is 10 MB.`
    }
    return null
  }, [])

  const checkDragItems = useCallback((event: DragEvent): DropState => {
    const items = event.dataTransfer?.items
    if (!items || items.length === 0) return 'invalid'
    /* During dragover, browsers may not expose filenames. Best-effort check. */
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind !== 'file') return 'invalid'
    }
    return 'valid'
  }, [])

  const handleDragEnter = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      event.stopPropagation()
      if (disabled) return
      dragCounter.current++
      setDropState(checkDragItems(event))
    },
    [disabled, checkDragItems],
  )

  const handleDragLeave = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      event.stopPropagation()
      dragCounter.current--
      if (dragCounter.current <= 0) {
        dragCounter.current = 0
        setDropState('idle')
      }
    },
    [],
  )

  const handleDragOver = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      event.stopPropagation()
      if (!disabled) {
        event.dataTransfer.dropEffect = 'copy'
      }
    },
    [disabled],
  )

  const handleDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      event.stopPropagation()
      dragCounter.current = 0
      setDropState('idle')

      if (disabled) return

      const files = event.dataTransfer?.files
      if (!files || files.length === 0) return

      const file = files[0]
      const error = validateFile(file)
      if (error) {
        onReject?.(error)
        return
      }
      onFileDrop(file)
    },
    [disabled, validateFile, onFileDrop, onReject],
  )

  const isActive = dropState !== 'idle'

  return (
    <div
      className={`relative ${className}`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {children}

      {/* Overlay shown only when dragging files over */}
      {isActive && (
        <div
          className={`absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed backdrop-blur-[2px] transition-colors ${
            dropState === 'valid'
              ? 'border-accent bg-accent/5'
              : 'border-error bg-error/5'
          }`}
        >
          <div
            className={`grid h-12 w-12 place-items-center rounded-2xl border ${
              dropState === 'valid'
                ? 'border-accent-border bg-accent-bg text-accent-subtle'
                : 'border-error-bg bg-error-bg/30 text-error'
            }`}
          >
            {dropState === 'valid' ? <FileUp size={22} /> : <AlertCircle size={22} />}
          </div>
          <span
            className={`font-semibold text-base ${
              dropState === 'valid' ? 'text-accent-lighter' : 'text-error'
            }`}
          >
            {dropState === 'valid' ? 'Drop to upload' : 'Unsupported file type'}
          </span>
          <span className="text-xs text-text-muted">
            {dropState === 'valid'
              ? 'PPTX · XLSX · DOCX · MMD · HTML — up to 10 MB'
              : 'Only PPTX, XLSX, DOCX, MMD, and HTML files are supported'}
          </span>
        </div>
      )}
    </div>
  )
}

/** Compact drop zone suitable for use inside panels or upload areas. */
export function DropZoneCompact({
  onFileDrop,
  onReject,
  disabled = false,
  className = '',
}: Omit<DropZoneProps, 'children'>) {
  const [dropState, setDropState] = useState<DropState>('idle')
  const fileInput = useRef<HTMLInputElement>(null)

  const handleDragOver = (event: DragEvent) => {
    event.preventDefault()
    if (!disabled) {
      event.dataTransfer.dropEffect = 'copy'
      setDropState('valid')
    }
  }

  const handleDragLeave = (event: DragEvent) => {
    event.preventDefault()
    setDropState('idle')
  }

  const handleDrop = (event: DragEvent) => {
    event.preventDefault()
    setDropState('idle')
    if (disabled) return
    const file = event.dataTransfer?.files?.[0]
    if (!file) return
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (!SUPPORTED_EXTENSIONS.includes(ext as typeof SUPPORTED_EXTENSIONS[number])) {
      onReject?.(`Unsupported format (.${ext}).`)
      return
    }
    if (file.size > MAX_SIZE_BYTES) {
      onReject?.('File exceeds 10 MB limit.')
      return
    }
    onFileDrop(file)
  }

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) onFileDrop(file)
    event.target.value = ''
  }

  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-6 transition-colors cursor-pointer ${
        dropState === 'valid'
          ? 'border-accent bg-accent/5'
          : 'border-border-strong bg-surface-input hover:border-border-prominent hover:bg-surface-hover'
      } ${disabled ? 'pointer-events-none opacity-50' : ''} ${className}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => fileInput.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          fileInput.current?.click()
        }
      }}
      aria-label="Upload a document"
    >
      <input
        ref={fileInput}
        type="file"
        accept=".pptx,.xlsx,.docx,.mmd,.html"
        hidden
        onChange={handleFileSelect}
      />
      <Upload size={18} className="text-text-muted" />
      <span className="text-sm font-medium text-text-secondary">
        Drop a file or <span className="text-accent-light">browse</span>
      </span>
      <span className="text-xs text-text-faint">
        PPTX · XLSX · DOCX · MMD · HTML — 10 MB max
      </span>
    </div>
  )
}
