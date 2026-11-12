import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

interface EmptyStateProps {
  /** Lucide icon to display. */
  icon: LucideIcon
  /** Primary headline. */
  title: string
  /** Descriptive text beneath the headline. */
  description?: string
  /** Optional action button(s). */
  children?: ReactNode
  /** Additional class on the wrapper. */
  className?: string
  /** Visual style variant. */
  variant?: 'default' | 'compact'
}

/**
 * Consistent empty-state placeholder used across panels, lists, and inspectors.
 * Follows the existing visual language (dark card, muted text, centered layout).
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
  className = '',
  variant = 'default',
}: EmptyStateProps) {
  const isCompact = variant === 'compact'

  return (
    <div
      className={`flex flex-col items-center justify-center text-center ${
        isCompact ? 'gap-2 py-4 px-3' : 'gap-3 py-8 px-5'
      } ${className}`}
    >
      <div
        className={`grid place-items-center rounded-3xl border border-border-prominent bg-surface-hover text-accent ${
          isCompact ? 'h-8 w-8' : 'h-[42px] w-[42px]'
        }`}
      >
        <Icon size={isCompact ? 16 : 22} />
      </div>
      <strong
        className={`font-semibold text-text-primary ${
          isCompact ? 'text-sm' : 'text-base'
        }`}
      >
        {title}
      </strong>
      {description && (
        <span
          className={`max-w-[240px] leading-relaxed text-text-muted ${
            isCompact ? 'text-xs' : 'text-sm'
          }`}
        >
          {description}
        </span>
      )}
      {children && (
        <div className={`flex items-center gap-2 ${isCompact ? 'mt-1' : 'mt-2'}`}>
          {children}
        </div>
      )}
    </div>
  )
}
