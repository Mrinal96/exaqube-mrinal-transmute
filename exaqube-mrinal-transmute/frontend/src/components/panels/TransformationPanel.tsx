import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Download, FileOutput, Loader2, WandSparkles } from 'lucide-react'
import type { DocumentMetadata, DocumentFormat } from '../../services/api'
import { createArtifactTransformation, downloadArtifact, TransmuteApiError } from '../../services/api'
import type { DocumentInterpretation, UsageSummary } from '../../types/interpretation'
import type { ArtifactOperationResponse } from '../../types/artifact'
import type { DocumentFlowNode } from '../../types/workflow'
import { formatCost } from '../interpretation/CostSummaryCard'

interface TransformationPanelProps {
  document?: DocumentMetadata
  interpretation?: DocumentInterpretation | null
  targetNode?: DocumentFlowNode
  onTransformationStart?: (targetNodeId?: string) => void
  onTransformationSuccess?: (response: ArtifactOperationResponse, targetNodeId?: string) => void
  onTransformationError?: (error: string, targetNodeId?: string) => void
  onClearArtifact?: (targetNodeId?: string) => void
  onInstructionsChange?: (instructions: string, targetNodeId?: string) => void
  onTargetFormatChange?: (format: DocumentFormat, targetNodeId?: string) => void
}

type OperationStatus = 'idle' | 'transforming' | 'done' | 'failed'

const formatLabels: Record<DocumentFormat, string> = {
  pptx: 'PowerPoint (.pptx)',
  xlsx: 'Spreadsheet (.xlsx)',
  docx: 'Report (.docx)',
  mmd: 'Mermaid diagram (.mmd)',
  html: 'HTML page (.html)',
}

