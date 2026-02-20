import { render, screen, waitFor } from '@testing-library/react';
import Home from '@/app/page';
import { apiClient } from '@/lib/api-client';

// Mock the API client (include all methods used by page + SubjectPicker)
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getGraphStats: jest.fn(),
    getSubjects: jest.fn().mockResolvedValue({
      subjects: [
        { id: 'us_history', name: 'US History', description: 'US History', is_default: true },
      ],
      default_subject: 'us_history',
    }),
  },
}));

// Mock the store
jest.mock('@/lib/store', () => ({
  useAppStore: Object.assign(
    jest.fn(() => ({
      masteryMap: {},
      getMastery: jest.fn().mockReturnValue(0),
      currentSubject: 'us_history',
      setCurrentSubject: jest.fn(),
      subjectTheme: null,
      loadSubjectTheme: jest.fn(),
      isLoadingTheme: false,
      loadMasteryFromBackend: jest.fn(),
    })),
    {
      getState: jest.fn(() => ({})),
      setState: jest.fn(),
    }
  ),
}));

// Mock next/link
jest.mock('next/link', () => {
  return ({ children, href }: any) => {
    return <a href={href}>{children}</a>;
  };
});

// Mock global fetch for the /api/v1/concepts/top call
beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ concepts: [] }),
  }) as jest.Mock;
});

describe('Home Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Re-set the fetch mock after clearAllMocks
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ concepts: [] }),
    }) as jest.Mock;
  });

  it('renders the main heading', () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    render(<Home />);

    expect(screen.getByText('Adaptive Certifications')).toBeInTheDocument();
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

  it('shows loading skeleton while fetching stats', () => {
    (apiClient.getGraphStats as jest.Mock).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    render(<Home />);

    // The StatsSkeleton renders a grid of animated placeholder cards
    // Verify the skeleton is shown by checking for the stats section heading
    // while the stat values are NOT yet present
    expect(screen.getByText('Knowledge Graph Statistics')).toBeInTheDocument();
    expect(screen.queryByText('150')).not.toBeInTheDocument();
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

    expect(screen.getByText('Knowledge Map')).toBeInTheDocument();
    expect(screen.getByText('AI Tutor Chat')).toBeInTheDocument();
    expect(screen.getByText('KG-Aware RAG')).toBeInTheDocument();
    expect(screen.getByText('Local-First')).toBeInTheDocument();
  });
});
