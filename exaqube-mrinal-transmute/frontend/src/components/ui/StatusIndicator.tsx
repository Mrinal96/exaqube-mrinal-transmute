import type { ExecutionStatus } from '../../types/execution'
import {
  Check,
  Clock3,
  LoaderCircle,
  AlertCircle,
  Pause,
  Ban,
  BookOpen,
  Sparkles,
  Paintbrush,
  ShieldCheck,
  CircleDot,
  type LucideIcon,
} from 'lucide-react'

export type { ExecutionStatus }

interface StatusConfig {
  label: string
  icon: LucideIcon
  colorClass: string
  bgClass: string
  borderClass: string
  dotClass: string
  animate?: boolean
}

const statusMap: Record<ExecutionStatus, StatusConfig> = {
  idle: {
    label: 'Idle',
    icon: Clock3,
    colorClass: 'text-text-muted',
    bgClass: 'bg-surface-hover',
    borderClass: 'border-border-strong',
    dotClass: 'bg-text-muted',
  },
  ready: {
    label: 'Ready',
    icon: Check,
    colorClass: 'text-success',
    bgClass: 'bg-success-bg/30',
    borderClass: 'border-success-bg',
    dotClass: 'bg-success',
  },
  queued: {
    label: 'Queued',
    icon: CircleDot,
    colorClass: 'text-accent-subtle',
    bgClass: 'bg-accent-bg/50',
    borderClass: 'border-accent-border',
    dotClass: 'bg-accent-subtle animate-pulse-dot',
  },
  reading: {
    label: 'Reading',
    icon: BookOpen,
    colorClass: 'text-info',
    bgClass: 'bg-info/10',
    borderClass: 'border-info/20',
    dotClass: 'bg-info',
    animate: true,
  },
  interpreting: {
    label: 'Interpreting',
    icon: Sparkles,
    colorClass: 'text-accent-light',
    bgClass: 'bg-accent-bg/50',
    borderClass: 'border-accent-border',
    dotClass: 'bg-accent-light',
    animate: true,
  },
  rendering: {
    label: 'Rendering',
    icon: Paintbrush,
    colorClass: 'text-warning',
    bgClass: 'bg-warning/10',
    borderClass: 'border-warning-bg',
    dotClass: 'bg-warning',
    animate: true,
  },
  validating: {
    label: 'Validating',
    icon: ShieldCheck,
    colorClass: 'text-cyan',
    bgClass: 'bg-cyan/10',
    borderClass: 'border-cyan/20',
    dotClass: 'bg-cyan',
    animate: true,
  },
  running: {
    label: 'Processing',
    icon: LoaderCircle,
    colorClass: 'text-accent-subtle',
    bgClass: 'bg-accent-bg/50',
    borderClass: 'border-accent-border',
    dotClass: 'bg-accent-subtle',
    animate: true,
  },
  complete: {
    label: 'Complete',
    icon: Check,
    colorClass: 'text-success',
    bgClass: 'bg-success-bg/30',
    borderClass: 'border-success-bg',
    dotClass: 'bg-success',
  },
  done: {
    label: 'Done',
    icon: Check,
    colorClass: 'text-success',
    bgClass: 'bg-success-bg/30',
    borderClass: 'border-success-bg',
    dotClass: 'bg-success',
  },
  error: {
    label: 'Error',
    icon: AlertCircle,
    colorClass: 'text-error',
    bgClass: 'bg-error-bg/30',
    borderClass: 'border-error-bg',
    dotClass: 'bg-error',
  },
  failed: {
    label: 'Failed',
    icon: AlertCircle,
    colorClass: 'text-error',
    bgClass: 'bg-error-bg/30',
    borderClass: 'border-error-bg',
    dotClass: 'bg-error',
  },
  cancelled: {
    label: 'Cancelled',
    icon: Ban,
    colorClass: 'text-text-muted',
    bgClass: 'bg-surface-hover',
    borderClass: 'border-border-strong',
    dotClass: 'bg-text-disabled',
  },
  blocked: {
    label: 'Blocked',
    icon: Pause,
    colorClass: 'text-warning',
    bgClass: 'bg-warning/10',
    borderClass: 'border-warning-bg',
    dotClass: 'bg-warning',
  },
}

interface StatusIndicatorProps {
  /** Current status. */
  status: ExecutionStatus
  /** Display variant. */
  variant?: 'dot' | 'pill' | 'icon' | 'full'
  /** Additional class names. */
  className?: string
  /** Custom label override. */
  label?: string
  /** Size for the icon variant. */
  size?: number
}

/**
 * Versatile status indicator supporting multiple visual representations.
 * Use `dot` for inline status, `pill` for badges, `icon` for compact, `full` for detailed.
 */
export function StatusIndicator({
  status,
  variant = 'pill',
  className = '',
  label,
  size = 13,
}: StatusIndicatorProps) {
  const config = statusMap[status] ?? statusMap.idle
  const displayLabel = label ?? config.label
  const Icon = config.icon

  if (variant === 'dot') {
    return (
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${config.dotClass} ${className}`}
        title={displayLabel}
        aria-label={displayLabel}
      />
    )
  }

  if (variant === 'icon') {
    return (
      <span className={`inline-flex ${config.colorClass} ${className}`} title={displayLabel}>
        <Icon size={size} className={config.animate ? 'animate-spin-slow' : ''} />
      </span>
    )
  }

  if (variant === 'full') {
    return (
      <div
        className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm font-medium ${config.bgClass} ${config.borderClass} ${config.colorClass} ${className}`}
      >
        <Icon size={size} className={config.animate ? 'animate-spin-slow' : ''} />
        <span>{displayLabel}</span>
      </div>
    )
  }

  /* Default: pill */
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-sans text-xs ${config.bgClass} ${config.borderClass} ${config.colorClass} ${className}`}
    >
      <span className={`inline-block h-[5px] w-[5px] rounded-full ${config.dotClass}`} />
      {displayLabel}
    </span>
  )
}

/** Hook helper: get the status config for programmatic use. */
export function getStatusConfig(status: ExecutionStatus): StatusConfig {
  return statusMap[status] ?? statusMap.idle
}
