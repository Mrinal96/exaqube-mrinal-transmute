import type { DocumentFormat } from '../services/api'
import type { ApiDecimal, CostPricing, UsageSummary } from './interpretation'

export interface ArtifactMetadata {
  output_id: string
  document_id: string
  interpretation_id: string
  target_format: DocumentFormat
  filename: string
  provider: string
  model: string
  prompt_version: string
  created_at: string
  is_mock: boolean
  warnings: string[]
}

export interface ArtifactOperationResponse {
  output: ArtifactMetadata
  download_url: string
  run_id: string
  usage: UsageSummary | null
  estimated_cost: ApiDecimal | null
  pricing: CostPricing
}

export interface CreateArtifactRequest {
  target_format: DocumentFormat
  instructions?: string
  interpretation_id?: string
}
