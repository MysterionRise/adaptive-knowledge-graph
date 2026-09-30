/**
 * API client for the Adaptive Knowledge Graph backend.
 *
 * Every HTTP request the frontend makes goes through this module:
 * - one base URL (`NEXT_PUBLIC_API_URL`) and the optional `X-API-Key` header,
 * - a timeout on every request, with a longer one for endpoints that wait for the LLM,
 * - `AbortSignal` support, so components can cancel requests they no longer need,
 * - one error type, `ApiError`, whose message is the backend's `detail` when there is one.
 *
 * JSON endpoints use axios; the streaming answer endpoint uses `fetch`, which exposes the
 * response body as a stream.
 */

import axios, { type AxiosAdapter, type AxiosInstance } from 'axios';
import {
  ABORTED_MESSAGE,
  ApiError,
  extractErrorDetail,
  messageForStatus,
  networkErrorMessage,
  timeoutMessage,
} from './api-errors';
import type {
  AdaptiveQuiz,
  DemoStatusResponse,
  GraphData,
  GraphStats,
  LearningPathResponse,
  MasteryUpdateResponse,
  QuestionRequest,
  QuestionResponse,
  Quiz,
  RecommendationRequest,
  RecommendationResponse,
  StreamMetadata,
  StudentProfileResponse,
  SubjectListResponse,
  SubjectTheme,
  TopConcept,
} from './types';

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';
const API_KEY_HEADER = 'X-API-Key';

/** Timeout for regular requests. */
export const DEFAULT_TIMEOUT_MS = 30_000;
/**
 * Timeout for endpoints that wait for the LLM (answers, quiz generation, recommendations).
 * A local model on a CPU can need a minute or more per answer, and Ollama queues concurrent
 * requests (the comparison page sends two at once), so 30 s is far too short for them.
 */
export const LLM_TIMEOUT_MS = 180_000;
/** An answer stream fails when no data arrives for this long. */
export const STREAM_IDLE_TIMEOUT_MS = 120_000;

/** Options accepted by every request method. */
export interface RequestOptions {
  signal?: AbortSignal;
}

export interface StreamCallbacks {
  /** First event: sources, expanded concepts, model and attribution. */
  onMetadata?: (metadata: StreamMetadata) => void;
  /** Each generated answer token. */
  onToken?: (token: string) => void;
}

export interface ApiClientOptions {
  /** Replaces the axios transport (tests answer requests without a network). */
  adapter?: AxiosAdapter;
}

/**
 * Build API headers, including the optional API key when `NEXT_PUBLIC_API_KEY` is configured.
 */
export function buildApiHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const apiKey = process.env.NEXT_PUBLIC_API_KEY || '';
  if (!apiKey) return headers;
  return {
    ...headers,
    [API_KEY_HEADER]: apiKey,
  };
}

const subjectParam = (subject?: string) => (subject ? { subject } : {});

function toApiError(error: unknown, baseURL: string): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isCancel(error)) return new ApiError('aborted', ABORTED_MESSAGE, { cause: error });
  if (axios.isAxiosError(error)) {
    if (error.response) {
      const { status, data } = error.response;
      const detail = extractErrorDetail(data);
      return new ApiError('http', detail ?? messageForStatus(status), {
        status,
        detail,
        cause: error,
      });
    }
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return new ApiError('timeout', timeoutMessage(error.config?.timeout), { cause: error });
    }
  }
  return new ApiError('network', networkErrorMessage(baseURL), { cause: error });
}

/**
 * API client class for interacting with the backend.
 */
class ApiClient {
  private readonly http: AxiosInstance;

  constructor(
    private readonly baseURL: string = API_BASE_URL,
    options: ApiClientOptions = {}
  ) {
    this.http = axios.create({
      baseURL: `${baseURL}${API_PREFIX}`,
      timeout: DEFAULT_TIMEOUT_MS,
      headers: buildApiHeaders({ 'Content-Type': 'application/json' }),
      ...(options.adapter ? { adapter: options.adapter } : {}),
    });

    // Callers get an ApiError for every failure. Nothing is logged here: the caller decides
    // whether a failure is shown to the user or is worth a console message.
    this.http.interceptors.response.use(undefined, (error: unknown) =>
      Promise.reject(toApiError(error, this.baseURL))
    );
  }

  // ==========================================================================
  // Knowledge graph
  // ==========================================================================

  /**
   * Get graph statistics (concept count, module count, relationship count).
   *
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   */
  async getGraphStats(subject?: string, { signal }: RequestOptions = {}): Promise<GraphStats> {
    const { data } = await this.http.get<GraphStats>('/graph/stats', {
      params: subjectParam(subject),
      signal,
    });
    return data;
  }

