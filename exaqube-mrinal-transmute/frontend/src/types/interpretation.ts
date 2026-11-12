import type { DocumentFormat, IRBlock } from '../services/api'

export type EvidenceType = 'explicit' | 'inferred'
export type SourceLocation = IRBlock['source']

export interface SourceReference {
  block_id: string | null
  section_id: string | null
  source_location: SourceLocation
}

export interface InterpretationFact {
  statement: string
  source_references: SourceReference[]
  confidence: number
  evidence_type: EvidenceType
}

export interface InterpretationMetric {
  name: string
  value: number | string
  unit: string | null
  currency: string | null
  reporting_period: string | null
  description: string
  source_references: SourceReference[]
  confidence: number
  evidence_type: EvidenceType
}

export interface InterpretationEntity {
  entity_id: string
  name: string
  entity_type: string
  attributes: Record<string, unknown>
  source_references: SourceReference[]
  confidence: number
}

export interface InterpretationClaim {
  statement: string
  claim_type: string
  source_references: SourceReference[]
  confidence: number
  evidence_type: EvidenceType
}

export interface InterpretationRelationship {
  source_entity_id: string
  target_entity_id: string
  relationship_type: string
  source_references: SourceReference[]
  confidence: number
}

export interface InterpretationInsight {
  observation: string
  reasoning: string
  supporting_source_references: SourceReference[]
  confidence: number
  evidence_type: EvidenceType
}

export interface LLMTokenUsage {
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
}

export interface InterpretationProvenanceRecord {
  extractor: string
  extracted_at: string
  source_format: DocumentFormat
  details: Record<string, unknown>
}

export interface InterpretationProvenance {
  provider: string
  model: string
  prompt_version: string
  created_at: string
  is_mock: boolean
  source_provenance: InterpretationProvenanceRecord[]
  token_usage: LLMTokenUsage | null
}

export interface InterpretationMetadata {
  source_format: DocumentFormat
  source_ir_fingerprint: string
  instruction_fingerprint: string
  input_fingerprint: string
}

export interface DocumentInterpretation {
  interpretation_id: string
  document_id: string
  schema_version: string
  summary: string
  facts: InterpretationFact[]
  metrics: InterpretationMetric[]
  entities: InterpretationEntity[]
  claims: InterpretationClaim[]
  relationships: InterpretationRelationship[]
  insights: InterpretationInsight[]
  warnings: string[]
  provenance: InterpretationProvenance
  metadata: InterpretationMetadata
}

export interface CreateInterpretationRequest {
  instructions?: string
  idempotency_key?: string
}

export interface UsageSummary {
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
}

/** Pydantic Decimal values may be encoded as JSON numbers or decimal strings. */
export type ApiDecimal = number | string

export interface CostPricing {
  currency: 'USD'
  pricing_version: string | null
  input_cost_per_million_tokens: ApiDecimal | null
  output_cost_per_million_tokens: ApiDecimal | null
}

export interface InterpretationOperationResponse {
  interpretation: DocumentInterpretation
  reused: boolean
  run_id: string
  usage: UsageSummary | null
  estimated_cost: ApiDecimal | null
  pricing: CostPricing
}

export interface InterpretationListResponse {
  items: DocumentInterpretation[]
  count: number
}

export interface PlanSourceItem {
  source_item_type: 'fact' | 'metric' | 'entity' | 'claim' | 'relationship' | 'insight' | 'ir_block'
  source_item_id: string
}

export interface PlanDestination {
  target_type:
    | 'slide' | 'slide_element' | 'worksheet' | 'table' | 'column'
    | 'doc_section' | 'doc_element' | 'diagram_node' | 'diagram_edge'
    | 'html_section' | 'html_component'
  target_id: string
}

export interface ContentMapping {
  mapping_id: string
  source_item_type: PlanSourceItem['source_item_type']
  source_item_id: string
  destination: PlanDestination
  operation: 'preserve' | 'summarize' | 'reframe' | 'aggregate' | 'visualize' | 'reorganize'
  formatting_guidance: string
  source_references: SourceReference[]
}

export interface OmittedContent {
  source_item_type: PlanSourceItem['source_item_type']
  source_item_id: string
  reason: string
  source_references: SourceReference[]
}

export interface PPTXElementPlan {
  element_id: string
  element_type: 'title' | 'paragraph' | 'bullets' | 'table' | 'chart' | 'callout' | 'image_placeholder'
  purpose: string
  mapping_ids: string[]
}

