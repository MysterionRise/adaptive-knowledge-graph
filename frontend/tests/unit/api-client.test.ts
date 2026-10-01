// Polyfill TextEncoder/TextDecoder for jsdom (used by SSE streaming tests)
import { TextEncoder, TextDecoder } from 'util';
Object.assign(global, { TextEncoder, TextDecoder });

import { AxiosError } from 'axios';
import ApiClient, {
  buildApiHeaders,
  DEFAULT_TIMEOUT_MS,
  LLM_TIMEOUT_MS,
  STREAM_IDLE_TIMEOUT_MS,
} from '@/lib/api-client';
import { ApiError, isAbortError } from '@/lib/api-errors';
import { MockApi, json, pending } from './helpers/mockApi';

const BASE_URL = 'http://localhost:8000';

describe('ApiClient', () => {
  const api = new MockApi();
  let client: ApiClient;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_API_KEY;
    api.reset();
    client = new ApiClient(BASE_URL, { adapter: api.adapter });
  });

  afterEach(() => {
    expect(api.unexpected).toEqual([]);
  });

  /** The error a promise rejects with. */
  async function rejection(promise: Promise<unknown>): Promise<ApiError> {
    try {
      await promise;
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      return error as ApiError;
    }
    throw new Error('Expected the request to fail');
  }

  describe('API key headers', () => {
    it('builds headers without API key by default', () => {
      expect(buildApiHeaders({ 'Content-Type': 'application/json' })).toEqual({
        'Content-Type': 'application/json',
      });
    });

    it('adds X-API-Key when NEXT_PUBLIC_API_KEY is configured', () => {
      process.env.NEXT_PUBLIC_API_KEY = 'demo-key';

      expect(buildApiHeaders({ 'Content-Type': 'application/json' })).toEqual({
        'Content-Type': 'application/json',
        'X-API-Key': 'demo-key',
      });
    });

    it('sends the API key with every request', async () => {
      process.env.NEXT_PUBLIC_API_KEY = 'demo-key';
      const keyedClient = new ApiClient(BASE_URL, { adapter: api.adapter });
      api.on('GET /api/v1/student/profile', json({ mastery_levels: {} }));

      await keyedClient.getStudentProfile();

      const { headers } = api.calls('GET /api/v1/student/profile')[0].config;
      expect(headers['X-API-Key']).toBe('demo-key');
    });

    it('sends no API key header when none is configured', async () => {
      api.on('GET /api/v1/subjects', json({ subjects: [], default_subject: 'us_history' }));

      await client.getSubjects();

      expect(api.calls('GET /api/v1/subjects')[0].config.headers['X-API-Key']).toBeUndefined();
    });
  });

  describe('knowledge graph', () => {
    it('fetches graph statistics for a subject', async () => {
      const stats = { concept_count: 150, module_count: 42, relationship_count: 320 };
      api.on('GET /api/v1/graph/stats', json(stats));

      await expect(client.getGraphStats('economics')).resolves.toEqual(stats);

      const [request] = api.calls('GET /api/v1/graph/stats');
      expect(request.params.get('subject')).toBe('economics');
      expect(request.config.timeout).toBe(DEFAULT_TIMEOUT_MS);
    });

    it('omits the subject parameter when no subject is given', async () => {
      api.on('GET /api/v1/graph/stats', json({}));

      await client.getGraphStats();

      expect(api.calls('GET /api/v1/graph/stats')[0].params.has('subject')).toBe(false);
    });

    it('fetches graph data with the default limit', async () => {
      const graph = { nodes: [{ data: { id: 'n1', label: 'A', importance: 0.9 } }], edges: [] };
      api.on('GET /api/v1/graph/data', json(graph));

      await expect(client.getGraphData()).resolves.toEqual(graph);

      const [request] = api.calls('GET /api/v1/graph/data');
      expect(request.params.get('limit')).toBe('100');
      expect(request.params.has('subject')).toBe(false);
    });

    it('passes the limit and subject for graph data', async () => {
      api.on('GET /api/v1/graph/data', json({ nodes: [], edges: [] }));

      await client.getGraphData(50, 'us_history');

      const [request] = api.calls('GET /api/v1/graph/data');
      expect(request.params.get('limit')).toBe('50');
      expect(request.params.get('subject')).toBe('us_history');
    });

    it('fetches the top concepts of a subject', async () => {
      const concepts = [{ name: 'Photosynthesis', score: 0.95 }];
      api.on('GET /api/v1/concepts/top', json(concepts));

      await expect(client.getTopConceptsForSubject(6, 'biology')).resolves.toEqual(concepts);

      const [request] = api.calls('GET /api/v1/concepts/top');
      expect(request.params.get('limit')).toBe('6');
      expect(request.params.get('subject')).toBe('biology');
    });

    it('reports top-concept failures instead of returning an empty list', async () => {
      api.on('GET /api/v1/concepts/top', json({ detail: 'Database connection failed' }, 503));

      const error = await rejection(client.getTopConceptsForSubject(6, 'us_history'));

      expect(error.status).toBe(503);
      expect(error.message).toBe('Database connection failed');
    });

    it('fetches the learning path of a concept', async () => {
      const path = { target_concept: 'Civil War', prerequisites: [], total_concepts: 1 };
      api.on('GET /api/v1/learning-path/Civil%20War%20%2F%20Reconstruction', json(path));

      await expect(
        client.getLearningPath('Civil War / Reconstruction', 4, 'us_history')
      ).resolves.toEqual(path);

      const [request] = api.calls('GET /api/v1/learning-path/Civil%20War%20%2F%20Reconstruction');
      expect(request.params.get('max_depth')).toBe('4');
      expect(request.params.get('subject')).toBe('us_history');
    });
  });

  describe('questions', () => {
    it('asks a question with default options and the LLM timeout', async () => {
      const answer = { question: 'What is X?', answer: 'X is...', sources: [] };
      api.on('POST /api/v1/ask', json(answer));

      await expect(client.askQuestion({ question: 'What is X?' }, 'biology')).resolves.toEqual(answer);

      const [request] = api.calls('POST /api/v1/ask');
      expect(request.body).toEqual({
        question: 'What is X?',
        use_kg_expansion: true,
        top_k: 5,
        subject: 'biology',
      });
      expect(request.config.timeout).toBe(LLM_TIMEOUT_MS);
      expect(LLM_TIMEOUT_MS).toBeGreaterThan(DEFAULT_TIMEOUT_MS);
    });

    it('sends the KG expansion setting and top_k', async () => {
      api.on('POST /api/v1/ask', json({}));

      await client.askQuestion({ question: 'Why?', use_kg_expansion: false, top_k: 3 });

      expect(api.calls('POST /api/v1/ask')[0].body).toEqual(
        expect.objectContaining({ use_kg_expansion: false, top_k: 3 })
      );
    });
  });

  describe('quizzes and recommendations', () => {
    const quiz = { id: 'q', title: 'Quiz', questions: [] };

    it('generates a quiz with the LLM timeout', async () => {
      api.on('POST /api/v1/quiz/generate', json(quiz));

      await expect(client.generateQuiz('Photosynthesis', 5, 'biology')).resolves.toEqual(quiz);

      const [request] = api.calls('POST /api/v1/quiz/generate');
      expect(Object.fromEntries(request.params)).toEqual({
        topic: 'Photosynthesis',
        num_questions: '5',
        subject: 'biology',
      });
      expect(request.config.timeout).toBe(LLM_TIMEOUT_MS);
    });

    it('generates an adaptive quiz with three questions by default', async () => {
      api.on('POST /api/v1/quiz/generate-adaptive', json({ ...quiz, adapted: true }));

      await client.generateAdaptiveQuiz('The Civil War');

      const [request] = api.calls('POST /api/v1/quiz/generate-adaptive');
      expect(Object.fromEntries(request.params)).toEqual({
        topic: 'The Civil War',
        num_questions: '3',
      });
      expect(request.config.timeout).toBe(LLM_TIMEOUT_MS);
    });

    it('posts quiz results for recommendations', async () => {
      const recommendations = { path_type: 'advancement', score_pct: 100, remediation: [], advancement: [], summary: 'Done' };
      api.on('POST /api/v1/quiz/recommendations', json(recommendations));
      const body = {
        topic: 'The Civil War',
        question_results: [{ question_id: 'q1', related_concept: 'Slavery', correct: true }],
        student_id: 'default',
        subject: 'us_history',
      };

      await expect(client.getQuizRecommendations(body)).resolves.toEqual(recommendations);

      const [request] = api.calls('POST /api/v1/quiz/recommendations');
      expect(request.body).toEqual(body);
      expect(request.config.timeout).toBe(LLM_TIMEOUT_MS);
    });
  });

  describe('student profile', () => {
    it('loads the profile', async () => {
      const profile = { student_id: 'default', overall_ability: 0.3, mastery_levels: { A: 0.5 }, updated_at: 'now' };
      api.on('GET /api/v1/student/profile', json(profile));

      await expect(client.getStudentProfile()).resolves.toEqual(profile);
    });

    it('records an answer', async () => {
      api.on('POST /api/v1/student/mastery', json({ concept: 'A', new_mastery: 0.45 }));

      await client.updateStudentMastery('A', true);

      expect(api.calls('POST /api/v1/student/mastery')[0].body).toEqual({ concept: 'A', correct: true });
    });

    it('resets the profile', async () => {
      api.on('POST /api/v1/student/reset', json({ student_id: 'default', mastery_levels: {} }));

      await client.resetStudentProfile();

      expect(api.calls('POST /api/v1/student/reset')).toHaveLength(1);
    });
  });

  describe('subjects and demo status', () => {
    it('fetches the subjects', async () => {
      const subjects = {
        subjects: [{ id: 'us_history', name: 'US History', description: '', is_default: true, available: true }],
        default_subject: 'us_history',
      };
      api.on('GET /api/v1/subjects', json(subjects));

      await expect(client.getSubjects()).resolves.toEqual(subjects);
    });

    it('fetches the theme of a subject', async () => {
      const theme = { subject_id: 'us_history', primary_color: '#1a237e', chapter_colors: {} };
      api.on('GET /api/v1/subjects/us_history/theme', json(theme));

      await expect(client.getSubjectTheme('us_history')).resolves.toEqual(theme);
    });

    it('fetches the demo status', async () => {
      const status = { status: 'ready', services: {} };
      api.on('GET /api/v1/demo/status', json(status));

      await expect(client.getDemoStatus()).resolves.toEqual(status);
    });
  });

  describe('cancellation', () => {
    it('passes the AbortSignal and reports an aborted request', async () => {
      api.on('GET /api/v1/graph/data', () => pending());
      const controller = new AbortController();

      const request = client.getGraphData(100, 'us_history', { signal: controller.signal });
      controller.abort();
      const error = await rejection(request);

      expect(error.kind).toBe('aborted');
      expect(isAbortError(error)).toBe(true);
      expect(api.calls('GET /api/v1/graph/data')[0].config.signal).toBe(controller.signal);
    });
  });

  describe('errors', () => {
    it.each([
      [404, { detail: 'Subject not found' }, 'Subject not found'],
      [503, { detail: 'LLM service temporarily unavailable' }, 'LLM service temporarily unavailable'],
      [502, { detail: 'The language model returned an invalid quiz' }, 'The language model returned an invalid quiz'],
      [429, { detail: 'Rate limit exceeded: 30 per 1 minute', error: 'Rate limit exceeded', retry_after: '60' }, 'Rate limit exceeded: 30 per 1 minute'],
    ])('exposes the backend detail of a %s response', async (status, body, message) => {
      api.on('POST /api/v1/ask', json(body, status));

      const error = await rejection(client.askQuestion({ question: 'Why?' }));

      expect(error).toMatchObject({ kind: 'http', status, detail: message, message });
    });

    it('turns validation errors into a readable message', async () => {
      api.on(
        'POST /api/v1/ask',
        json(
          {
            detail: [
              {
                loc: ['body', 'question'],
                msg: 'Value error, question must not contain HTML or script markup',
                type: 'value_error',
              },
            ],
          },
          422
        )
      );

      const error = await rejection(client.askQuestion({ question: '<b>Why?</b>' }));

      expect(error.status).toBe(422);
      expect(error.message).toBe('question: question must not contain HTML or script markup');
    });

    it('falls back to a status message when the error has no detail', async () => {
      api.on('GET /api/v1/graph/stats', { status: 500, data: '<html>Internal Server Error</html>' });

      const error = await rejection(client.getGraphStats());

      expect(error.detail).toBeNull();
      expect(error.message).toBe('The server could not complete the request (HTTP 500).');
    });

    it('reports an unreachable backend', async () => {
      api.on('GET /api/v1/subjects', (request) => {
        throw new AxiosError('Network Error', AxiosError.ERR_NETWORK, request.config);
      });

      const error = await rejection(client.getSubjects());

      expect(error.kind).toBe('network');
      expect(error.status).toBeNull();
      expect(error.message).toBe(
        'Could not reach the API at http://localhost:8000. Check that the backend is running.'
      );
    });

    it('reports a timeout with its duration', async () => {
      api.on('POST /api/v1/ask', (request) => {
        throw new AxiosError('timeout exceeded', AxiosError.ECONNABORTED, request.config);
      });

      const error = await rejection(client.askQuestion({ question: 'Why?' }));

      expect(error.kind).toBe('timeout');
      expect(error.message).toBe(
        `The server did not respond within ${LLM_TIMEOUT_MS / 1000} seconds.`
      );
    });
  });
});

