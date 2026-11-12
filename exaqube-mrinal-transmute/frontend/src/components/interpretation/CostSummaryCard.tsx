import { useState } from 'react'
import { Check, Coins, Copy, Hash } from 'lucide-react'
import type { UsageSummary, LLMTokenUsage, CostPricing, ApiDecimal } from '../../types/interpretation'

interface CostSummaryCardProps {
  runId?: string
  usage?: UsageSummary | LLMTokenUsage | null
  estimatedCost?: ApiDecimal | null
  pricing?: CostPricing
  reused?: boolean
}

export function formatCost(cost?: ApiDecimal | null): string {
  if (cost === null || cost === undefined) return 'Not configured'

  let amount: number
  if (typeof cost === 'number') {
    amount = cost
  } else if (typeof cost === 'string') {
    const trimmed = cost.trim()
    if (!trimmed) return 'Unavailable'
    const lower = trimmed.toLowerCase()
    if (lower === 'not configured') return 'Not configured'
    if (lower === 'unavailable') return 'Unavailable'
    amount = Number(trimmed)
  } else {
    return 'Unavailable'
  }

  if (!Number.isFinite(amount)) return 'Unavailable'
  if (amount === 0) return '$0.00'
  if (Math.abs(amount) < 0.01) {
    const formatted = amount.toFixed(4)
    if (formatted === '0.0000' && amount > 0) {
      return `$${amount.toFixed(6).replace(/0+$/, '')}`
    }
    return `$${formatted}`
  }
  return `$${amount.toFixed(2)}`
}

export function CostSummaryCard({
  runId,
  usage,
  estimatedCost,
  pricing,
  reused,
}: CostSummaryCardProps) {
  const [copiedRunId, setCopiedRunId] = useState<string | null>(null)
  const inTokens = usage
    ? ('input_tokens' in usage ? usage.input_tokens : 'prompt_tokens' in usage ? usage.prompt_tokens : null)
    : null
  const outTokens = usage
    ? ('output_tokens' in usage ? usage.output_tokens : 'completion_tokens' in usage ? usage.completion_tokens : null)
    : null
  const totalTokens = usage?.total_tokens ?? null

  const copyRunId = async () => {
    if (!runId) return
    try {
      await navigator.clipboard.writeText(runId)
      setCopiedRunId(runId)
    } catch {
      setCopiedRunId(null)
    }
  }

  return (
    <div className="rounded-lg border border-border-muted bg-surface-input p-3 space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 text-text-muted font-medium">
          <Coins size={13} className="text-warning" />
          Cost & Execution
        </span>
        {reused && (
          <span className="rounded bg-accent-bg px-1.5 py-0.5 font-mono text-2xs text-accent-lighter border border-accent-border">
            Reused cache
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 pt-1 border-t border-border-subtle text-xs">
        <div>
          <span className="block font-mono text-2xs text-text-faint uppercase">EST. COST</span>
          <strong className="font-mono text-xs text-text-primary">
            {formatCost(estimatedCost)}
          </strong>
        </div>
        <div>
          <span className="block font-mono text-2xs text-text-faint uppercase">TOTAL TOKENS</span>
          <strong className="font-mono text-xs text-text-secondary">
            {totalTokens !== null && totalTokens !== undefined
              ? totalTokens.toLocaleString()
              : '—'}
          </strong>
        </div>
      </div>

      {(inTokens !== null || outTokens !== null) && (
        <div className="flex items-center gap-3 text-2xs font-mono text-text-muted">
          <span>In: {inTokens?.toLocaleString() ?? 'Unavailable'}</span>
          <span>·</span>
          <span>Out: {outTokens?.toLocaleString() ?? 'Unavailable'}</span>
        </div>
      )}

      {runId && (
        <div className="flex items-start gap-1.5 pt-1 border-t border-border-subtle text-2xs text-text-faint">
          <Hash size={10} className="flex-none mt-0.5" />
          <div className="min-w-0 flex-1">
            <span className="block font-mono uppercase">Run ID</span>
            <code className="block break-all font-mono text-text-secondary" title={runId}>
              {runId}
            </code>
          </div>
          <button
            type="button"
            onClick={() => void copyRunId()}
            className="flex-none rounded p-1 text-text-muted hover:bg-surface-active hover:text-text-primary focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
            aria-label={copiedRunId === runId ? 'Run ID copied' : 'Copy run ID'}
            title={copiedRunId === runId ? 'Copied' : 'Copy run ID'}
          >
            {copiedRunId === runId ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </div>
      )}

      {pricing && (
        <div className="text-2xs text-text-faint pt-0.5">
          {pricing.pricing_version
            ? `Pricing: ${pricing.pricing_version} (${pricing.currency})`
            : 'Pricing: not configured'}
        </div>
      )}
    </div>
  )
}
