// Response/request shapes mirrored from backend/finalsay/schemas.py.

export type Role = 'student' | 'reviewer' | 'admin' | 'issuer'

export const RELATIONSHIP_LABELS = [
  'consistent',
  'contradictory',
  'superseded',
  'corrected',
  'extended',
  'cancelled',
  'unresolved',
] as const

export type RelationshipLabel = (typeof RELATIONSHIP_LABELS)[number]

export interface UserOut {
  id: number
  email: string
  role: Role
  display_name: string | null
  institution_id: number | null
}

export interface InstitutionChoice {
  id: number
  name: string
  current_notice_count: number
}

export interface Token {
  access_token: string
  token_type: string
}

export interface NoticeFieldOut {
  field_name: string
  value: string | null
  confidence: number | null
}

export interface NoticeDocumentExtractionOut {
  source_url: string
  extracted_text: string
  extracted_text_sha256: string
  extraction_quality: string
  extraction_method: string
  extracted_at: string
}

export interface NoticeSummary {
  id: number
  kind: string
  institution_id: number | null
  title: string | null
  published_date: string | null
  published_on: string | null
  issuer: string | null
  notice_date: string | null
  deadline: string | null
  audience: string | null
  extraction_quality: string
  source_url: string | null
  source_key: string | null
  version_no: number
  is_current: boolean
  previous_version_id: number | null
  sha256: string | null
  retrieved_at: string | null
}

export interface StudentNoticeFeed {
  institution_id: number
  institution_name: string
  items: StudentNoticeItem[]
  total: number
  page: number
  page_size: number
  page_count: number
  months: { month: string; count: number }[]
  undated_count: number
}

export interface StudentNoticeItem extends NoticeSummary {
  preview: string | null
}

export interface NoticeDetail extends NoticeSummary {
  action: string | null
  redacted_text: string | null
  fields: NoticeFieldOut[]
  supplemental_extractions: NoticeDocumentExtractionOut[]
}

export interface CandidateOut {
  notice: NoticeSummary
  score: number
  semantic_similarity?: number | null
}

export interface ComparisonResponse {
  submission_id: number
  candidate_id: number | null
  edge_id: number
  label: RelationshipLabel
  confidence: number
  rationale: string
  model: string
  status: string
  gated: boolean
  review_case_id: number | null
  candidate_score?: number | null
  candidate_institution?: string | null
  candidate_issuer?: string | null
  candidate_notice_date?: string | null
  candidate_deadline?: string | null
  candidate_source_url?: string | null
  candidate_text?: string | null
  candidate_supplemental_extractions?: NoticeDocumentExtractionOut[]
  evidence?: string[]
}

export interface VerifyResponse {
  ok: boolean
  tamper: boolean
  integrity_status:
    | 'VERIFIED'
    | 'TAMPERED'
    | 'NOT_ANCHORED'
    | 'PENDING'
    | 'VERIFICATION_UNAVAILABLE'
    | 'LOCAL_VERIFIED'
  details: Record<string, unknown>
}

export interface MerkleBuildResponse {
  root_id: number
  day: string
  root_hash: string
  anchor_kind: string
  anchor_ref: string | null
  anchor_chain_id: number | null
  anchor_block_number: number | null
  anchor_network: string | null
  anchor_contract_address: string | null
  anchor_issuer_address: string | null
  anchor_issuer_id: string | null
  anchor_batch_id: string | null
  anchor_timestamp: string | null
  anchor_submitted_at: string | null
  anchor_status: string
  anchor_error: string | null
  leaf_count: number
}

export interface InstitutionOut {
  id: number
  name: string
  slug: string
  source_url: string | null
  scrape_type: 'fixture' | 'thapar_html' | 'nitj_api' | 'iitb_html' | 'vtu_examination' | 'du_examination' | 'mumbai_circulars'
  scrape_enabled: boolean
  active: boolean
  backfill_complete: boolean
  backfill_cursor: string | null
  last_successful_fetch: string | null
  last_successful_created: number
  last_successful_modified: number
  last_successful_unchanged: number
  current_notice_count: number
  extracted_count: number
  listing_only_count: number
  unextractable_count: number
  unknown_extraction_count: number
}

export interface IssuerMembershipOut {
  user_id: number
  issuer_email: string
  display_name: string | null
  institution_id: number
  institution_name: string
  institution_slug: string
  active: boolean
}

export interface BenchmarkCandidateOut {
  submission_id: number
  official_id: number
  institution_name: string
  submission_title: string | null
  official_title: string | null
  submission_created_at: string
  official_published_date: string | null
}

export interface FetchResponse {
  created: number
  modified: number
  skipped: number
  errors: number
  institutions: Array<Record<string, unknown>>
}

export interface ScrapeRunOut {
  id: number
  institution_id: number
  status: string
  found: number
  created: number
  modified: number
  unchanged: number
  error: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ReviewQueueItem {
  case_id: number
  edge_id: number
  status: string
  label: RelationshipLabel
  confidence: number
  rationale: string | null
  submission: NoticeSummary
  candidate: NoticeSummary | null
}

export interface ResolveResponse {
  case_id: number
  edge_id: number
  label: RelationshipLabel
  edge_status: string
  case_status: string
}

export interface BenchmarkPairOut {
  id: number
  submission_id: number
  official_id: number
  submission_text: string | null
  official_text: string | null
  pair_kind: 'student_comparison' | 'source_revision'
  institution_name: string | null
  left_title: string | null
  right_title: string | null
  your_label: RelationshipLabel | null
}

export interface BenchmarkStatusOut {
  completed: boolean
  pair_count: number
  annotated_count: number
}

export interface KappaResponse {
  kappa: number | null
  ready: boolean
  annotators: string[]
  pairs_compared: number
  per_label: Record<string, unknown>
  is_seed_demo: boolean
}
