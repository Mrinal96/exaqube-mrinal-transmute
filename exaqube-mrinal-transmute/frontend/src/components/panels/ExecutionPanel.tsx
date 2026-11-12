import { useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  Clock3,
  Coins,
  TerminalSquare,
  Trash2,
} from 'lucide-react'
import { StatusIndicator } from '../ui/StatusIndicator'
import { EmptyState } from '../ui/EmptyState'
import { Tooltip } from '../ui/Tooltip'
import type { ExecutionLogEntry, ExecutionRun } from '../../types/execution'
import { EXECUTION_PHASES, phaseDescriptions } from '../../types/execution'
import { formatCost } from '../interpretation/CostSummaryCard'
import '../../enhancements.css'

interface ExecutionPanelProps {
  expanded: boolean
  onToggle: () => void
  /** Optional current run data. When undefined, shows the idle/empty state. */
  currentRun?: ExecutionRun
  /** Historical runs. */
  runHistory?: ExecutionRun[]
  /** Optional callback to clear the activity log. */
  onClearLogs?: () => void
  /** Optional callback when user clicks a run in the history list. */
  onSelectRun?: (run: ExecutionRun) => void
}

type TabId = 'activity' | 'history' | 'pipeline'

export function ExecutionPanel({
  expanded,
  onToggle,
  currentRun,
  runHistory = [],
  onClearLogs,
  onSelectRun,
}: ExecutionPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('activity')

  const status = currentRun?.status ?? 'idle'
  const isIdle = !currentRun || status === 'idle'
  const duration = currentRun?.durationMs
  const cost = currentRun?.estimatedCost
  const hasEntries = (currentRun?.entries?.length ?? 0) > 0

  return (
    <section
      className={`execution-panel ${expanded ? 'expanded' : ''}`}
      aria-label="Execution panel"
    >
      {/* ── Toggle bar ── */}
      <button
        type="button"
        className="execution-toggle"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <div className="execution-title">
          <TerminalSquare size={15} />
          <strong>Execution</strong>
          <StatusIndicator status={isIdle ? 'idle' : status} variant="pill" />
        </div>
        <div className="execution-summary">
          <span>
            <Clock3 size={13} />
            {duration !== undefined ? formatDuration(duration) : '—'}
          </span>
          <span>
            <Coins size={13} />
            {cost !== undefined ? formatCost(cost) : '—'}
          </span>
          {expanded ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        </div>
      </button>

      {/* ── Expanded body ── */}
      {expanded && (
        <div className="execution-body">
          {/* Tab bar */}
          <div className="log-tabs flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                type="button"
                className={activeTab === 'activity' ? 'selected' : ''}
                onClick={() => setActiveTab('activity')}
              >
                Activity log {hasEntries && <span>{currentRun?.entries.length}</span>}
              </button>
              <button
                type="button"
                className={activeTab === 'pipeline' ? 'selected' : ''}
                onClick={() => setActiveTab('pipeline')}
              >
                Pipeline
              </button>
              <button
                type="button"
                className={activeTab === 'history' ? 'selected' : ''}
                onClick={() => setActiveTab('history')}
              >
                Run history <span>{runHistory.length}</span>
              </button>
            </div>
            {activeTab === 'activity' && hasEntries && onClearLogs && (
              <Tooltip content="Clear activity log">
                <button
                  type="button"
                  onClick={onClearLogs}
                  className="icon-button mr-2"
                  aria-label="Clear activity log"
                >
                  <Trash2 size={13} />
                </button>
              </Tooltip>
            )}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-auto">
            {activeTab === 'activity' && (
              <ActivityLogTab entries={currentRun?.entries ?? []} />
            )}
            {activeTab === 'pipeline' && (
              <PipelineTab
                currentPhase={isIdle ? undefined : currentRun?.status}
                error={currentRun?.error}
              />
            )}
            {activeTab === 'history' && (
              <RunHistoryTab
                runs={runHistory}
                activeRunId={currentRun?.id}
                onSelectRun={(run) => {
                  onSelectRun?.(run)
                  setActiveTab('activity')
                }}
              />
            )}
          </div>
        </div>
      )}
    </section>
  )
}

/* ── Activity Log Tab ── */

function ActivityLogTab({ entries }: { entries: ExecutionLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <EmptyState
        icon={TerminalSquare}
        title="No execution events"
        description="Run a workflow to see progress, logs, and output details here."
        variant="compact"
      />
    )
  }

  return (
    <div className="flex flex-col gap-px p-2" role="log" aria-label="Activity log">
      {entries.map((entry) => (
        <LogEntryRow key={entry.id} entry={entry} />
      ))}
    </div>
  )
}

