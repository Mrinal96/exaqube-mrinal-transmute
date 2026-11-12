import type { ReactNode } from 'react'

interface SkeletonProps {
  /** Width class (Tailwind). Defaults to full width. */
  className?: string
}

/**
 * Animated placeholder block for loading states.
 * Uses a subtle shimmer animation on the existing surface palette.
 */
export function Skeleton({ className = 'h-3 w-full' }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded bg-surface-active ${className}`}
      aria-hidden="true"
    />
  )
}

interface SkeletonGroupProps {
  /** Number of skeleton lines to render. */
  lines?: number
  /** Additional class on the container. */
  className?: string
}

/** Renders multiple skeleton lines with varied widths for a realistic text placeholder. */
export function SkeletonGroup({ lines = 3, className = '' }: SkeletonGroupProps) {
  const widths = ['w-full', 'w-4/5', 'w-3/5', 'w-2/3', 'w-5/6', 'w-1/2']
  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-2.5 ${widths[i % widths.length]}`} />
      ))}
    </div>
  )
}

interface SkeletonNodeProps {
  className?: string
}

/** Skeleton that mimics a document node shape for canvas loading states. */
export function SkeletonNode({ className = '' }: SkeletonNodeProps) {
  return (
    <div className={`w-[252px] rounded-2xl border border-border bg-surface-elevated p-3 ${className}`}>
      <div className="flex items-center gap-2 mb-3">
        <Skeleton className="h-6 w-6 rounded-md" />
        <Skeleton className="h-2 w-24" />
      </div>
      <Skeleton className="h-3 w-36 mb-2" />
      <Skeleton className="h-2 w-20 mb-3" />
      <div className="border-t border-border pt-2">
        <Skeleton className="h-2 w-28" />
      </div>
    </div>
  )
}

interface SkeletonPanelProps {
  children?: ReactNode
  className?: string
}

/** Skeleton placeholder for a panel section with a label. */
export function SkeletonPanel({ children, className = '' }: SkeletonPanelProps) {
  return (
    <div className={`space-y-4 ${className}`}>
      <Skeleton className="h-2 w-20" />
      {children ?? (
        <>
          <div className="rounded border border-border bg-surface-input p-2.5">
            <SkeletonGroup lines={2} />
          </div>
          <Skeleton className="h-2 w-16 mt-4" />
          <div className="rounded border border-border bg-surface-input p-2.5">
            <SkeletonGroup lines={3} />
          </div>
        </>
      )}
    </div>
  )
}
