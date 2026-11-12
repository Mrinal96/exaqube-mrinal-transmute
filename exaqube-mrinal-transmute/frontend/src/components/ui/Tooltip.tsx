import { useState, useRef, useEffect, type ReactNode } from 'react'

interface TooltipProps {
  /** The tooltip content. Can be a string or JSX. */
  content: ReactNode
  /** Tooltip placement relative to the trigger. */
  position?: 'top' | 'bottom' | 'left' | 'right'
  /** Delay before showing (ms). */
  delay?: number
  /** The trigger element(s). */
  children: ReactNode
  /** Additional class names for the wrapper. */
  className?: string
  /** Whether the tooltip is disabled. */
  disabled?: boolean
}

/**
 * Lightweight tooltip that renders on hover/focus with a short delay.
 * Uses CSS positioning — no portal needed for our use-cases.
 */
export function Tooltip({
  content,
  position = 'top',
  delay = 400,
  children,
  className = '',
  disabled = false,
}: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const show = () => {
    if (disabled) return
    timeoutRef.current = setTimeout(() => setVisible(true), delay)
  }

  const hide = () => {
    if (timeoutRef.current !== undefined) {
      clearTimeout(timeoutRef.current)
    }
    setVisible(false)
  }

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== undefined) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const positionClasses: Record<string, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
  }

  return (
    <span
      className={`relative inline-flex ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {visible && content && (
        <span
          role="tooltip"
          className={`absolute z-50 whitespace-nowrap rounded-md border border-border-strong bg-surface-card px-2 py-1 font-sans text-xs text-text-secondary shadow-dropdown animate-fade-in pointer-events-none ${positionClasses[position]}`}
        >
          {content}
        </span>
      )}
    </span>
  )
}
