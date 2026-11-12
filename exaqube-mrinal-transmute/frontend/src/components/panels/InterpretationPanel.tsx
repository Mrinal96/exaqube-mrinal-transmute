import { useState, useEffect, useCallback } from 'react'
import {
  Brain,
  RefreshCw,
  FileText,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  TrendingUp,
  Tag,
  Link2,
  Lightbulb,
  Shield,
  History,
} from 'lucide-react'
import {
  createInterpretation,
  listInterpretations,
  getInterpretation,
  TransmuteApiError,
} from '../../services/api'
import type {
  DocumentInterpretation,
  InterpretationOperationResponse,
  EvidenceType,
} from '../../types/interpretation'
import { SourceReferenceList } from '../interpretation/SourceReferenceList'
import { CostSummaryCard } from '../interpretation/CostSummaryCard'
import { ProvenanceCard } from '../interpretation/ProvenanceCard'
import { EmptyState } from '../ui/EmptyState'
import { Tooltip } from '../ui/Tooltip'
import { SkeletonGroup } from '../ui/SkeletonLoader'
import '../../enhancements.css'

interface InterpretationPanelProps {
  documentId?: string
  documentFilename?: string
  onInterpretationSelected?: (interpretation: DocumentInterpretation) => void
  activeInterpretation?: DocumentInterpretation | null
}

type TabCategory = 'all' | 'facts' | 'metrics' | 'entities' | 'claims' | 'relationships' | 'insights'

