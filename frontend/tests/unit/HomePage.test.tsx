import { render, screen, waitFor } from '@testing-library/react';
import Home from '@/app/page';
import { apiClient } from '@/lib/api-client';

// Mock the API client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getGraphStats: jest.fn(),
  },
}));

// Mock next/link
jest.mock('next/link', () => {
  return ({ children, href }: any) => {
    return <a href={href}>{children}</a>;
  };
});

describe('Home Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders the main heading', () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    render(<Home />);

    expect(screen.getByText('Adaptive Knowledge Graph')).toBeInTheDocument();
  });

  it('displays graph statistics after loading', async () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    render(<Home />);

    await waitFor(() => {
      expect(screen.getByText('150')).toBeInTheDocument();
      expect(screen.getByText('42')).toBeInTheDocument();
      expect(screen.getByText('320')).toBeInTheDocument();
    });
  });

  it('shows loading spinner while fetching stats', () => {
    (apiClient.getGraphStats as jest.Mock).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    render(<Home />);

    expect(screen.getByRole('status', { hidden: true })).toBeInTheDocument();
  });

  it('handles API errors gracefully', async () => {
    (apiClient.getGraphStats as jest.Mock).mockRejectedValue(
      new Error('API Error')
    );

    render(<Home />);

    await waitFor(() => {
      expect(
        screen.getByText(/Unable to load statistics/i)
      ).toBeInTheDocument();
    });
  });

  it('renders navigation links', () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    render(<Home />);

    expect(screen.getByText('Explore Graph')).toBeInTheDocument();
    expect(screen.getByText('Ask Questions')).toBeInTheDocument();
  });

  it('displays feature cards', () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    render(<Home />);

    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
    expect(screen.getByText('AI Tutor Chat')).toBeInTheDocument();
    expect(screen.getByText('KG-Aware RAG')).toBeInTheDocument();
    expect(screen.getByText('Local-First')).toBeInTheDocument();
  });
});