  /**
   * Get graph data for visualization (nodes and edges).
   *
   * @param limit - Maximum number of concepts to return (default: 100)
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   */
  async getGraphData(
    limit: number = 100,
    subject?: string,
    { signal }: RequestOptions = {}
  ): Promise<GraphData> {
    const { data } = await this.http.get<GraphData>('/graph/data', {
      params: { limit, ...subjectParam(subject) },
      signal,
    });
    return data;
  }

  /**
   * Get the most important concepts of a subject.
   */
  async getTopConceptsForSubject(
    limit: number = 20,
    subject?: string,
    { signal }: RequestOptions = {}
  ): Promise<TopConcept[]> {
    const { data } = await this.http.get<TopConcept[]>('/concepts/top', {
      params: { limit, ...subjectParam(subject) },
      signal,
    });
    return data;
  }

  /**
   * Get the prerequisite chain of a concept.
   */
  async getLearningPath(
    conceptName: string,
    maxDepth: number = 5,
    subject?: string,
    { signal }: RequestOptions = {}
  ): Promise<LearningPathResponse> {
    const { data } = await this.http.get<LearningPathResponse>(
      `/learning-path/${encodeURIComponent(conceptName)}`,
      { params: { max_depth: maxDepth, ...subjectParam(subject) }, signal }
    );
    return data;
  }

  // ==========================================================================
  // Questions and answers
  // ==========================================================================

  /**
   * Ask a question using KG-aware RAG (waits for the complete answer).
   *
   * @param request - Question request with question text and optional parameters
   * @param subject - Subject ID (e.g., 'us_history', 'biology')
   */
  async askQuestion(
    request: QuestionRequest,
    subject?: string,
    { signal }: RequestOptions = {}
  ): Promise<QuestionResponse> {
    const { data } = await this.http.post<QuestionResponse>(
      '/ask',
      this.questionPayload(request, subject),
      { timeout: LLM_TIMEOUT_MS, signal }
    );
    return data;
  }

