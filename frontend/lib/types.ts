/**
 * Type definitions for the Adaptive Knowledge Graph application.
 * These types align with the backend API models.
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
    [key: string]: any;
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

/**
 * Health check response.
 */
export interface HealthResponse {
  status: string;
  attribution?: string;
}

/**
 * Subject summary for listing.
 */
export interface SubjectSummary {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
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

/**
 * Subject detail response.
 */
export interface SubjectDetailResponse {
  id: string;
  name: string;
  description: string;
  attribution: string;
  opensearch_index: string;
  book_count: number;
  is_default: boolean;
}
