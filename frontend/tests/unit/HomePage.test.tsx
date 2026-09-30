import { render, screen, waitFor } from '@testing-library/react';
import Home from '@/app/page';
import { apiClient } from '@/lib/api-client';

// Mock the API client (include all methods used by page + SubjectPicker)
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getGraphStats: jest.fn(),
    getTopConceptsForSubject: jest.fn().mockResolvedValue([]),
    getSubjects: jest.fn().mockResolvedValue({
      subjects: [
        { id: 'us_history', name: 'US History', description: 'US History', is_default: true },
      ],
      default_subject: 'us_history',
    }),
  },
}));

// Mock the store. The state object (and its functions) must be stable across renders:
// SubjectPicker re-runs its loading effect whenever these functions change identity.
jest.mock('@/lib/store', () => {
  const state = {
    masteryMap: {},
    getMastery: jest.fn().mockReturnValue(0),
    currentSubject: 'us_history',
    setCurrentSubject: jest.fn(),
    subjectTheme: null,
    loadSubjectTheme: jest.fn(),
    isLoadingTheme: false,
    loadMasteryFromBackend: jest.fn(),
  };
  return {
    useAppStore: Object.assign(
      jest.fn(() => state),
      {
        getState: jest.fn(() => state),
        setState: jest.fn(),
      }
    ),
  };
});

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: any) {
    return <a href={href}>{children}</a>;
  };
});

/** Render the page and let the SubjectPicker, stats and top-concept requests settle. */
async function renderHome() {
  render(<Home />);
  await screen.findByRole('button', { name: /US History/i });
}

describe('Home Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (apiClient.getTopConceptsForSubject as jest.Mock).mockResolvedValue([]);
  });

  it('renders the main heading', async () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    await renderHome();

    expect(screen.getByText('Adaptive Knowledge Graph')).toBeInTheDocument();
  });

  it('displays graph statistics after loading', async () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    await renderHome();

    await waitFor(() => {
      expect(screen.getByText('150')).toBeInTheDocument();
      expect(screen.getByText('42')).toBeInTheDocument();
      expect(screen.getByText('320')).toBeInTheDocument();
    });
  });

  it('shows loading skeleton while fetching stats', async () => {
    (apiClient.getGraphStats as jest.Mock).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    await renderHome();

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

    await renderHome();

    await waitFor(() => {
      expect(
        screen.getByText(/Unable to load statistics/i)
      ).toBeInTheDocument();
    });
  });

  it('renders navigation links', async () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    await renderHome();

    expect(screen.getByText('Explore Graph')).toBeInTheDocument();
    expect(screen.getByText('Ask Questions')).toBeInTheDocument();
    expect(screen.getByText('Demo Status')).toBeInTheDocument();
  });

  it('displays feature cards', async () => {
    (apiClient.getGraphStats as jest.Mock).mockResolvedValue({
      concept_count: 150,
      module_count: 42,
      relationship_count: 320,
    });

    await renderHome();

    expect(screen.getByText('Knowledge Map')).toBeInTheDocument();
    expect(screen.getByText('AI Tutor Chat')).toBeInTheDocument();
    expect(screen.getByText('KG-Aware RAG')).toBeInTheDocument();
    expect(screen.getByText('Local-First')).toBeInTheDocument();
  });
});
