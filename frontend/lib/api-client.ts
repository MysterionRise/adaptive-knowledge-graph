/**
 * API Client for the Adaptive Knowledge Graph backend.
 * Handles all HTTP requests to the FastAPI backend.
 */

import axios, { AxiosInstance } from 'axios';
import type {
  GraphStats,
  QuestionRequest,
  QuestionResponse,
  GraphData,
  TopConcept,
  HealthResponse,
  SubjectListResponse,
  SubjectTheme,
  SubjectDetailResponse,
} from './types';

/**
 * API Client class for interacting with the backend.
 */
class ApiClient {
  private client: AxiosInstance;
  private baseURL: string;
  private apiPrefix: string = '/api/v1';

  constructor(baseURL?: string) {
    this.baseURL = baseURL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    this.client = axios.create({
      baseURL: this.baseURL,
      timeout: 30000, // 30 second timeout
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response) {
          // Server responded with error status
          console.error('API Error:', error.response.status, error.response.data);
        } else if (error.request) {
          // Request made but no response
          console.error('Network Error: No response from server');
        } else {
          // Error in request setup
          console.error('Request Error:', error.message);
        }
        return Promise.reject(error);
      }
    );
  }

  /**
   * Get graph statistics (concept count, module count, relationship count).
   * Falls back to mock data if the API is unavailable.
   *
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   */
  async getGraphStats(subject?: string): Promise<GraphStats> {
    try {
      const response = await this.client.get<GraphStats>(`${this.apiPrefix}/graph/stats`, {
        params: subject ? { subject } : undefined,
      });
      return response.data;
    } catch (error) {
      console.warn('Failed to fetch graph stats, using mock data:', error);
      // Return mock data as fallback
      return {
        concept_count: 450,
        module_count: 47,
        relationship_count: 892,
      };
    }
  }

  /**
   * Ask a question using KG-aware RAG.
   *
   * @param request - Question request with question text and optional parameters
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   * @returns Question response with answer, sources, and metadata
   */
  async askQuestion(request: QuestionRequest, subject?: string): Promise<QuestionResponse> {
    const payload = {
      question: request.question,
      use_kg_expansion: request.use_kg_expansion ?? true,
      top_k: request.top_k ?? 5,
      subject: subject,
    };

    const response = await this.client.post<QuestionResponse>(
      `${this.apiPrefix}/ask`,
      payload
    );
    return response.data;
  }

  /**
   * Get graph data for visualization (nodes and edges).
   *
   * @param limit - Maximum number of concepts to return (default: 100)
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   * @returns Graph data with nodes and edges
   */
  async getGraphData(limit: number = 100, subject?: string): Promise<GraphData> {
    try {
      const response = await this.client.get<GraphData>(`${this.apiPrefix}/graph/data`, {
        params: { limit, ...(subject && { subject }) },
      });
      return response.data;
    } catch (error) {
      console.warn('Failed to fetch graph data:', error);
      // Return empty graph as fallback
      return {
        nodes: [],
        edges: [],
      };
    }
  }

  /**
   * Get top concepts by importance score.
   *
   * @param limit - Maximum number of concepts to return (default: 20)
   * @returns Array of top concepts
   */
  async getTopConcepts(limit: number = 20): Promise<TopConcept[]> {
    try {
      const response = await this.client.get<TopConcept[]>(`${this.apiPrefix}/concepts/top`, {
        params: { limit },
      });
      return response.data;
    } catch (error) {
      console.warn('Failed to fetch top concepts:', error);
      return [];
    }
  }

  /**
   * Health check endpoint to verify backend is available.
   *
   * @returns true if backend is healthy, false otherwise
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await this.client.get<HealthResponse>('/health');
      return response.data.status === 'healthy' || response.data.status === 'ok';
    } catch (error) {
      console.warn('Health check failed:', error);
      return false;
    }
  }

  /**
   * Get the base URL of the API.
   */
  getBaseURL(): string {
    return this.baseURL;
  }

  // ==========================================================================
  // Subject Management
  // ==========================================================================

  /**
   * Get all available subjects.
   *
   * @returns List of subjects with default subject indicated
   */
  async getSubjects(): Promise<SubjectListResponse> {
    try {
      const response = await this.client.get<SubjectListResponse>(`${this.apiPrefix}/subjects`);
      return response.data;
    } catch (error) {
      console.warn('Failed to fetch subjects:', error);
      // Return fallback with default subject
      return {
        subjects: [
          { id: 'us_history', name: 'US History', description: 'American History from colonial times to modern era', is_default: true },
          { id: 'biology', name: 'Biology', description: 'Comprehensive biology covering cellular to ecosystem levels', is_default: false },
          { id: 'economics', name: 'Economics', description: 'Principles of economics covering micro and macroeconomics', is_default: false },
          { id: 'world_history', name: 'World History', description: 'World history from ancient civilizations to the modern era', is_default: false },
        ],
        default_subject: 'us_history',
      };
    }
  }

  /**
   * Get theme for a specific subject.
   *
   * @param subjectId - Subject identifier
   * @returns Theme configuration with colors
   */
  async getSubjectTheme(subjectId: string): Promise<SubjectTheme> {
    try {
      const response = await this.client.get<SubjectTheme>(
        `${this.apiPrefix}/subjects/${subjectId}/theme`
      );
      return response.data;
    } catch (error) {
      console.warn(`Failed to fetch theme for ${subjectId}:`, error);
      // Return default theme
      return {
        subject_id: subjectId,
        primary_color: '#6366f1',
        secondary_color: '#e0e7ff',
        accent_color: '#4f46e5',
        chapter_colors: { default: '#6366f1' },
      };
    }
  }

  /**
   * Get detailed information about a subject.
   *
   * @param subjectId - Subject identifier
   * @returns Subject detail information
   */
  async getSubjectDetail(subjectId: string): Promise<SubjectDetailResponse> {
    const response = await this.client.get<SubjectDetailResponse>(
      `${this.apiPrefix}/subjects/${subjectId}`
    );
    return response.data;
  }

  /**
   * Generate a quiz for a topic.
   *
   * @param topic - Topic to generate quiz for
   * @param numQuestions - Number of questions (default: 3)
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   */
  async generateQuiz(topic: string, numQuestions: number = 3, subject?: string): Promise<any> {
    const response = await this.client.post(`${this.apiPrefix}/quiz/generate`, null, {
      params: { topic, num_questions: numQuestions, ...(subject && { subject }) },
    });
    return response.data;
  }

  /**
   * Ask a question with SSE streaming response.
   *
   * Returns an object with metadata and a ReadableStream of tokens.
   * The first SSE event contains metadata (sources, expanded_concepts),
   * subsequent events contain answer tokens.
   *
   * @param request - Question request
   * @param subject - Subject ID
   * @param onToken - Callback for each token
   * @param onMetadata - Callback for metadata (sources, concepts, etc.)
   * @param onDone - Callback when streaming is complete
   * @param onError - Callback on error
   */
  async askQuestionStream(
    request: QuestionRequest,
    subject?: string,
    callbacks?: {
      onToken?: (token: string) => void;
      onMetadata?: (metadata: any) => void;
      onDone?: () => void;
      onError?: (error: string) => void;
    }
  ): Promise<void> {
    const payload = {
      question: request.question,
      use_kg_expansion: request.use_kg_expansion ?? true,
      top_k: request.top_k ?? 5,
      subject: subject,
    };

    const response = await fetch(`${this.baseURL}${this.apiPrefix}/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorText = await response.text();
      callbacks?.onError?.(errorText || `HTTP ${response.status}`);
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      callbacks?.onError?.('No response body');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;

          const dataStr = trimmed.slice(6);
          if (dataStr === '[DONE]') {
            callbacks?.onDone?.();
            return;
          }

          try {
            const data = JSON.parse(dataStr);
            if (data.type === 'metadata') {
              callbacks?.onMetadata?.(data);
            } else if (data.type === 'token') {
              callbacks?.onToken?.(data.content);
            } else if (data.type === 'error') {
              callbacks?.onError?.(data.content);
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
      callbacks?.onDone?.();
    } finally {
      reader.releaseLock();
    }
  }
}

// Export default instance with environment-based configuration
export const apiClient = new ApiClient();

// Export class for testing and custom instances
export default ApiClient;
