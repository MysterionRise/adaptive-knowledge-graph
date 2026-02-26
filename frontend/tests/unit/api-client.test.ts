/* eslint-disable no-var */
// Polyfill TextEncoder/TextDecoder for jsdom (used by SSE streaming tests)
import { TextEncoder, TextDecoder } from 'util';
Object.assign(global, { TextEncoder, TextDecoder });

// Use var to avoid temporal dead zone — jest.mock is hoisted above const/let declarations
var mockGet: jest.Mock;
var mockPost: jest.Mock;
var mockAxiosInstance: any;

jest.mock('axios', () => {
  mockGet = jest.fn();
  mockPost = jest.fn();
  mockAxiosInstance = {
    get: mockGet,
    post: mockPost,
    interceptors: {
      response: { use: jest.fn() },
      request: { use: jest.fn() },
    },
  };
  return {
    __esModule: true,
    default: {
      create: jest.fn(() => mockAxiosInstance),
    },
  };
});

import axios from 'axios';
import ApiClient from '@/lib/api-client';

describe('ApiClient', () => {
  let client: ApiClient;

  beforeEach(() => {
    jest.clearAllMocks();
    (axios.create as jest.Mock).mockReturnValue(mockAxiosInstance);
    client = new ApiClient('http://localhost:8000');
  });

  describe('getGraphStats', () => {
    it('should fetch graph statistics successfully', async () => {
      const mockStats = {
        concept_count: 150,
        module_count: 42,
        relationship_count: 320,
      };

      mockGet.mockResolvedValue({ data: mockStats });

      const stats = await client.getGraphStats();
      expect(stats).toEqual(mockStats);
    });

    it('should propagate error when API fails', async () => {
      mockGet.mockRejectedValue(new Error('Network error'));

      await expect(client.getGraphStats()).rejects.toThrow('Network error');
    });
  });

  describe('askQuestion', () => {
    it('should send question and receive response', async () => {
      const mockResponse = {
        question: 'What is photosynthesis?',
        answer: 'Photosynthesis is...',
        sources: [],
        expanded_concepts: ['Photosynthesis', 'Chloroplast'],
        retrieved_count: 5,
        model: 'llama3.1:8b',
        attribution: 'OpenStax Biology 2e',
      };

      mockPost.mockResolvedValue({ data: mockResponse });

      const response = await client.askQuestion({
        question: 'What is photosynthesis?',
        use_kg_expansion: true,
        top_k: 5,
      });

      expect(response).toEqual(mockResponse);
      expect(response.expanded_concepts).toContain('Photosynthesis');
    });
  });

  describe('health check', () => {
    it('should return true when API is healthy', async () => {
      mockGet.mockResolvedValue({ data: { status: 'ok' } });

      const isHealthy = await client.healthCheck();
      expect(isHealthy).toBe(true);
    });

    it('should return false when API is down', async () => {
      mockGet.mockRejectedValue(new Error('Connection refused'));

      const isHealthy = await client.healthCheck();
      expect(isHealthy).toBe(false);
    });
  });

  // ==========================================================================
  // New test groups for previously untested methods
  // ==========================================================================

  describe('getGraphData', () => {
    it('should fetch graph data with default params', async () => {
      const mockData = {
        nodes: [
          { data: { id: 'n1', label: 'Photosynthesis', importance: 0.9 } },
          { data: { id: 'n2', label: 'Chloroplast', importance: 0.7 } },
        ],
        edges: [
          { data: { id: 'e1', source: 'n1', target: 'n2', type: 'RELATES_TO', label: 'occurs in' } },
        ],
      };

      mockGet.mockResolvedValue({ data: mockData });

      const result = await client.getGraphData();
      expect(result).toEqual(mockData);
      expect(mockGet).toHaveBeenCalledWith('/api/v1/graph/data', {
        params: { limit: 100 },
      });
    });

    it('should pass custom limit and subject params', async () => {
      const mockData = { nodes: [], edges: [] };
      mockGet.mockResolvedValue({ data: mockData });

      const result = await client.getGraphData(50, 'us_history');
      expect(result).toEqual(mockData);
      expect(mockGet).toHaveBeenCalledWith('/api/v1/graph/data', {
        params: { limit: 50, subject: 'us_history' },
      });
    });
  });

  describe('getTopConcepts', () => {
    it('should fetch top concepts successfully', async () => {
      const mockConcepts = [
        { name: 'Photosynthesis', score: 0.95, is_key_term: true, frequency: 12 },
        { name: 'Chloroplast', score: 0.8, is_key_term: false, frequency: 7 },
      ];

      mockGet.mockResolvedValue({ data: mockConcepts });

      const result = await client.getTopConcepts(10);
      expect(result).toEqual(mockConcepts);
      expect(mockGet).toHaveBeenCalledWith('/api/v1/concepts/top', {
        params: { limit: 10 },
      });
    });

    it('should return empty array on error (graceful degradation)', async () => {
      mockGet.mockRejectedValue(new Error('Server error'));

      const result = await client.getTopConcepts();
      expect(result).toEqual([]);
    });
  });

  describe('getBaseURL', () => {
    it('should return the configured base URL', () => {
      expect(client.getBaseURL()).toBe('http://localhost:8000');
    });
  });

  describe('getSubjects', () => {
    it('should fetch available subjects', async () => {
      const mockResponse = {
        subjects: [
          { id: 'us_history', name: 'US History', description: 'US History course', is_default: true },
          { id: 'biology', name: 'Biology', description: 'Biology course', is_default: false },
        ],
        default_subject: 'us_history',
      };

      mockGet.mockResolvedValue({ data: mockResponse });

      const result = await client.getSubjects();
      expect(result).toEqual(mockResponse);
      expect(result.subjects).toHaveLength(2);
      expect(result.default_subject).toBe('us_history');
      expect(mockGet).toHaveBeenCalledWith('/api/v1/subjects');
    });
  });

  describe('getSubjectTheme', () => {
    it('should fetch theme for a specific subject', async () => {
      const mockTheme = {
        subject_id: 'us_history',
        primary_color: '#1a237e',
        secondary_color: '#283593',
        accent_color: '#448aff',
        chapter_colors: { 'Chapter 1': '#e53935', 'Chapter 2': '#43a047' },
      };

      mockGet.mockResolvedValue({ data: mockTheme });

      const result = await client.getSubjectTheme('us_history');
      expect(result).toEqual(mockTheme);
      expect(mockGet).toHaveBeenCalledWith('/api/v1/subjects/us_history/theme');
    });
  });

  describe('getSubjectDetail', () => {
    it('should fetch detail for a specific subject', async () => {
      const mockDetail = {
        id: 'us_history',
        name: 'US History',
        description: 'American History course materials',
        attribution: 'OpenStax US History',
        opensearch_index: 'kg_chunks_us_history',
        book_count: 2,
        is_default: true,
      };

      mockGet.mockResolvedValue({ data: mockDetail });

      const result = await client.getSubjectDetail('us_history');
      expect(result).toEqual(mockDetail);
      expect(mockGet).toHaveBeenCalledWith('/api/v1/subjects/us_history');
    });
  });

  describe('generateQuiz', () => {
    it('should generate quiz with topic, numQuestions, and subject', async () => {
      const mockQuiz = {
        topic: 'Photosynthesis',
        questions: [
          {
            question: 'What is the primary pigment in photosynthesis?',
            options: ['Chlorophyll', 'Carotene', 'Xanthophyll', 'Phycocyanin'],
            correct_answer: 0,
          },
        ],
      };

      mockPost.mockResolvedValue({ data: mockQuiz });

      const result = await client.generateQuiz('Photosynthesis', 5, 'biology');
      expect(result).toEqual(mockQuiz);
      expect(mockPost).toHaveBeenCalledWith('/api/v1/quiz/generate', null, {
        params: { topic: 'Photosynthesis', num_questions: 5, subject: 'biology' },
      });
    });

    it('should use default numQuestions when not specified', async () => {
      const mockQuiz = { topic: 'Civil War', questions: [] };
      mockPost.mockResolvedValue({ data: mockQuiz });

      await client.generateQuiz('Civil War');
      expect(mockPost).toHaveBeenCalledWith('/api/v1/quiz/generate', null, {
        params: { topic: 'Civil War', num_questions: 3 },
      });
    });
  });

  describe('askQuestionStream', () => {
    let originalFetch: typeof global.fetch;

    beforeEach(() => {
      originalFetch = global.fetch;
    });

    afterEach(() => {
      global.fetch = originalFetch;
    });

    it('should call onMetadata when metadata event is received', async () => {
      const onMetadata = jest.fn();
      const onToken = jest.fn();
      const onDone = jest.fn();

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"metadata","sources":[],"expanded_concepts":["A"]}\n'),
          })
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: [DONE]\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'What is X?' },
        undefined,
        { onMetadata, onToken, onDone }
      );

      expect(onMetadata).toHaveBeenCalledWith({
        type: 'metadata',
        sources: [],
        expanded_concepts: ['A'],
      });
      expect(onDone).toHaveBeenCalled();
      expect(onToken).not.toHaveBeenCalled();
      expect(mockReader.releaseLock).toHaveBeenCalled();
    });

    it('should call onToken for each token event', async () => {
      const onToken = jest.fn();
      const onDone = jest.fn();

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"token","content":"Hello"}\n'),
          })
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"token","content":" world"}\n'),
          })
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: [DONE]\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'Hello?' },
        undefined,
        { onToken, onDone }
      );

      expect(onToken).toHaveBeenCalledTimes(2);
      expect(onToken).toHaveBeenNthCalledWith(1, 'Hello');
      expect(onToken).toHaveBeenNthCalledWith(2, ' world');
      expect(onDone).toHaveBeenCalled();
    });

    it('should call onDone when [DONE] is received', async () => {
      const onDone = jest.fn();

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: [DONE]\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'Test' },
        undefined,
        { onDone }
      );

      expect(onDone).toHaveBeenCalledTimes(1);
    });

    it('should call onError when response is not ok', async () => {
      const onError = jest.fn();

      global.fetch = jest.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: jest.fn().mockResolvedValue('Internal Server Error'),
      });

      await client.askQuestionStream(
        { question: 'Fail?' },
        undefined,
        { onError }
      );

      expect(onError).toHaveBeenCalledWith('Internal Server Error');
    });

    it('should call onError with HTTP status when error text is empty', async () => {
      const onError = jest.fn();

      global.fetch = jest.fn().mockResolvedValue({
        ok: false,
        status: 503,
        text: jest.fn().mockResolvedValue(''),
      });

      await client.askQuestionStream(
        { question: 'Fail?' },
        undefined,
        { onError }
      );

      expect(onError).toHaveBeenCalledWith('HTTP 503');
    });

    it('should call onError when response body is null', async () => {
      const onError = jest.fn();

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: null,
      });

      await client.askQuestionStream(
        { question: 'No body?' },
        undefined,
        { onError }
      );

      expect(onError).toHaveBeenCalledWith('No response body');
    });

    it('should parse multiple SSE events from a single chunk', async () => {
      const onMetadata = jest.fn();
      const onToken = jest.fn();
      const onDone = jest.fn();

      const multiLineChunk =
        'data: {"type":"metadata","sources":[]}\n' +
        'data: {"type":"token","content":"Hi"}\n' +
        'data: {"type":"token","content":"!"}\n' +
        'data: [DONE]\n';

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode(multiLineChunk),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'Multi?' },
        undefined,
        { onMetadata, onToken, onDone }
      );

      expect(onMetadata).toHaveBeenCalledWith({ type: 'metadata', sources: [] });
      expect(onToken).toHaveBeenCalledTimes(2);
      expect(onToken).toHaveBeenNthCalledWith(1, 'Hi');
      expect(onToken).toHaveBeenNthCalledWith(2, '!');
      expect(onDone).toHaveBeenCalledTimes(1);
    });

    it('should send correct payload including subject via fetch', async () => {
      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: [DONE]\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'What happened?', use_kg_expansion: false, top_k: 3 },
        'us_history',
        { onDone: jest.fn() }
      );

      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/ask/stream',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: 'What happened?',
            use_kg_expansion: false,
            top_k: 3,
            subject: 'us_history',
          }),
          signal: undefined,
        }
      );
    });

    it('should pass abort signal to fetch', async () => {
      const controller = new AbortController();

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: [DONE]\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'Abort test' },
        undefined,
        { onDone: jest.fn() },
        controller.signal
      );

      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ signal: controller.signal })
      );
    });

    it('should call onDone when reader ends without [DONE] marker', async () => {
      const onDone = jest.fn();
      const onToken = jest.fn();

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"token","content":"partial"}\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'Incomplete stream' },
        undefined,
        { onToken, onDone }
      );

      expect(onToken).toHaveBeenCalledWith('partial');
      expect(onDone).toHaveBeenCalledTimes(1);
    });

    it('should skip malformed JSON in SSE data', async () => {
      const onToken = jest.fn();
      const onDone = jest.fn();
      const onError = jest.fn();

      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {broken json}\ndata: {"type":"token","content":"ok"}\ndata: [DONE]\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        releaseLock: jest.fn(),
      };

      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      });

      await client.askQuestionStream(
        { question: 'Malformed?' },
        undefined,
        { onToken, onDone, onError }
      );

      expect(onError).not.toHaveBeenCalled();
      expect(onToken).toHaveBeenCalledWith('ok');
      expect(onDone).toHaveBeenCalledTimes(1);
    });
  });
});