export function InterpretationPanel({
  documentId,
  documentFilename,
  onInterpretationSelected,
  activeInterpretation: externalActiveInterpretation,
}: InterpretationPanelProps) {
  const [instructions, setInstructions] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastResponse, setLastResponse] = useState<InterpretationOperationResponse | null>(null)
  const [interpretation, setInterpretation] = useState<DocumentInterpretation | null>(
    externalActiveInterpretation ?? null,
  )
  const [previousList, setPreviousList] = useState<DocumentInterpretation[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [activeCategory, setActiveCategory] = useState<TabCategory>('all')
  const currentOperation = lastResponse
    && interpretation
    && lastResponse.interpretation.document_id === documentId
    && lastResponse.interpretation.interpretation_id === interpretation.interpretation_id
    ? lastResponse
    : null

  // Sync external interpretation
  useEffect(() => {
    if (externalActiveInterpretation) {
      setInterpretation(externalActiveInterpretation)
    }
  }, [externalActiveInterpretation])

  // Fetch history when documentId changes
  const fetchHistory = useCallback(async (docId: string) => {
    setIsLoadingHistory(true)
    try {
      const res = await listInterpretations(docId)
      setPreviousList(res.items || [])
      if (res.items.length > 0 && !interpretation && !externalActiveInterpretation) {
        setInterpretation(res.items[0])
        onInterpretationSelected?.(res.items[0])
      }
    } catch {
      setPreviousList([])
    } finally {
      setIsLoadingHistory(false)
    }
  }, [interpretation, externalActiveInterpretation, onInterpretationSelected])

  useEffect(() => {
    if (documentId) {
      void fetchHistory(documentId)
    } else {
      setInterpretation(null)
      setPreviousList([])
      setLastResponse(null)
    }
  }, [documentId, fetchHistory])

  // Interpret document handler
  const handleInterpret = async () => {
    if (!documentId || isLoading) return
    setIsLoading(true)
    setError(null)
    setLastResponse(null)

    try {
      const res = await createInterpretation(documentId, {
        instructions: instructions.trim() || undefined,
      })
      setLastResponse(res)
      setInterpretation(res.interpretation)
      onInterpretationSelected?.(res.interpretation)
      void fetchHistory(documentId)
    } catch (err) {
      if (err instanceof TransmuteApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('An unexpected error occurred while interpreting the document.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  // Load selected previous interpretation
  const handleSelectPrevious = async (item: DocumentInterpretation) => {
    if (!documentId) return
    setIsLoading(true)
    setError(null)
    setLastResponse(null)
    try {
      const full = await getInterpretation(documentId, item.interpretation_id)
      setInterpretation(full)
      onInterpretationSelected?.(full)
      setHistoryOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the interpretation.')
    } finally {
      setIsLoading(false)
    }
  }

  if (!documentId) {
    return (
      <aside className="properties-panel" aria-label="Semantic interpretation panel">
        <div className="properties-header">
          <div>
            <span>SEMANTIC EXTRACTION</span>
            <h3>Interpretation</h3>
          </div>
        </div>
        <EmptyState
          icon={Brain}
          title="No document selected"
          description="Upload or select a document on the canvas to run semantic interpretation."
          className="h-[calc(100%-65px)]"
        />
      </aside>
    )
  }

  return (
    <aside className="properties-panel" aria-label="Semantic interpretation panel">
      {/* ── Header ── */}
      <div className="properties-header">
        <div>
          <span>SEMANTIC ANALYSIS (M2.2)</span>
          <h3>Interpretation</h3>
        </div>
        <div className="flex items-center gap-1">
          {previousList.length > 0 && (
            <Tooltip content={historyOpen ? 'Hide saved interpretations' : 'Saved interpretations'}>
              <button
                type="button"
                className={`icon-button ${historyOpen ? 'text-accent' : ''}`}
                onClick={() => setHistoryOpen(!historyOpen)}
                aria-label="Toggle history"
              >
                <History size={16} />
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      {/* ── Document context indicator ── */}
      <div className="flex items-center justify-between border-b border-border pb-3 mb-3 text-xs">
        <div className="flex items-center gap-2 truncate">
          <FileText size={14} className="text-accent flex-none" />
          <span className="truncate font-medium text-text-primary" title={documentFilename}>
            {documentFilename || 'Source document'}
          </span>
        </div>
        <code className="text-2xs font-mono text-text-muted flex-none">
          {documentId.slice(0, 8)}…
        </code>
      </div>

      {/* ── History dropdown ── */}
      {historyOpen && (
        <div className="mb-4 rounded-lg border border-border-strong bg-surface-card p-3 space-y-2">
          <div className="flex items-center justify-between text-xs text-text-muted font-medium">
            <span>Saved Interpretations ({previousList.length})</span>
            {isLoadingHistory && <RefreshCw size={12} className="animate-spin" />}
          </div>
          <div className="max-h-40 overflow-y-auto space-y-1.5 pr-1">
            {previousList.map((item) => {
              const isSelected = item.interpretation_id === interpretation?.interpretation_id
              return (
                <button
                  key={item.interpretation_id}
                  type="button"
                  onClick={() => void handleSelectPrevious(item)}
                  className={`w-full text-left p-2 rounded-md border text-xs transition-colors ${
                    isSelected
                      ? 'border-accent bg-accent-bg/40 text-text-primary'
                      : 'border-border-subtle bg-surface-input text-text-muted hover:border-border hover:text-text-primary'
                  }`}
                >
                  <div className="flex items-center justify-between font-mono text-2xs">
                    <span>{item.interpretation_id.slice(0, 8)}…</span>
                    <span>{new Date(item.provenance.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <p className="text-2xs line-clamp-1 mt-1 text-text-secondary">
                    {item.summary || 'Semantic interpretation'}
                  </p>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Explicit action trigger ── */}
      <div className="space-y-3 pb-3 border-b border-border">
        <div>
          <label className="block text-2xs font-mono text-text-muted uppercase tracking-wider mb-1.5">
            Interpretation Guidance (Optional)
          </label>
          <textarea
            className="w-full rounded border border-border bg-surface-input p-2 text-xs text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-accent resize-none h-16"
            placeholder="e.g. Focus on financial metrics, risk claims, and organizational entities…"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            disabled={isLoading}
          />
        </div>

        <button
          type="button"
          onClick={() => void handleInterpret()}
          disabled={isLoading}
          className={`w-full h-8 rounded-md font-semibold text-xs flex items-center justify-center gap-2 transition-colors ${
            isLoading
              ? 'bg-accent/50 text-white cursor-not-allowed'
              : 'bg-accent text-white hover:bg-accent-dim active:scale-[0.99]'
          }`}
        >
          {isLoading ? (
            <>
              <RefreshCw size={14} className="animate-spin" />
              <span>Interpreting Document…</span>
            </>
          ) : (
            <>
              <Brain size={14} />
              <span>{interpretation ? 'Re-interpret Document' : 'Interpret Document'}</span>
            </>
          )}
        </button>

        {isLoading && (
          <div className="space-y-2 pt-2">
            <span className="text-2xs font-mono text-accent-light block animate-pulse">
              Extracting facts, metrics, entities, and claims…
            </span>
            <SkeletonGroup lines={3} />
          </div>
        )}

        {/* Error notification */}
        {error && (
          <div className="rounded-md bg-error-bg/30 border border-error-bg p-2.5 text-xs text-error flex items-start gap-2">
            <AlertCircle size={15} className="flex-none mt-0.5" />
            <div className="min-w-0">
              <strong className="block font-semibold">Interpretation Failed</strong>
              <span className="text-2xs opacity-90 break-words">{error}</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Active Interpretation Display ── */}
      {interpretation ? (
        <div className="space-y-4 pt-3">
          {/* Metadata & Cost Card */}
          <CostSummaryCard
            runId={currentOperation?.run_id}
            usage={currentOperation?.usage ?? interpretation.provenance.token_usage}
            estimatedCost={currentOperation?.estimated_cost}
            pricing={currentOperation?.pricing}
            reused={currentOperation?.reused}
          />

          {/* Provenance and Mock Status */}
          <ProvenanceCard
            provenance={interpretation.provenance}
            warnings={interpretation.warnings}
          />

          {/* Summary */}
          {interpretation.summary && (
            <div className="rounded-lg border border-border bg-surface-card p-3 space-y-1.5">
              <span className="font-mono text-2xs text-text-muted uppercase tracking-wider block">
                Executive Summary
              </span>
              <p className="text-xs leading-relaxed text-text-secondary">
                {interpretation.summary}
              </p>
            </div>
          )}

          {/* ── Category Filter Tabs ── */}
          <div className="flex flex-wrap gap-1 border-b border-border pb-2 text-2xs font-mono">
            <CategoryTab
              id="all"
              label="All"
              active={activeCategory}
              onClick={setActiveCategory}
            />
            <CategoryTab
              id="facts"
              label={`Facts (${interpretation.facts.length})`}
              active={activeCategory}
              onClick={setActiveCategory}
            />
            <CategoryTab
              id="metrics"
              label={`Metrics (${interpretation.metrics.length})`}
              active={activeCategory}
              onClick={setActiveCategory}
            />
            <CategoryTab
              id="entities"
              label={`Entities (${interpretation.entities.length})`}
              active={activeCategory}
              onClick={setActiveCategory}
            />
            <CategoryTab
              id="claims"
              label={`Claims (${interpretation.claims.length})`}
              active={activeCategory}
              onClick={setActiveCategory}
            />
            <CategoryTab
              id="relationships"
              label={`Relations (${interpretation.relationships.length})`}
              active={activeCategory}
              onClick={setActiveCategory}
            />
            <CategoryTab
              id="insights"
              label={`Insights (${interpretation.insights.length})`}
              active={activeCategory}
              onClick={setActiveCategory}
            />
          </div>

          {/* ── Facts Section ── */}
          {(activeCategory === 'all' || activeCategory === 'facts') && (
            <SectionGroup title="Extracted Facts" count={interpretation.facts.length} icon={CheckCircle2}>
              {interpretation.facts.map((fact, idx) => (
                <div key={idx} className="rounded border border-border-subtle bg-surface-input p-2 text-xs space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-text-primary leading-relaxed">{fact.statement}</p>
                    <ConfidenceBadge confidence={fact.confidence} evidence={fact.evidence_type} />
                  </div>
                  <SourceReferenceList references={fact.source_references} />
                </div>
              ))}
            </SectionGroup>
          )}

          {/* ── Metrics Section ── */}
          {(activeCategory === 'all' || activeCategory === 'metrics') && (
            <SectionGroup title="Key Metrics" count={interpretation.metrics.length} icon={TrendingUp}>
              {interpretation.metrics.map((metric, idx) => (
                <div key={idx} className="rounded border border-border-subtle bg-surface-input p-2 text-xs space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-text-primary font-medium">{metric.name}</strong>
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-xs font-semibold text-accent-light">
                        {metric.currency ?? ''}{metric.value} {metric.unit ?? ''}
                      </span>
                      <ConfidenceBadge confidence={metric.confidence} evidence={metric.evidence_type} />
                    </div>
                  </div>
                  {metric.description && (
                    <p className="text-2xs text-text-muted">{metric.description}</p>
                  )}
                  {metric.reporting_period && (
                    <span className="inline-block text-2xs font-mono text-text-faint">
                      Period: {metric.reporting_period}
                    </span>
                  )}
                  <SourceReferenceList references={metric.source_references} />
                </div>
              ))}
            </SectionGroup>
          )}

          {/* ── Entities Section ── */}
          {(activeCategory === 'all' || activeCategory === 'entities') && (
            <SectionGroup title="Identified Entities" count={interpretation.entities.length} icon={Tag}>
              {interpretation.entities.map((entity, idx) => (
                <div key={idx} className="rounded border border-border-subtle bg-surface-input p-2 text-xs space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-text-primary font-medium">{entity.name}</strong>
                    <div className="flex items-center gap-1.5">
                      <span className="rounded bg-surface-active px-1.5 py-0.5 text-2xs font-mono text-text-muted">
                        {entity.entity_type}
                      </span>
                      <ConfidenceBadge confidence={entity.confidence} />
                    </div>
                  </div>
                  <SourceReferenceList references={entity.source_references} />
                </div>
              ))}
            </SectionGroup>
          )}

          {/* ── Claims Section ── */}
          {(activeCategory === 'all' || activeCategory === 'claims') && (
            <SectionGroup title="Claims & Arguments" count={interpretation.claims.length} icon={Shield}>
              {interpretation.claims.map((claim, idx) => (
                <div key={idx} className="rounded border border-border-subtle bg-surface-input p-2 text-xs space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-text-primary leading-relaxed">{claim.statement}</p>
                    <ConfidenceBadge confidence={claim.confidence} evidence={claim.evidence_type} />
                  </div>
                  <span className="inline-block text-2xs font-mono text-text-faint">
                    Type: {claim.claim_type}
                  </span>
                  <SourceReferenceList references={claim.source_references} />
                </div>
              ))}
            </SectionGroup>
          )}

          {/* ── Relationships Section ── */}
          {(activeCategory === 'all' || activeCategory === 'relationships') && (
            <SectionGroup title="Relationships" count={interpretation.relationships.length} icon={Link2}>
              {interpretation.relationships.map((rel, idx) => (
                <div key={idx} className="rounded border border-border-subtle bg-surface-input p-2 text-xs space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 font-mono text-2xs text-text-secondary">
                      <span>{rel.source_entity_id}</span>
                      <span className="text-accent">→ {rel.relationship_type} →</span>
                      <span>{rel.target_entity_id}</span>
                    </div>
                    <ConfidenceBadge confidence={rel.confidence} />
                  </div>
                  <SourceReferenceList references={rel.source_references} />
                </div>
              ))}
            </SectionGroup>
          )}

          {/* ── Insights Section ── */}
          {(activeCategory === 'all' || activeCategory === 'insights') && (
            <SectionGroup title="Synthesis Insights" count={interpretation.insights.length} icon={Lightbulb}>
              {interpretation.insights.map((insight, idx) => (
                <div key={idx} className="rounded border border-accent-border/30 bg-accent-bg/10 p-2.5 text-xs space-y-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <strong className="text-accent-lighter font-medium">{insight.observation}</strong>
                    <ConfidenceBadge confidence={insight.confidence} evidence={insight.evidence_type} />
                  </div>
                  <p className="text-2xs text-text-muted leading-relaxed">{insight.reasoning}</p>
                  <SourceReferenceList references={insight.supporting_source_references} />
                </div>
              ))}
            </SectionGroup>
          )}
        </div>
      ) : (
        !isLoading && (
          <div className="py-8 text-center text-xs text-text-muted space-y-2">
            <Brain size={24} className="mx-auto text-text-faint opacity-50" />
            <p>No interpretation exists yet for this document.</p>
            <p className="text-2xs text-text-faint">
              Click &quot;Interpret Document&quot; to extract structured facts, metrics, entities, and claims.
            </p>
          </div>
        )
      )}
    </aside>
  )
}

/* ── Micro-components ── */

function CategoryTab({
  id,
  label,
  active,
  onClick,
}: {
  id: TabCategory
  label: string
  active: TabCategory
  onClick: (cat: TabCategory) => void
}) {
  const isSelected = active === id
  return (
    <button
      type="button"
      onClick={() => onClick(id)}
      className={`px-2 py-1 rounded transition-colors ${
        isSelected
          ? 'bg-accent-bg text-accent-lighter border border-accent-border'
          : 'text-text-muted hover:text-text-primary'
      }`}
    >
      {label}
    </button>
  )
}

function SectionGroup({
  title,
  count,
  icon: Icon,
  children,
}: {
  title: string
  count: number
  icon: React.ComponentType<{ size?: number; className?: string }>
  children: React.ReactNode
}) {
  const [collapsed, setCollapsed] = useState(false)
  if (count === 0) return null

  return (
    <div className="space-y-1.5">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center justify-between w-full text-left font-mono text-2xs text-text-muted uppercase tracking-wider py-1 hover:text-text-secondary"
      >
        <span className="flex items-center gap-1.5">
          <Icon size={12} className="text-accent-subtle" />
          {title} ({count})
        </span>
        {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
      </button>
      {!collapsed && <div className="space-y-1.5">{children}</div>}
    </div>
  )
}

function ConfidenceBadge({
  confidence,
  evidence,
}: {
  confidence: number
  evidence?: EvidenceType
}) {
  const pct = Math.round(confidence * 100)
  return (
    <span className="flex-none inline-flex items-center gap-1 font-mono text-2xs">
      {evidence && (
        <span
          className={`px-1 rounded text-2xs ${
            evidence === 'explicit'
              ? 'bg-success-bg/30 text-success border border-success-bg/50'
              : 'bg-accent-bg/40 text-accent-lighter border border-accent-border/50'
          }`}
          title={`Evidence: ${evidence}`}
        >
          {evidence}
        </span>
      )}
      <span className="text-text-faint">{pct}%</span>
    </span>
  )
}
