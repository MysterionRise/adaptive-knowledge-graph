/* eslint-disable no-var */
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

    it('should fallback to mock data on error', async () => {
      mockGet.mockRejectedValue(new Error('Network error'));

      const stats = await client.getGraphStats();
      expect(stats).toHaveProperty('concept_count');
      expect(stats).toHaveProperty('module_count');
      expect(stats).toHaveProperty('relationship_count');
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
});