  /**
   * Ask a question and stream the answer (server-sent events).
   *
   * The first event carries the metadata (sources, expanded concepts), then answer tokens
   * follow. The promise resolves when the answer is complete and rejects with an `ApiError`
   * when the request fails, the stream reports an error, no data arrives for
   * `STREAM_IDLE_TIMEOUT_MS`, or `signal` aborts.
   */
  async askQuestionStream(
    request: QuestionRequest,
    subject?: string,
    callbacks: StreamCallbacks = {},
    signal?: AbortSignal
  ): Promise<void> {
    if (signal?.aborted) throw new ApiError('aborted', ABORTED_MESSAGE);

    // Aborted by the caller's signal or by the idle timer.
    const controller = new AbortController();
    const abortFromCaller = () => controller.abort();
    signal?.addEventListener('abort', abortFromCaller);

    let timedOut = false;
    let idleTimer: ReturnType<typeof setTimeout> | undefined;
    const restartIdleTimer = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, STREAM_IDLE_TIMEOUT_MS);
    };

    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      restartIdleTimer();
      const response = await fetch(`${this.baseURL}${API_PREFIX}/ask/stream`, {
        method: 'POST',
        headers: buildApiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(this.questionPayload(request, subject)),
        signal: controller.signal,
      });

      if (!response.ok) {
        const detail = extractErrorDetail(await response.text().catch(() => ''));
        throw new ApiError('http', detail ?? messageForStatus(response.status), {
          status: response.status,
          detail,
        });
      }

      reader = response.body?.getReader();
      if (!reader) throw new ApiError('network', 'The server sent an empty response.');

      const streamError = await this.readAnswerStream(reader, callbacks, restartIdleTimer);
      if (streamError !== null) {
        throw new ApiError('stream', streamError, { detail: streamError });
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (timedOut) throw new ApiError('timeout', timeoutMessage(STREAM_IDLE_TIMEOUT_MS), { cause: error });
      if (controller.signal.aborted) throw new ApiError('aborted', ABORTED_MESSAGE, { cause: error });
      throw new ApiError('network', networkErrorMessage(this.baseURL), { cause: error });
    } finally {
      clearTimeout(idleTimer);
      signal?.removeEventListener('abort', abortFromCaller);
      reader?.releaseLock();
    }
  }

  /** Read SSE events until `[DONE]`; returns the stream's error message, if it sent one. */
  private async readAnswerStream(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    { onMetadata, onToken }: StreamCallbacks,
    onData: () => void
  ): Promise<string | null> {
    const decoder = new TextDecoder();
    let buffer = '';
    let streamError: string | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) return streamError;
      onData();

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;

        const payload = trimmed.slice('data:'.length).trim();
        if (payload === '[DONE]') return streamError;

        let event: { type?: unknown; content?: unknown };
        try {
          event = JSON.parse(payload);
        } catch {
          continue; // Skip malformed events
        }
        if (event.type === 'metadata') {
          onMetadata?.(event as StreamMetadata);
        } else if (event.type === 'token' && typeof event.content === 'string') {
          onToken?.(event.content);
        } else if (event.type === 'error') {
          streamError =
            typeof event.content === 'string' && event.content.trim()
              ? event.content
              : 'The answer could not be generated.';
        }
      }
    }
  }

  private questionPayload(request: QuestionRequest, subject?: string) {
    return {
      question: request.question,
      use_kg_expansion: request.use_kg_expansion ?? true,
      top_k: request.top_k ?? 5,
      subject,
    };
  }

  // ==========================================================================
  // Quizzes and recommendations
  // ==========================================================================

  /**
   * Generate a quiz with mixed difficulty for a topic.
   */
  async generateQuiz(
    topic: string,
    numQuestions: number = 3,
    subject?: string,
    { signal }: RequestOptions = {}
  ): Promise<Quiz> {
    const { data } = await this.http.post<Quiz>('/quiz/generate', null, {
      params: { topic, num_questions: numQuestions, ...subjectParam(subject) },
      timeout: LLM_TIMEOUT_MS,
      signal,
    });
    return data;
  }

  /**
   * Generate a quiz whose difficulty targets the learner's mastery of the topic.
   */
  async generateAdaptiveQuiz(
    topic: string,
    numQuestions: number = 3,
    subject?: string,
    { signal }: RequestOptions = {}
  ): Promise<AdaptiveQuiz> {
    const { data } = await this.http.post<AdaptiveQuiz>('/quiz/generate-adaptive', null, {
      params: { topic, num_questions: numQuestions, ...subjectParam(subject) },
      timeout: LLM_TIMEOUT_MS,
      signal,
    });
    return data;
  }

  /**
   * Get remediation and advancement recommendations for a finished quiz.
   */
  async getQuizRecommendations(
    request: RecommendationRequest,
    { signal }: RequestOptions = {}
  ): Promise<RecommendationResponse> {
    const { data } = await this.http.post<RecommendationResponse>(
      '/quiz/recommendations',
      request,
      { timeout: LLM_TIMEOUT_MS, signal }
    );
    return data;
  }

  // ==========================================================================
  // Student profile
  // ==========================================================================

  async getStudentProfile({ signal }: RequestOptions = {}): Promise<StudentProfileResponse> {
    const { data } = await this.http.get<StudentProfileResponse>('/student/profile', { signal });
    return data;
  }

  /**
   * Record an answer; the backend returns the updated mastery estimate for the concept.
   */
  async updateStudentMastery(
    concept: string,
    correct: boolean,
    { signal }: RequestOptions = {}
  ): Promise<MasteryUpdateResponse> {
    const { data } = await this.http.post<MasteryUpdateResponse>(
      '/student/mastery',
      { concept, correct },
      { signal }
    );
    return data;
  }

  async resetStudentProfile({ signal }: RequestOptions = {}): Promise<StudentProfileResponse> {
    const { data } = await this.http.post<StudentProfileResponse>('/student/reset', null, {
      signal,
    });
    return data;
  }

  // ==========================================================================
  // Subjects and demo status
  // ==========================================================================

  /**
   * Get all configured subjects and the default subject.
   */
  async getSubjects({ signal }: RequestOptions = {}): Promise<SubjectListResponse> {
    const { data } = await this.http.get<SubjectListResponse>('/subjects', { signal });
    return data;
  }

  /**
   * Get the colour theme of a subject.
   */
  async getSubjectTheme(subjectId: string, { signal }: RequestOptions = {}): Promise<SubjectTheme> {
    const { data } = await this.http.get<SubjectTheme>(
      `/subjects/${encodeURIComponent(subjectId)}/theme`,
      { signal }
    );
    return data;
  }

  /**
   * Get the readiness of the local demo stack.
   */
  async getDemoStatus({ signal }: RequestOptions = {}): Promise<DemoStatusResponse> {
    const { data } = await this.http.get<DemoStatusResponse>('/demo/status', { signal });
    return data;
  }
}

// Export default instance with environment-based configuration
export const apiClient = new ApiClient();

// Export class for testing and custom instances
export default ApiClient;
