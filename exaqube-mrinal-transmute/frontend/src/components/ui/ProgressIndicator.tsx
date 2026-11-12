interface ProgressIndicatorProps {
  /** Progress value from 0 to 100. */
  value: number
  /** Visual variant. */
  variant?: 'bar' | 'ring'
  /** Size for ring variant (px). */
  size?: number
  /** Whether to show the percentage label. */
  showLabel?: boolean
  /** Color variant. */
  color?: 'accent' | 'success' | 'warning' | 'info'
  /** Additional class names. */
  className?: string
}

const colorMap = {
  accent: {
    track: 'bg-border-strong',
    fill: 'bg-accent',
    stroke: 'stroke-accent',
    trackStroke: 'stroke-border-strong',
    text: 'text-accent-lighter',
  },
  success: {
    track: 'bg-border-strong',
    fill: 'bg-success',
    stroke: 'stroke-success',
    trackStroke: 'stroke-border-strong',
    text: 'text-success-light',
  },
  warning: {
    track: 'bg-border-strong',
    fill: 'bg-warning',
    stroke: 'stroke-warning',
    trackStroke: 'stroke-border-strong',
    text: 'text-warning-light',
  },
  info: {
    track: 'bg-border-strong',
    fill: 'bg-info',
    stroke: 'stroke-info',
    trackStroke: 'stroke-border-strong',
    text: 'text-info',
  },
}

/**
 * Progress indicator in bar or ring form.
 * Bar is used for uploads and inline progress. Ring for compact dashboard views.
 */
export function ProgressIndicator({
  value,
  variant = 'bar',
  size = 28,
  showLabel = false,
  color = 'accent',
  className = '',
}: ProgressIndicatorProps) {
  const clamped = Math.max(0, Math.min(100, value))
  const colors = colorMap[color]

  if (variant === 'ring') {
    const strokeWidth = 2.5
    const radius = (size - strokeWidth * 2) / 2
    const circumference = 2 * Math.PI * radius
    const offset = circumference - (clamped / 100) * circumference

    return (
      <span className={`relative inline-flex items-center justify-center ${className}`}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={strokeWidth}
            className={colors.trackStroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className={`${colors.stroke} transition-[stroke-dashoffset] duration-300 ease-out`}
          />
        </svg>
        {showLabel && (
          <span
            className={`absolute font-mono text-2xs font-medium ${colors.text}`}
          >
            {Math.round(clamped)}
          </span>
        )}
      </span>
    )
  }

  /* Bar variant */
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div
        className={`h-[3px] flex-1 overflow-hidden rounded-full ${colors.track}`}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-200 ease-out ${colors.fill}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className={`font-mono text-xs tabular-nums ${colors.text}`}>
          {Math.round(clamped)}%
        </span>
      )}
    </div>
  )
}