function LogEntryRow({ entry }: { entry: ExecutionLogEntry }) {
  return (
    <div className="group flex items-start gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors hover:bg-surface-hover">
      <StatusIndicator status={entry.status} variant="icon" size={12} className="mt-0.5 flex-none" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-text-secondary truncate">{entry.message}</span>
          {entry.nodeLabel && (
            <span className="flex-none rounded bg-surface-active px-1.5 py-0.5 font-mono text-2xs text-text-muted">
              {entry.nodeLabel}
            </span>
          )}
        </div>
        {entry.error && (
          <p className="mt-1 text-xs text-error leading-relaxed">{entry.error}</p>
        )}
      </div>
      <span className="flex-none font-mono text-2xs text-text-faint tabular-nums">
        {formatTimestamp(entry.timestamp)}
      </span>
      {entry.durationMs !== undefined && (
        <span className="flex-none font-mono text-2xs text-text-faint tabular-nums">
          {formatDuration(entry.durationMs)}
        </span>
      )}
    </div>
  )
}

/* ── Pipeline Tab ── */

function PipelineTab({ currentPhase, error }: { currentPhase?: string; error?: string }) {
  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-mono text-2xs tracking-wider text-text-muted uppercase">
          Execution Pipeline
        </span>
        {!currentPhase && (
          <span className="text-xs text-text-faint">Not started</span>
        )}
      </div>
      <div className="flex items-center gap-1">
        {EXECUTION_PHASES.map((phase, index) => {
          const phaseIndex = currentPhase
            ? EXECUTION_PHASES.indexOf(currentPhase as typeof EXECUTION_PHASES[number])
            : -1
          const isCompleted = phaseIndex >= 0 && index < phaseIndex
          const isCurrent = currentPhase === phase
          const isPending = !isCompleted && !isCurrent

          return (
            <div key={phase} className="flex items-center gap-1 flex-1">
              <div
                className={`flex h-7 flex-1 items-center justify-center rounded-md border text-2xs font-medium transition-colors ${
                  isCompleted
                    ? 'border-success-bg bg-success-bg/30 text-success'
                    : isCurrent
                      ? 'border-accent-border bg-accent-bg text-accent-lighter'
                      : 'border-border bg-surface-input text-text-faint'
                } ${isPending ? 'opacity-50' : ''}`}
                title={phaseDescriptions[phase]}
              >
                {phase.charAt(0).toUpperCase() + phase.slice(1)}
              </div>
              {index < EXECUTION_PHASES.length - 1 && (
                <div
                  className={`h-px w-2 flex-none ${
                    isCompleted ? 'bg-success/50' : 'bg-border'
                  }`}
                />
              )}
            </div>
          )
        })}
      </div>
      {error && (
        <div className="mt-2 rounded border border-error/30 bg-error/10 px-2.5 py-1.5 text-xs text-error leading-relaxed">
          <strong>Execution error: </strong>{error}
        </div>
      )}
    </div>
  )
}

/* ── Run History Tab ── */

function RunHistoryTab({
  runs,
  activeRunId,
  onSelectRun,
}: {
  runs: ExecutionRun[]
  activeRunId?: string
  onSelectRun?: (run: ExecutionRun) => void
}) {
  if (runs.length === 0) {
    return (
      <EmptyState
        icon={Clock3}
        title="No run history"
        description="Previous workflow executions will appear here."
        variant="compact"
      />
    )
  }

  return (
    <div className="flex flex-col gap-px p-2" role="list" aria-label="Run history list">
      {runs.map((run) => {
        const isSelected = run.id === activeRunId
        return (
          <button
            type="button"
            key={run.id}
            onClick={() => onSelectRun?.(run)}
            className={`w-full text-left flex items-center gap-3 rounded-md px-2.5 py-2 transition-colors cursor-pointer border ${
              isSelected
                ? 'bg-surface-active border-accent/40'
                : 'bg-transparent border-transparent hover:bg-surface-hover'
            }`}
            title="Click to view activity log for this run"
          >
            <StatusIndicator status={run.status} variant="dot" />
            <span className="flex-1 truncate text-sm text-text-secondary font-mono">
              Run {run.id.slice(0, 8)}
            </span>
            <span className="font-mono text-2xs text-text-faint tabular-nums">
              {run.nodesProcessed}/{run.nodesTotal} nodes
            </span>
            {run.durationMs !== undefined && (
              <span className="font-mono text-2xs text-text-faint tabular-nums">
                {formatDuration(run.durationMs)}
              </span>
            )}
            <StatusIndicator status={run.status} variant="pill" />
          </button>
        )
      })}
    </div>
  )
}

/* ── Helpers ── */

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.round(seconds % 60)
  return `${minutes}m ${remainingSeconds}s`
}

function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso)
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}