// =============================================================================
// Streaming answers
// =============================================================================

interface MockReader {
  read: jest.Mock;
  releaseLock: jest.Mock;
}

/** A reader returning the given SSE chunks, then the end of the stream. */
function readerFor(...chunks: string[]): MockReader {
  const read = jest.fn();
  for (const chunk of chunks) {
    read.mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(chunk) });
  }
  read.mockResolvedValue({ done: true, value: undefined });
  return { read, releaseLock: jest.fn() };
}

const sse = (event: unknown) => `data: ${typeof event === 'string' ? event : JSON.stringify(event)}\n\n`;

describe('ApiClient.askQuestionStream', () => {
  const originalFetch = global.fetch;
  const fetchMock = jest.fn();
  let client: ApiClient;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_API_KEY;
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
    client = new ApiClient(BASE_URL);
  });

  afterEach(() => {
    jest.useRealTimers();
    global.fetch = originalFetch;
  });

  const respondWith = (reader: MockReader) =>
    fetchMock.mockResolvedValue({ ok: true, status: 200, body: { getReader: () => reader } });

  /** A stream that delivers nothing until its request is aborted. */
  const respondWithSilentStream = () =>
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      Promise.resolve({
        ok: true,
        status: 200,
        body: {
          getReader: () => ({
            read: () =>
              new Promise((_resolve, reject) => {
                const abort = () =>
                  reject(new DOMException('The operation was aborted.', 'AbortError'));
                if (init.signal?.aborted) abort();
                else init.signal?.addEventListener('abort', abort);
              }),
            releaseLock: jest.fn(),
          }),
        },
      })
    );

  async function streamRejection(promise: Promise<unknown>): Promise<ApiError> {
    try {
      await promise;
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      return error as ApiError;
    }
    throw new Error('Expected the stream to fail');
  }

  it('delivers the metadata and the answer tokens', async () => {
    const reader = readerFor(
      sse({ type: 'metadata', sources: [], expanded_concepts: ['A'] }),
      sse({ type: 'token', content: 'Hello' }) + sse({ type: 'token', content: ' world' }),
      sse('[DONE]')
    );
    respondWith(reader);
    const onMetadata = jest.fn();
    const onToken = jest.fn();

    await client.askQuestionStream({ question: 'Hi?' }, 'us_history', { onMetadata, onToken });

    expect(onMetadata).toHaveBeenCalledWith({ type: 'metadata', sources: [], expanded_concepts: ['A'] });
    expect(onToken.mock.calls).toEqual([['Hello'], [' world']]);
    expect(reader.releaseLock).toHaveBeenCalled();
  });

  it('reassembles events split across chunks', async () => {
    respondWith(readerFor('data: {"type":"tok', 'en","content":"Hi"}\n', sse('[DONE]')));
    const onToken = jest.fn();

    await client.askQuestionStream({ question: 'Hi?' }, undefined, { onToken });

    expect(onToken).toHaveBeenCalledWith('Hi');
  });

  it('stops reading at [DONE]', async () => {
    const reader = readerFor(sse('[DONE]'), sse({ type: 'token', content: 'ignored' }));
    respondWith(reader);
    const onToken = jest.fn();

    await client.askQuestionStream({ question: 'Hi?' }, undefined, { onToken });

    expect(onToken).not.toHaveBeenCalled();
    expect(reader.read).toHaveBeenCalledTimes(1);
  });

  it('finishes when the stream ends without [DONE]', async () => {
    respondWith(readerFor(sse({ type: 'token', content: 'partial' })));
    const onToken = jest.fn();

    await expect(
      client.askQuestionStream({ question: 'Hi?' }, undefined, { onToken })
    ).resolves.toBeUndefined();
    expect(onToken).toHaveBeenCalledWith('partial');
  });

  it('skips malformed events', async () => {
    respondWith(readerFor('data: {broken json}\n' + sse({ type: 'token', content: 'ok' }) + sse('[DONE]')));
    const onToken = jest.fn();

    await client.askQuestionStream({ question: 'Hi?' }, undefined, { onToken });

    expect(onToken).toHaveBeenCalledWith('ok');
  });

  it('rejects with the error event of the stream', async () => {
    respondWith(
      readerFor(
        sse({ type: 'token', content: 'Part' }),
        sse({ type: 'error', content: 'The model returned an empty answer' }),
        sse('[DONE]')
      )
    );
    const onToken = jest.fn();

    const error = await streamRejection(
      client.askQuestionStream({ question: 'Hi?' }, undefined, { onToken })
    );

    expect(onToken).toHaveBeenCalledWith('Part');
    expect(error).toMatchObject({ kind: 'stream', message: 'The model returned an empty answer' });
  });

  it('sends the question, settings and subject with the API key', async () => {
    process.env.NEXT_PUBLIC_API_KEY = 'stream-key';
    respondWith(readerFor(sse('[DONE]')));

    await client.askQuestionStream(
      { question: 'What happened?', use_kg_expansion: false, top_k: 3 },
      'us_history'
    );

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/ask/stream',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'stream-key' },
        body: JSON.stringify({
          question: 'What happened?',
          use_kg_expansion: false,
          top_k: 3,
          subject: 'us_history',
        }),
        signal: expect.any(AbortSignal),
      })
    );
  });

  it.each([
    ['a JSON detail', JSON.stringify({ detail: 'LLM service temporarily unavailable' }), 'LLM service temporarily unavailable'],
    ['plain text', 'LLM service temporarily unavailable', 'LLM service temporarily unavailable'],
    ['no body', '', 'The server could not complete the request (HTTP 503).'],
  ])('reports an HTTP error with %s', async (_label, body, message) => {
    fetchMock.mockResolvedValue({ ok: false, status: 503, text: async () => body });

    const error = await streamRejection(client.askQuestionStream({ question: 'Hi?' }));

    expect(error).toMatchObject({ kind: 'http', status: 503, message });
  });

  it('reports a response without a body', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, body: null });

    const error = await streamRejection(client.askQuestionStream({ question: 'Hi?' }));

    expect(error).toMatchObject({ kind: 'network', message: 'The server sent an empty response.' });
  });

  it('reports an unreachable backend', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const error = await streamRejection(client.askQuestionStream({ question: 'Hi?' }));

    expect(error.kind).toBe('network');
  });

  it('is cancelled by the caller signal', async () => {
    respondWithSilentStream();
    const controller = new AbortController();

    const stream = client.askQuestionStream({ question: 'Hi?' }, undefined, {}, controller.signal);
    await Promise.resolve();
    controller.abort();
    const error = await streamRejection(stream);

    expect(isAbortError(error)).toBe(true);
  });

  it('does not start when the signal is already aborted', async () => {
    const controller = new AbortController();
    controller.abort();

    const error = await streamRejection(
      client.askQuestionStream({ question: 'Hi?' }, undefined, {}, controller.signal)
    );

    expect(error.kind).toBe('aborted');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('times out when no data arrives', async () => {
    jest.useFakeTimers();
    respondWithSilentStream();

    const stream = client.askQuestionStream({ question: 'Hi?' });
    const failure = streamRejection(stream);
    await jest.advanceTimersByTimeAsync(STREAM_IDLE_TIMEOUT_MS);
    const error = await failure;

    expect(error).toMatchObject({
      kind: 'timeout',
      message: `The server did not respond within ${STREAM_IDLE_TIMEOUT_MS / 1000} seconds.`,
    });
  });
});
