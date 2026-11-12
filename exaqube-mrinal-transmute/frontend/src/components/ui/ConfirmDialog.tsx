import { useEffect, useRef, type ReactNode, type KeyboardEvent } from 'react'
import { AlertTriangle, X } from 'lucide-react'

interface ConfirmDialogProps {
  /** Whether the dialog is visible. */
  open: boolean
  /** Called when the user confirms the action. */
  onConfirm: () => void
  /** Called when the user cancels or dismisses the dialog. */
  onCancel: () => void
  /** Dialog title. */
  title: string
  /** Descriptive body text. */
  description?: string
  /** Text for the confirm button. */
  confirmLabel?: string
  /** Text for the cancel button. */
  cancelLabel?: string
  /** Visual variant — destructive shows a red confirm button. */
  variant?: 'default' | 'destructive'
  /** Optional icon or custom header content. */
  children?: ReactNode
}

/**
 * Modal confirmation dialog with focus trap and keyboard support.
 * Used for destructive actions (delete node, clear canvas, etc.).
 */
export function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  children,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  /* Focus the cancel button (safe default) when dialog opens */
  useEffect(() => {
    if (open) {
      /* Small delay to let animation start */
      const timer = setTimeout(() => confirmRef.current?.focus(), 50)
      return () => clearTimeout(timer)
    }
  }, [open])

  if (!open) return null

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onCancel()
    }
    /* Basic focus trap */
    if (event.key === 'Tab' && dialogRef.current) {
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  }

  const isDestructive = variant === 'destructive'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-[2px] animate-fade-in"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby={description ? 'confirm-desc' : undefined}
        className="w-[min(380px,90vw)] rounded-xl border border-border-strong bg-surface-overlay p-5 shadow-overlay animate-scale-in"
      >
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-3">
            {isDestructive && (
              <div className="flex h-8 w-8 flex-none items-center justify-center rounded-lg border border-error-bg bg-error-bg/30 text-error">
                <AlertTriangle size={16} />
              </div>
            )}
            <h2 id="confirm-title" className="text-xl font-semibold font-display text-text-primary">
              {title}
            </h2>
          </div>
          <button
            onClick={onCancel}
            className="grid h-6 w-6 flex-none place-items-center rounded-md text-text-muted transition-colors hover:bg-surface-active hover:text-text-secondary"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {description && (
          <p id="confirm-desc" className="text-sm leading-relaxed text-text-tertiary mb-4">
            {description}
          </p>
        )}

        {children && <div className="mb-4">{children}</div>}

        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            onClick={onCancel}
            className="h-8 rounded-md border border-border-strong bg-surface-hover px-3.5 text-sm font-semibold text-text-secondary transition-colors hover:bg-surface-active hover:text-text-primary"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`h-8 rounded-md px-3.5 text-sm font-semibold transition-colors ${
              isDestructive
                ? 'bg-error/90 text-white hover:bg-error'
                : 'bg-accent text-white hover:bg-accent-dim'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
