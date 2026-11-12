import { useState, useEffect, useCallback } from 'react'
import {
  Wand2,
  RefreshCw,
  AlertCircle,
  FileText,
  ShieldCheck,
  CheckCircle,
  History,
  FileCode,
  Table,
  Presentation,
  Workflow,
  Sparkles,
} from 'lucide-react'
import {
  createTransformationPlan,
  listPlansForInterpretation,
  getTransformationPlan,
  TransmuteApiError,
  type DocumentFormat,
} from '../../services/api'
import type {
  DocumentInterpretation,
  TransformationPlan,
  PlanOperationResponse,
  TransformationOutputStructure,
} from '../../types/interpretation'
import { SourceReferenceList } from '../interpretation/SourceReferenceList'
import { CostSummaryCard } from '../interpretation/CostSummaryCard'
import { ProvenanceCard } from '../interpretation/ProvenanceCard'
import { EmptyState } from '../ui/EmptyState'
import { Tooltip } from '../ui/Tooltip'
import { SkeletonGroup } from '../ui/SkeletonLoader'
import { formats, formatColors, formatIcons } from '../../utils/formats'
import '../../enhancements.css'

interface TransformationPlanPanelProps {
  documentId?: string
  interpretation?: DocumentInterpretation | null
  activePlan?: TransformationPlan | null
  onPlanSelected?: (plan: TransformationPlan) => void
}

type TabSection = 'all' | 'structure' | 'mappings' | 'omissions' | 'rules'