export interface PPTXSlidePlan {
  slide_id: string
  title: string
  purpose: string
  visual_guidance: string
  mapping_ids: string[]
  elements: PPTXElementPlan[]
}

export interface PPTXOutputStructure {
  target_format: 'pptx'
  presentation_title: string
  slides: PPTXSlidePlan[]
}

export interface XLSXColumnPlan {
  column_id: string
  name: string
  data_type: string
  purpose: string
  mapping_ids: string[]
}

export interface XLSXTablePlan {
  table_id: string
  name: string
  purpose: string
  mapping_ids: string[]
  columns: XLSXColumnPlan[]
}

export interface XLSXWorksheetPlan {
  worksheet_id: string
  name: string
  purpose: string
  mapping_ids: string[]
  tables: XLSXTablePlan[]
}

export interface XLSXOutputStructure {
  target_format: 'xlsx'
  workbook_title: string
  worksheets: XLSXWorksheetPlan[]
}

export interface DOCXElementPlan {
  element_id: string
  element_type: 'heading' | 'paragraph' | 'table' | 'list' | 'callout'
  purpose: string
}

export interface DOCXSectionPlan {
  section_id: string
  title: string
  heading_level: number
  purpose: string
  elements: DOCXElementPlan[]
}

export interface DOCXOutputStructure {
  target_format: 'docx'
  document_title: string
  sections: DOCXSectionPlan[]
}

export interface MermaidNodePlan {
  node_id: string
  label: string
  role: string
  mapping_ids: string[]
}

export interface MermaidEdgePlan {
  edge_id: string
  source_node_id: string
  target_node_id: string
  label: string
  mapping_ids: string[]
}

export interface MMDOutputStructure {
  target_format: 'mmd'
  diagram_type: string
  title: string
  nodes: MermaidNodePlan[]
  relationships: MermaidEdgePlan[]
}

export interface HTMLComponentPlan {
  component_id: string
  component_type: 'heading' | 'paragraph' | 'table' | 'list' | 'chart' | 'metric_card' | 'callout' | 'accordion' | 'link'
  purpose: string
  mapping_ids: string[]
}

export interface HTMLSectionPlan {
  section_id: string
  heading: string
  semantic_element: 'main' | 'section' | 'article' | 'aside' | 'nav' | 'footer'
  purpose: string
  mapping_ids: string[]
  components: HTMLComponentPlan[]
}

export interface HTMLOutputStructure {
  target_format: 'html'
  page_title: string
  include_navigation: boolean
  sections: HTMLSectionPlan[]
}

export type TransformationOutputStructure =
  | PPTXOutputStructure
  | XLSXOutputStructure
  | DOCXOutputStructure
  | MMDOutputStructure
  | HTMLOutputStructure

export interface PlanValidationRules {
  validation_status: 'ready' | 'not_evaluated'
  target_format: DocumentFormat
  required_content_items: PlanSourceItem[]
  require_source_reference_integrity: boolean
  require_material_content_accounting: boolean
  require_omission_reasons: boolean
  require_target_structure_validation: boolean
}

export interface TransformationProvenance {
  provider: string
  model: string
  prompt_version: string
  created_at: string
  is_mock: boolean
  token_usage: LLMTokenUsage | null
}

export interface TransformationMetadata {
  source_ir_fingerprint: string
  interpretation_fingerprint: string
  instruction_fingerprint: string
  input_fingerprint: string
}

export interface TransformationPlan {
  plan_id: string
  document_id: string
  interpretation_id: string
  schema_version: string
  target_format: DocumentFormat
  user_instructions: string | null
  output_structure: TransformationOutputStructure | null
  content_mappings: ContentMapping[]
  generation_instructions: string[]
  preservation_rules: string[]
  omissions: OmittedContent[]
  validation_rules: PlanValidationRules
  provenance: TransformationProvenance
  metadata: TransformationMetadata
  warnings: string[]
}

export interface CreateTransformationPlanRequest {
  target_format: DocumentFormat
  instructions?: string
  idempotency_key?: string
}

export interface PlanOperationResponse {
  plan: TransformationPlan
  reused: boolean
  run_id: string
  usage: UsageSummary | null
  estimated_cost: ApiDecimal | null
  pricing: CostPricing
}

export interface PlanListResponse {
  items: TransformationPlan[]
  count: number
}