export function TransformationPanel({
  document: sourceDocument,
  interpretation,
  targetNode,
  onTransformationStart,
  onTransformationSuccess,
  onTransformationError,
  onClearArtifact,
  onInstructionsChange,
  onTargetFormatChange,
}: TransformationPanelProps) {
  const [targetFormat, setTargetFormat] = useState<DocumentFormat>(
    (targetNode?.data.format as DocumentFormat) || 'html',
  )
  const [instructions, setInstructions] = useState(
    targetNode?.data.instruction || '',
  )
  const [status, setStatus] = useState<OperationStatus>(
    targetNode?.data.status === 'complete'
      ? 'done'
      : targetNode?.data.status === 'error'
        ? 'failed'
        : 'idle',
  )
  const [error, setError] = useState<string | undefined>(
    targetNode?.data.errorMessage,
  )
  const [downloadError, setDownloadError] = useState<string>()
  const [downloading, setDownloading] = useState(false)
  const [result, setResult] = useState<ArtifactOperationResponse | undefined>(
    targetNode?.data.artifactId && targetNode?.data.downloadUrl
      ? {
          output: {
            output_id: targetNode.data.artifactId,
            document_id: sourceDocument?.id || '',
            interpretation_id: targetNode.data.interpretationId || '',
            target_format: targetNode.data.format as DocumentFormat,
            filename: targetNode.data.filename,
            provider: 'standard',
            model: 'standard',
            prompt_version: 'v1',
            created_at: '',
            is_mock: false,
            warnings: [],
          },
          download_url: targetNode.data.downloadUrl,
          run_id: targetNode.data.runId || '',
          usage: (targetNode.data.usage as UsageSummary) || null,
          estimated_cost: targetNode.data.estimatedCost || null,
          pricing: {
            currency: 'USD',
            pricing_version: null,
            input_cost_per_million_tokens: null,
            output_cost_per_million_tokens: null,
          },
        }
      : undefined,
  )
  const operationSequence = useRef(0)
  const prevTargetNodeId = useRef<string | undefined>(targetNode?.id)

  const validInterpretation = sourceDocument && interpretation?.document_id === sourceDocument.id
    ? interpretation
    : null

  // Sync state when targetNode selection changes
  useEffect(() => {
    if (targetNode?.id !== prevTargetNodeId.current) {
      prevTargetNodeId.current = targetNode?.id
      if (targetNode) {
        setTargetFormat(targetNode.data.format as DocumentFormat)
        setInstructions(targetNode.data.instruction || '')
        if (targetNode.data.status === 'complete' && targetNode.data.downloadUrl && targetNode.data.artifactId) {
          setStatus('done')
          setError(undefined)
          setResult({
          output: {
            output_id: targetNode.data.artifactId,
            document_id: sourceDocument?.id || '',
            interpretation_id: targetNode.data.interpretationId || '',
            target_format: targetNode.data.format as DocumentFormat,
            filename: targetNode.data.filename,
            provider: 'standard',
            model: 'standard',
            prompt_version: 'v1',
            created_at: '',
            is_mock: false,
            warnings: [],
          },
            download_url: targetNode.data.downloadUrl,
            run_id: targetNode.data.runId || '',
            usage: (targetNode.data.usage as UsageSummary) || null,
            estimated_cost: targetNode.data.estimatedCost || null,
            pricing: {
              currency: 'USD',
              pricing_version: null,
              input_cost_per_million_tokens: null,
              output_cost_per_million_tokens: null,
            },
          })
        } else if (targetNode.data.status === 'error') {
          setStatus('failed')
          setError(targetNode.data.errorMessage || 'Transformation failed.')
          setResult(undefined)
        } else {
          setStatus('idle')
          setError(undefined)
          setResult(undefined)
        }
      }
    }
  }, [targetNode?.id, targetNode?.data.status, targetNode?.data.format, targetNode?.data.instruction, sourceDocument?.id])

  // Clear stale results when source document or interpretation changes
  useEffect(() => {
    operationSequence.current += 1
    setStatus('idle')
    setResult(undefined)
    setError(undefined)
    setDownloadError(undefined)
    onClearArtifact?.(targetNode?.id)
  }, [sourceDocument?.id, validInterpretation?.interpretation_id])

  const handleInstructionsChange = (newVal: string) => {
    setInstructions(newVal)
    setStatus('idle')
    setResult(undefined)
    setError(undefined)
    setDownloadError(undefined)
    onInstructionsChange?.(newVal, targetNode?.id)
    onClearArtifact?.(targetNode?.id)
  }

  const handleTargetFormatChange = (newFormat: DocumentFormat) => {
    setTargetFormat(newFormat)
    setStatus('idle')
    setResult(undefined)
    setError(undefined)
    setDownloadError(undefined)
    onTargetFormatChange?.(newFormat, targetNode?.id)
    onClearArtifact?.(targetNode?.id)
  }

  const transform = async () => {
    if (!sourceDocument || !validInterpretation || status === 'transforming') return
    const currentOperation = ++operationSequence.current
    const capturedTargetNodeId = targetNode?.id
    setStatus('transforming')
    setResult(undefined)
    setError(undefined)
    setDownloadError(undefined)
    onTransformationStart?.(capturedTargetNodeId)

    try {
      const response = await createArtifactTransformation(sourceDocument.id, {
        target_format: targetFormat,
        instructions: instructions.trim() || undefined,
        interpretation_id: validInterpretation.interpretation_id,
      })
      if (currentOperation !== operationSequence.current) return
      setResult(response)
      setStatus('done')
      onTransformationSuccess?.(response, capturedTargetNodeId)
    } catch (cause) {
      if (currentOperation !== operationSequence.current) return
      const msg = cause instanceof TransmuteApiError || cause instanceof Error
        ? cause.message
        : 'Output generation failed. Try again.'
      setError(msg)
      setStatus('failed')
      onTransformationError?.(msg, capturedTargetNodeId)
    }
  }

  const download = async () => {
    if (!result) return
    setDownloading(true)
    setDownloadError(undefined)
    try {
      await downloadArtifact(result.download_url, result.output.filename)
    } catch (cause) {
      setDownloadError(cause instanceof Error ? cause.message : 'The output could not be downloaded.')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <aside className="properties-panel" aria-label="Document transformation panel">
      <div className="properties-header">
        <div>
          <span>NATIVE OUTPUT GENERATION</span>
          <h3>Transform</h3>
        </div>
      </div>

      {!sourceDocument ? (
        <div className="m-3 rounded-lg border border-border bg-surface-card p-3 text-xs text-text-secondary" role="status">
          <div className="mb-1 flex items-center gap-2 font-semibold text-text-primary"><FileOutput size={15} /> Source document required</div>
          Upload a supported document to choose a source for transformation.
        </div>
      ) : (
        <div className="m-3 space-y-3">
          <div className="rounded-lg border border-border bg-surface-card p-3">
            <span className="block text-2xs font-mono uppercase tracking-wider text-text-faint">Source document</span>
            <strong className="mt-1 block break-words text-xs text-text-primary">{sourceDocument.filename}</strong>
            <span className="mt-1 block text-2xs text-text-muted">{formatLabels[sourceDocument.format]}</span>
          </div>

          {!validInterpretation ? (
            <div className="rounded-lg border border-border bg-surface-card p-3 text-xs text-text-secondary" role="status">
              <div className="mb-1 flex items-center gap-2 font-semibold text-text-primary"><WandSparkles size={14} /> Interpretation required</div>
              Run or select an interpretation in the Interpretation panel before generating an output.
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="transform-target" className="mb-1.5 block text-2xs font-mono uppercase tracking-wider text-text-muted">Target format</label>
                <select
                  id="transform-target"
                  value={targetFormat}
                  onChange={(event) => handleTargetFormatChange(event.target.value as DocumentFormat)}
                  disabled={status === 'transforming'}
                  className="w-full rounded border border-border bg-surface-input p-2 text-xs text-text-primary focus:border-accent focus:outline-none"
                >
                  {(Object.keys(formatLabels) as DocumentFormat[]).map((format) => (
                    <option key={format} value={format}>{formatLabels[format]}</option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="transform-instructions" className="mb-1.5 block text-2xs font-mono uppercase tracking-wider text-text-muted">Instructions <span className="text-text-faint">(optional)</span></label>
                <textarea
                  id="transform-instructions"
                  value={instructions}
                  onChange={(event) => handleInstructionsChange(event.target.value)}
                  maxLength={8000}
                  disabled={status === 'transforming'}
                  placeholder="Describe what the new artefact should communicate…"
                  className="min-h-20 w-full resize-y rounded border border-border bg-surface-input p-2 text-xs text-text-primary placeholder:text-text-disabled focus:border-accent focus:outline-none"
                />
              </div>

              <button
                type="button"
                onClick={() => void transform()}
                disabled={status === 'transforming'}
                className="flex h-9 w-full items-center justify-center gap-2 rounded-md bg-accent text-xs font-semibold text-white transition-colors hover:bg-accent-dim disabled:cursor-wait disabled:opacity-60"
              >
                {status === 'transforming' ? <><Loader2 size={14} className="animate-spin" /> Generating and validating…</> : <><WandSparkles size={14} /> Transform</>}
              </button>

              <div className="rounded-lg border border-border bg-surface-card p-3 text-xs" aria-live="polite">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="font-mono text-2xs uppercase tracking-wider text-text-muted">Operation status</span>
                  <span className={`flex items-center gap-1.5 font-medium ${status === 'failed' ? 'text-error' : status === 'done' ? 'text-success' : status === 'transforming' ? 'text-accent-light' : 'text-text-secondary'}`}>
                    {status === 'transforming' && <Loader2 size={12} className="animate-spin" />}
                    {status === 'done' && <CheckCircle2 size={12} />}
                    {status === 'failed' && <AlertCircle size={12} />}
                    {status === 'transforming' ? 'Transforming' : status === 'done' ? 'Complete' : status === 'failed' ? 'Failed' : 'Ready'}
                  </span>
                </div>
                {status === 'transforming' && <p className="text-2xs text-text-muted">The backend is generating, rendering, and validating the native file.</p>}
                {error && <p className="break-words text-2xs text-error" role="alert">{error}</p>}
                {result && (
                  <div className="space-y-2 border-t border-border-subtle pt-2">
                    <div>
                      <span className="block text-2xs text-text-faint">Generated file</span>
                      <strong className="break-all text-text-primary">{result.output.filename}</strong>
                      <span className="block text-2xs text-text-muted">{formatLabels[result.output.target_format]}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-2xs">
                      <div><span className="block text-text-faint">Estimated cost</span><strong className="text-text-secondary">{formatCost(result.estimated_cost)}</strong></div>
                      <div><span className="block text-text-faint">Tokens</span><strong className="text-text-secondary">{formatUsage(result.usage)}</strong></div>
                    </div>
                    <div><span className="block text-2xs text-text-faint">Run ID</span><code className="break-all font-mono text-2xs text-text-secondary">{result.run_id}</code></div>
                    {result.output.is_mock && <p className="rounded border border-warning/30 bg-warning/10 p-2 text-2xs text-warning">Mock output: this file contains deterministic source content and is not an AI transformation.</p>}
                    {result.output.warnings.map((warning, index) => <p key={`${index}-${warning}`} className="break-words text-2xs text-warning">{warning}</p>)}
                    <button type="button" onClick={() => void download()} disabled={downloading} className="flex h-8 w-full items-center justify-center gap-2 rounded border border-border-strong bg-surface-input text-xs font-semibold text-text-primary hover:border-accent disabled:opacity-60">
                      {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                      {downloading ? 'Preparing download…' : 'Download output'}
                    </button>
                    {downloadError && <p className="break-words text-2xs text-error" role="alert">{downloadError}</p>}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </aside>
  )
}

function formatUsage(usage: ArtifactOperationResponse['usage']): string {
  if (!usage) return 'Unavailable'
  const input = usage.input_tokens
  const output = usage.output_tokens
  if (input === null && output === null && usage.total_tokens === null) return 'Unavailable'
  const parts = [
    input === null ? undefined : `In ${input.toLocaleString()}`,
    output === null ? undefined : `Out ${output.toLocaleString()}`,
    usage.total_tokens === null ? undefined : `Total ${usage.total_tokens.toLocaleString()}`,
  ].filter((part): part is string => part !== undefined)
  return parts.join(' · ')
}