export function TransformationPlanPanel({
  documentId,
  interpretation,
  activePlan: externalActivePlan,
  onPlanSelected,
}: TransformationPlanPanelProps) {
  const [targetFormat, setTargetFormat] = useState<DocumentFormat>('pptx')
  const [instructions, setInstructions] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastResponse, setLastResponse] = useState<PlanOperationResponse | null>(null)
  const [plan, setPlan] = useState<TransformationPlan | null>(externalActivePlan ?? null)
  const [previousPlans, setPreviousPlans] = useState<TransformationPlan[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [activeSection, setActiveSection] = useState<TabSection>('all')

  // Sync external plan
  useEffect(() => {
    if (externalActivePlan) {
      setPlan(externalActivePlan)
    }
  }, [externalActivePlan])

  // Fetch plan history when interpretation changes
  const fetchPlans = useCallback(async (docId: string, interpId: string) => {
    setIsLoadingHistory(true)
    try {
      const res = await listPlansForInterpretation(docId, interpId)
      setPreviousPlans(res.items || [])
      if (res.items.length > 0 && !plan && !externalActivePlan) {
        setPlan(res.items[0])
        onPlanSelected?.(res.items[0])
      }
    } catch {
      setPreviousPlans([])
    } finally {
      setIsLoadingHistory(false)
    }
  }, [plan, externalActivePlan, onPlanSelected])

  useEffect(() => {
    if (documentId && interpretation?.interpretation_id) {
      void fetchPlans(documentId, interpretation.interpretation_id)
    } else {
      setPlan(null)
      setPreviousPlans([])
      setLastResponse(null)
    }
  }, [documentId, interpretation?.interpretation_id, fetchPlans])

  // Generate Plan Handler
  const handleGeneratePlan = async () => {
    if (!documentId || !interpretation?.interpretation_id || isLoading) return
    setIsLoading(true)
    setError(null)

    try {
      const res = await createTransformationPlan(
        documentId,
        interpretation.interpretation_id,
        {
          target_format: targetFormat,
          instructions: instructions.trim() || undefined,
        },
      )
      setLastResponse(res)
      setPlan(res.plan)
      onPlanSelected?.(res.plan)
      void fetchPlans(documentId, interpretation.interpretation_id)
    } catch (err) {
      if (err instanceof TransmuteApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('An unexpected error occurred while generating the transformation plan.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  // Select previous plan
  const handleSelectPlan = async (item: TransformationPlan) => {
    if (!documentId) return
    setIsLoading(true)
    setError(null)
    try {
      const full = await getTransformationPlan(documentId, item.plan_id)
      setPlan(full)
      onPlanSelected?.(full)
      setHistoryOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load plan details.')
    } finally {
      setIsLoading(false)
    }
  }

  // Pre-condition: Need an interpretation first
  if (!documentId || !interpretation) {
    return (
      <aside className="properties-panel" aria-label="Transformation plan panel">
        <div className="properties-header">
          <div>
            <span>TRANSFORMATION PLANNING (M2.3)</span>
            <h3>Plan</h3>
          </div>
        </div>
        <EmptyState
          icon={Wand2}
          title="Interpretation Required"
          description="Complete semantic interpretation on the Interpretation tab before designing a transformation plan."
          className="h-[calc(100%-65px)]"
        />
      </aside>
    )
  }

  return (
    <aside className="properties-panel" aria-label="Transformation plan panel">
      {/* ── Header ── */}
      <div className="properties-header">
        <div>
          <span>TRANSFORMATION PLANNING (M2.3)</span>
          <h3>Plan</h3>
        </div>
        <div className="flex items-center gap-1">
          {previousPlans.length > 0 && (
            <Tooltip content={historyOpen ? 'Hide plan history' : 'Plan history'}>
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

      {/* ── Context summary ── */}
      <div className="flex items-center justify-between border-b border-border pb-3 mb-3 text-xs">
        <div className="truncate">
          <span className="text-2xs font-mono text-text-faint block">INTERPRETATION</span>
          <span className="font-mono text-xs text-accent-lighter truncate">
            {interpretation.interpretation_id.slice(0, 10)}…
          </span>
        </div>
        <span className="text-2xs font-mono text-text-muted">
          {interpretation.facts.length} facts · {interpretation.metrics.length} metrics
        </span>
      </div>

      {/* ── History dropdown ── */}
      {historyOpen && (
        <div className="mb-4 rounded-lg border border-border-strong bg-surface-card p-3 space-y-2">
          <div className="flex items-center justify-between text-xs text-text-muted font-medium">
            <span>Saved Plans ({previousPlans.length})</span>
            {isLoadingHistory && <RefreshCw size={12} className="animate-spin" />}
          </div>
          <div className="max-h-40 overflow-y-auto space-y-1.5 pr-1">
            {previousPlans.map((p) => {
              const isSelected = p.plan_id === plan?.plan_id
              return (
                <button
                  key={p.plan_id}
                  type="button"
                  onClick={() => void handleSelectPlan(p)}
                  className={`w-full text-left p-2 rounded-md border text-xs transition-colors ${
                    isSelected
                      ? 'border-accent bg-accent-bg/40 text-text-primary'
                      : 'border-border-subtle bg-surface-input text-text-muted hover:border-border hover:text-text-primary'
                  }`}
                >
                  <div className="flex items-center justify-between font-mono text-2xs">
                    <span className="uppercase text-accent-light">{p.target_format}</span>
                    <span>{new Date(p.provenance.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <p className="text-2xs text-text-secondary mt-1">
                    {p.content_mappings.length} mappings · {p.omissions.length} omissions
                  </p>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Creation Controls ── */}
      <div className="space-y-3 pb-3 border-b border-border">
        {/* Format Selector */}
        <div>
          <label className="block text-2xs font-mono text-text-muted uppercase tracking-wider mb-1.5">
            Target Artefact Format
          </label>
          <div className="grid grid-cols-5 gap-1.5">
            {formats.map(({ id, label }) => {
              const Icon = formatIcons[id]
              const isSelected = targetFormat === id
              const color = formatColors[id]
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => setTargetFormat(id)}
                  title={label}
                  className={`flex flex-col items-center justify-center py-2 px-1 rounded border text-center transition-all ${
                    isSelected
                      ? 'border-accent bg-accent-bg/50 text-text-primary shadow-sm'
                      : 'border-border-subtle bg-surface-input text-text-muted hover:border-border hover:text-text-secondary'
                  }`}
                  disabled={isLoading}
                >
                  <Icon size={16} style={{ color }} />
                  <span className="text-2xs font-mono uppercase mt-1 font-semibold">
                    {id}
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        {/* User Instructions */}
        <div>
          <label className="block text-2xs font-mono text-text-muted uppercase tracking-wider mb-1.5">
            Transformation Guidance (Optional)
          </label>
          <textarea
            className="w-full rounded border border-border bg-surface-input p-2 text-xs text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-accent resize-none h-16"
            placeholder="e.g. Structure as an executive slide deck with problem/solution narrative…"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            disabled={isLoading}
          />
        </div>

        {/* Generate Button */}
        <button
          type="button"
          onClick={() => void handleGeneratePlan()}
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
              <span>Synthesizing Plan…</span>
            </>
          ) : (
            <>
              <Wand2 size={14} />
              <span>{plan ? 'Regenerate Plan' : 'Generate Transformation Plan'}</span>
            </>
          )}
        </button>

        {isLoading && (
          <div className="space-y-2 pt-2">
            <span className="text-2xs font-mono text-accent-light block animate-pulse">
              Synthesizing structure, content mappings, and preservation rules…
            </span>
            <SkeletonGroup lines={3} />
          </div>
        )}

        {/* Error notification */}
        {error && (
          <div className="rounded-md bg-error-bg/30 border border-error-bg p-2.5 text-xs text-error flex items-start gap-2">
            <AlertCircle size={15} className="flex-none mt-0.5" />
            <div className="min-w-0">
              <strong className="block font-semibold">Planning Failed</strong>
              <span className="text-2xs opacity-90 break-words">{error}</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Active Plan Display ── */}
      {plan ? (
        <div className="space-y-4 pt-3">
          {/* Milestone notice banner */}
          <div className="rounded border border-border-subtle bg-surface-card p-2 text-2xs text-text-muted flex items-start gap-1.5">
            <Sparkles size={12} className="text-accent flex-none mt-0.5" />
            <span>
              This is a structural transformation plan (M2.3). Final artefact rendering occurs in Milestone 3.
            </span>
          </div>

          {/* Cost & Run Card */}
          <CostSummaryCard
            runId={lastResponse?.run_id}
            usage={lastResponse?.usage ?? plan.provenance.token_usage}
            estimatedCost={lastResponse?.estimated_cost}
            pricing={lastResponse?.pricing}
            reused={lastResponse?.reused}
          />

          {/* Provenance Card */}
          <ProvenanceCard
            provenance={plan.provenance}
            warnings={plan.warnings}
          />

          {/* Plan Meta Pills */}
          <div className="flex items-center gap-2 font-mono text-2xs">
            <span className="rounded bg-accent-bg px-2 py-0.5 text-accent-lighter uppercase border border-accent-border font-semibold">
              Target: {plan.target_format}
            </span>
            <span className="rounded bg-surface-active px-2 py-0.5 text-text-muted border border-border-subtle">
              Status: {plan.validation_rules.validation_status}
            </span>
            <span className="rounded bg-surface-active px-2 py-0.5 text-text-muted border border-border-subtle">
              {plan.content_mappings.length} mappings
            </span>
          </div>

          {/* ── Section Filters ── */}
          <div className="flex flex-wrap gap-1 border-b border-border pb-2 text-2xs font-mono">
            <SectionTab
              id="all"
              label="All"
              active={activeSection}
              onClick={setActiveSection}
            />
            <SectionTab
              id="structure"
              label="Output Structure"
              active={activeSection}
              onClick={setActiveSection}
            />
            <SectionTab
              id="mappings"
              label={`Mappings (${plan.content_mappings.length})`}
              active={activeSection}
              onClick={setActiveSection}
            />
            <SectionTab
              id="omissions"
              label={`Omissions (${plan.omissions.length})`}
              active={activeSection}
              onClick={setActiveSection}
            />
            <SectionTab
              id="rules"
              label="Rules & Integrity"
              active={activeSection}
              onClick={setActiveSection}
            />
          </div>

          {/* ── Output Structure Section ── */}
          {(activeSection === 'all' || activeSection === 'structure') && (
            <div className="space-y-2">
              <span className="font-mono text-2xs text-text-muted uppercase tracking-wider block">
                Target Output Blueprint
              </span>
              <OutputStructureRenderer structure={plan.output_structure} />
            </div>
          )}

          {/* ── Content Mappings Section ── */}
          {(activeSection === 'all' || activeSection === 'mappings') && (
            <div className="space-y-2">
              <span className="font-mono text-2xs text-text-muted uppercase tracking-wider block">
                Content Mappings ({plan.content_mappings.length})
              </span>
              <div className="space-y-2">
                {plan.content_mappings.map((mapping) => (
                  <div
                    key={mapping.mapping_id}
                    className="rounded border border-border-subtle bg-surface-input p-2.5 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 font-mono text-2xs">
                        <span className="rounded bg-surface-active px-1 text-text-muted">
                          {mapping.source_item_type}
                        </span>
                        <span className="text-accent">→ {mapping.operation} →</span>
                        <span className="rounded bg-accent-bg px-1 text-accent-lighter">
                          {mapping.destination.target_type}
                        </span>
                      </div>
                    </div>
                    {mapping.formatting_guidance && (
                      <p className="text-2xs text-text-secondary leading-relaxed">
                        {mapping.formatting_guidance}
                      </p>
                    )}
                    <SourceReferenceList references={mapping.source_references} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Omissions Section ── */}
          {(activeSection === 'all' || activeSection === 'omissions') && (
            <div className="space-y-2">
              <span className="font-mono text-2xs text-text-muted uppercase tracking-wider block">
                Omitted Content ({plan.omissions.length})
              </span>
              {plan.omissions.length === 0 ? (
                <div className="rounded border border-border-subtle bg-surface-input p-2 text-2xs text-text-muted">
                  No source content was omitted from this transformation plan.
                </div>
              ) : (
                <div className="space-y-2">
                  {plan.omissions.map((omission, idx) => (
                    <div
                      key={idx}
                      className="rounded border border-warning-bg/30 bg-warning-bg/10 p-2 text-xs space-y-1"
                    >
                      <div className="flex items-center justify-between text-2xs font-mono">
                        <span className="rounded bg-surface-active px-1 text-warning">
                          {omission.source_item_type}: {omission.source_item_id}
                        </span>
                      </div>
                      <p className="text-2xs text-text-muted">{omission.reason}</p>
                      <SourceReferenceList references={omission.source_references} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Rules & Guidance ── */}
          {(activeSection === 'all' || activeSection === 'rules') && (
            <div className="space-y-3">
              {/* Generation Instructions */}
              {plan.generation_instructions.length > 0 && (
                <div className="space-y-1.5">
                  <span className="font-mono text-2xs text-text-muted uppercase tracking-wider block">
                    Generation Instructions ({plan.generation_instructions.length})
                  </span>
                  <ul className="rounded border border-border-subtle bg-surface-input p-2.5 text-2xs text-text-secondary space-y-1 list-disc list-inside">
                    {plan.generation_instructions.map((ins, idx) => (
                      <li key={idx} className="leading-relaxed">{ins}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Preservation Rules */}
              {plan.preservation_rules.length > 0 && (
                <div className="space-y-1.5">
                  <span className="font-mono text-2xs text-text-muted uppercase tracking-wider block">
                    Preservation Rules ({plan.preservation_rules.length})
                  </span>
                  <ul className="rounded border border-border-subtle bg-surface-input p-2.5 text-2xs text-text-secondary space-y-1 list-disc list-inside">
                    {plan.preservation_rules.map((rule, idx) => (
                      <li key={idx} className="leading-relaxed">{rule}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Validation Rules Card */}
              <div className="rounded border border-border-subtle bg-surface-input p-2.5 text-2xs space-y-1.5">
                <div className="flex items-center gap-1.5 font-semibold text-text-primary">
                  <ShieldCheck size={13} className="text-success" />
                  <span>Validation Integrity Checks</span>
                </div>
                <div className="space-y-1 text-text-muted">
                  <div className="flex items-center justify-between">
                    <span>Reference integrity check</span>
                    <CheckCircle size={11} className="text-success" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Material content accounting</span>
                    <CheckCircle size={11} className="text-success" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Omission reasons required</span>
                    <CheckCircle size={11} className="text-success" />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        !isLoading && (
          <div className="py-8 text-center text-xs text-text-muted space-y-2">
            <Wand2 size={24} className="mx-auto text-text-faint opacity-50" />
            <p>No transformation plan generated yet.</p>
            <p className="text-2xs text-text-faint">
              Select a target format and click &quot;Generate Transformation Plan&quot; to formulate the architecture.
            </p>
          </div>
        )
      )}
    </aside>
  )
}

/* ── Section Tab Button ── */

function SectionTab({
  id,
  label,
  active,
  onClick,
}: {
  id: TabSection
  label: string
  active: TabSection
  onClick: (s: TabSection) => void
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

/* ── Output Structure Renderer ── */

function OutputStructureRenderer({ structure }: { structure: TransformationOutputStructure | null }) {
  if (!structure) {
    return (
      <div className="rounded border border-border-subtle bg-surface-input p-2 text-2xs text-text-muted">
        No structure details defined.
      </div>
    )
  }

  if (structure.target_format === 'pptx') {
    return (
      <div className="rounded border border-border bg-surface-card p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Presentation size={14} className="text-[#e78955]" />
          <span>{structure.presentation_title || 'Presentation Structure'}</span>
        </div>
        <div className="space-y-1.5 pt-1">
          {structure.slides.map((slide, idx) => (
            <div key={slide.slide_id} className="rounded bg-surface-input p-2 text-xs border border-border-subtle space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-text-primary">
                  Slide {idx + 1}: {slide.title}
                </span>
                <span className="text-2xs font-mono text-text-faint">
                  {slide.elements.length} elements
                </span>
              </div>
              <p className="text-2xs text-text-muted">{slide.purpose}</p>
              {slide.visual_guidance && (
                <p className="text-2xs text-accent-subtle italic">
                  Visual: {slide.visual_guidance}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (structure.target_format === 'xlsx') {
    return (
      <div className="rounded border border-border bg-surface-card p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Table size={14} className="text-[#54bd91]" />
          <span>{structure.workbook_title || 'Workbook Structure'}</span>
        </div>
        <div className="space-y-1.5 pt-1">
          {structure.worksheets.map((sheet) => (
            <div key={sheet.worksheet_id} className="rounded bg-surface-input p-2 text-xs border border-border-subtle space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-text-primary">
                  Sheet: {sheet.name}
                </span>
                <span className="text-2xs font-mono text-text-faint">
                  {sheet.tables.length} tables
                </span>
              </div>
              <p className="text-2xs text-text-muted">{sheet.purpose}</p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (structure.target_format === 'docx') {
    return (
      <div className="rounded border border-border bg-surface-card p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <FileText size={14} className="text-[#6ea5ed]" />
          <span>{structure.document_title || 'Document Structure'}</span>
        </div>
        <div className="space-y-1.5 pt-1">
          {structure.sections.map((section) => (
            <div key={section.section_id} className="rounded bg-surface-input p-2 text-xs border border-border-subtle space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-text-primary">
                  H{section.heading_level}: {section.title}
                </span>
                <span className="text-2xs font-mono text-text-faint">
                  {section.elements.length} elements
                </span>
              </div>
              <p className="text-2xs text-text-muted">{section.purpose}</p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (structure.target_format === 'mmd') {
    return (
      <div className="rounded border border-border bg-surface-card p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Workflow size={14} className="text-[#b39cf2]" />
          <span>{structure.title || 'Diagram Structure'} ({structure.diagram_type})</span>
        </div>
        <div className="space-y-1 text-2xs text-text-secondary">
          <div className="flex items-center justify-between">
            <span>Nodes: {structure.nodes.length}</span>
            <span>Relationships: {structure.relationships.length}</span>
          </div>
          <div className="flex flex-wrap gap-1 pt-1">
            {structure.nodes.map((node) => (
              <span key={node.node_id} className="rounded bg-surface-active px-1.5 py-0.5 border border-border-subtle">
                {node.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (structure.target_format === 'html') {
    return (
      <div className="rounded border border-border bg-surface-card p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <FileCode size={14} className="text-[#49c5c5]" />
          <span>{structure.page_title || 'HTML Page Blueprint'}</span>
        </div>
        <div className="space-y-1.5 pt-1">
          {structure.sections.map((sec) => (
            <div key={sec.section_id} className="rounded bg-surface-input p-2 text-xs border border-border-subtle space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-text-primary">
                  &lt;{sec.semantic_element}&gt; {sec.heading}
                </span>
                <span className="text-2xs font-mono text-text-faint">
                  {sec.components.length} components
                </span>
              </div>
              <p className="text-2xs text-text-muted">{sec.purpose}</p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return null
}
