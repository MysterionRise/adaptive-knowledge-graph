/**
 * Type definitions for the Adaptive Knowledge Graph application.
 * These types mirror the backend API payloads.
 */

/**
 * Graph statistics response from the backend.
 */
export interface GraphStats {
  concept_count: number;
  module_count: number;
  relationship_count: number;
}

/**
 * Request payload for asking a question.
 */
export interface QuestionRequest {
  question: string;
  use_kg_expansion?: boolean;
  top_k?: number;
}

/**
 * Source metadata from retrieved chunks.
 */
export interface Source {
  text: string;
  module_title?: string;
  section?: string;
  score?: number;
  metadata?: {
    chapter?: string;
    section?: string;
    [key: string]: unknown;
  };
}

/**
 * Response from the Q&A endpoint.
 */
export interface QuestionResponse {
  question: string;
  answer: string;
  sources: Source[];
  expanded_concepts?: string[] | null;
  retrieved_count: number;
  model: string;
  attribution: string;
}

/**
 * First event of the `/ask/stream` server-sent-event response.
 */
export interface StreamMetadata {
  type: 'metadata';
  sources?: Source[];
  expanded_concepts?: string[] | null;
  retrieved_count?: number;
  window_expanded_count?: number;
  model?: string;
  attribution?: string;
}

/**
 * Concept node data for graph visualization.
 */
export interface ConceptNode {
  data: {
    id: string;
    label: string;
    importance: number;
    chapter?: string;
  };
}

/**
 * Relationship edge data for graph visualization.
 */
export interface ConceptEdge {
  data: {
    id: string;
    source: string;
    target: string;
    type: string;
    label: string;
  };
}

/**
 * Graph data response for visualization.
 */
export interface GraphData {
  nodes: ConceptNode[];
  edges: ConceptEdge[];
}

/**
 * Top concept data.
 */
export interface TopConcept {
  name: string;
  score: number;
  is_key_term?: boolean;
  frequency?: number;
}

export type DemoReadinessStatus = 'ok' | 'degraded' | 'error' | 'missing';

export interface DemoServiceStatus {
  status: DemoReadinessStatus;
  message?: string | null;
  latency_ms?: number | null;
}

export interface DemoSubjectStatus {
  id: string;
  name: string;
  status: DemoReadinessStatus;
  concept_count: number;
  module_count: number;
  relationship_count: number;
  message?: string | null;
}

export interface DemoEvalStatus {
  status: DemoReadinessStatus;
  environment_valid: boolean;
  generated_at?: string | null;
  cases: number;
  kg_successful_cases: number;
  plain_successful_cases: number;
  citation_hit_rate_delta?: number | null;
  mrr_delta?: number | null;
  unsupported_refusal_rate?: number | null;
  message?: string | null;
}

export interface DemoStatusResponse {
  status: 'ready' | 'degraded' | 'not_ready';
  positioning: string;
  services: Record<string, DemoServiceStatus>;
  subjects: DemoSubjectStatus[];
  latest_eval: DemoEvalStatus;
  script_readiness: Record<string, boolean>;
  next_actions: string[];
}

/**
 * Subject summary for listing.
 */
export interface SubjectSummary {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
  /**
   * Whether the subject's knowledge graph has data. Older backends omit the field, so a
   * missing value means "available".
   */
  available?: boolean;
}

/**
 * Subject list response.
 */
export interface SubjectListResponse {
  subjects: SubjectSummary[];
  default_subject: string;
}

/**
 * Subject theme for frontend styling.
 */
export interface SubjectTheme {
  subject_id: string;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  chapter_colors: Record<string, string>;
}

// =============================================================================
// Learning paths
// =============================================================================

/**
 * A prerequisite of the target concept. `depth` is the number of PREREQ steps between the
 * prerequisite and the target (1 = direct prerequisite).
 */
export interface LearningPathConcept {
  id: string;
  name: string;
  importance: number;
  chapter?: string | null;
  depth: number;
}

/**
 * Response of `GET /learning-path/{concept}`. The target concept is not part of
 * `prerequisites`; `total_concepts` counts it.
 */
export interface LearningPathResponse {
  target_concept: string;
  prerequisites: LearningPathConcept[];
  total_concepts: number;
}

// =============================================================================
// Quizzes
// =============================================================================

export type Difficulty = 'easy' | 'medium' | 'hard';

export interface QuizOption {
  id: string;
  text: string;
}

export interface QuizQuestion {
  id: string;
  text: string;
  options: QuizOption[];
  correct_option_id: string;
  explanation: string;
  source_chunk_id?: string | null;
  related_concept?: string | null;
  difficulty?: Difficulty | null;
  /** 0.0-1.0 heuristic difficulty. */
  difficulty_score?: number | null;
}

export interface Quiz {
  id: string;
  title: string;
  questions: QuizQuestion[];
  average_difficulty?: number | null;
}

/** Quiz generated for the learner's current mastery of the topic. */
export interface AdaptiveQuiz extends Quiz {
  student_mastery: number;
  target_difficulty: Difficulty;
  adapted: boolean;
}

// =============================================================================
// Post-quiz recommendations
// =============================================================================

export interface QuizQuestionResult {
  question_id: string;
  related_concept: string;
  correct: boolean;
}

export interface RecommendationRequest {
  topic: string;
  question_results: QuizQuestionResult[];
  student_id?: string;
  subject?: string | null;
}

export interface ReadingMaterial {
  text: string;
  section?: string | null;
  module_title?: string | null;
  relevance_score?: number | null;
}

export interface ConceptRecommendation {
  name: string;
  importance?: number | null;
  mastery?: number | null;
  relationship_type?: string | null;
}

export interface RemediationBlock {
  concept: string;
  prerequisites: ConceptRecommendation[];
  reading_materials: ReadingMaterial[];
}

export interface AdvancementBlock {
  concept: string;
  advanced_topics: ConceptRecommendation[];
  deep_dive_content?: string | null;
}

export interface RecommendationResponse {
  /** "remediation", "advancement" or "mixed". */
  path_type: string;
  score_pct: number;
  remediation: RemediationBlock[];
  advancement: AdvancementBlock[];
  summary: string;
}

// =============================================================================
// Student profile
// =============================================================================

export interface MasteryUpdateResponse {
  concept: string;
  previous_mastery: number;
  new_mastery: number;
  target_difficulty: Difficulty;
  total_attempts: number;
  bkt_p_known?: number | null;
}

export interface StudentProfileResponse {
  student_id: string;
  overall_ability: number;
  mastery_levels: Record<string, number>;
  updated_at: string;
}
