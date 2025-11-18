import ApiClient, { apiClient } from '@/lib/api-client';
import axios from 'axios';

// Mock axios
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('ApiClient', () => {
  let client: ApiClient;

  beforeEach(() => {
    client = new ApiClient('http://localhost:8000');
    jest.clearAllMocks();
  });

  describe('getGraphStats', () => {
    it('should fetch graph statistics successfully', async () => {
      const mockStats = {
        concept_count: 150,
        module_count: 42,
        relationship_count: 320,
      };

      mockedAxios.create.mockReturnValue({
        get: jest.fn().mockResolvedValue({ data: mockStats }),
        post: jest.fn(),
        interceptors: {
          response: { use: jest.fn() },
          request: { use: jest.fn() },
        },
      } as any);

      const stats = await client.getGraphStats();
      expect(stats).toEqual(mockStats);
    });

    it('should fallback to mock data on error', async () => {
      mockedAxios.create.mockReturnValue({
        get: jest.fn().mockRejectedValue(new Error('Network error')),
        post: jest.fn(),
        interceptors: {
          response: { use: jest.fn() },
          request: { use: jest.fn() },
        },
      } as any);

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

      mockedAxios.create.mockReturnValue({
        get: jest.fn(),
        post: jest.fn().mockResolvedValue({ data: mockResponse }),
        interceptors: {
          response: { use: jest.fn() },
          request: { use: jest.fn() },
        },
      } as any);

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
      mockedAxios.create.mockReturnValue({
        get: jest.fn().mockResolvedValue({ data: { status: 'ok' } }),
        post: jest.fn(),
        interceptors: {
          response: { use: jest.fn() },
          request: { use: jest.fn() },
        },
      } as any);

      const isHealthy = await client.healthCheck();
      expect(isHealthy).toBe(true);
    });

    it('should return false when API is down', async () => {
      mockedAxios.create.mockReturnValue({
        get: jest.fn().mockRejectedValue(new Error('Connection refused')),
        post: jest.fn(),
        interceptors: {
          response: { use: jest.fn() },
          request: { use: jest.fn() },
        },
      } as any);

      const isHealthy = await client.healthCheck();
      expect(isHealthy).toBe(false);
    });
  });
});
