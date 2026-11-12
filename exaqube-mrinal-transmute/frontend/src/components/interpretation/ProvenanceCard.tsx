import { ShieldAlert, Bot, Sparkles } from 'lucide-react'
import type { InterpretationProvenance, TransformationProvenance } from '../../types/interpretation'

interface ProvenanceCardProps {
  provenance: InterpretationProvenance | TransformationProvenance
  warnings?: string[]
}

export function ProvenanceCard({ provenance, warnings = [] }: ProvenanceCardProps) {
  const isMock = provenance.is_mock

  return (
    <div className="space-y-2">
      {/* Mock indicator banner */}
      {isMock ? (
        <div className="flex items-center gap-2 rounded-md bg-warning-bg/25 border border-warning-bg/50 px-2.5 py-2 text-xs text-warning-light">
          <Bot size={14} className="flex-none text-warning" />
          <div className="min-w-0">
            <strong className="font-semibold block">Mock Mode Generation</strong>
            <span className="text-2xs opacity-90 block">
              Generated locally using mock templates (MOCK_LLM=true). No external LLM API calls or provider costs incurred.
            </span>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-md bg-accent-bg/30 border border-accent-border/50 px-2.5 py-1.5 text-xs text-accent-lighter">
          <Sparkles size={14} className="flex-none text-accent" />
          <span className="text-2xs">
            Live LLM: {provenance.provider} / {provenance.model} (v{provenance.prompt_version})
          </span>
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="rounded-md bg-warning-bg/20 border border-warning-bg/40 p-2.5 text-xs text-warning-light space-y-1">
          <div className="flex items-center gap-1.5 font-semibold text-warning">
            <ShieldAlert size={13} />
            <span>Warnings ({warnings.length})</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-2xs opacity-90">
            {warnings.map((w, idx) => (
              <li key={idx} className="leading-relaxed">{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Details metadata */}
      <div className="flex items-center justify-between text-2xs font-mono text-text-faint px-1">
        <span>Model: {provenance.model || 'mock'}</span>
        <span>{new Date(provenance.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    </div>
  )
}
