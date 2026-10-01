import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Home from '@/app/page';
import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';

// Mock the API client (all methods used by the page and SubjectPicker)
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getGraphStats: jest.fn(),
    getTopConceptsForSubject: jest.fn(),
    getSubjects: jest.fn(),
  },
}));

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), prefetch: jest.fn(), back: jest.fn() }),
}));

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href, className }: any) {
    return <a href={href} className={className}>{children}</a>;
  };
});

const mockGetGraphStats = apiClient.getGraphStats as jest.Mock;
const mockGetTopConcepts = apiClient.getTopConceptsForSubject as jest.Mock;
const mockGetSubjects = apiClient.getSubjects as jest.Mock;

const initialStoreState = useAppStore.getState();

const stats = { concept_count: 150, module_count: 42, relationship_count: 320 };
const subjects = {
  subjects: [
    { id: 'us_history', name: 'US History', description: 'US History', is_default: true, available: true },
    { id: 'economics', name: 'Economics', description: 'Economics', is_default: false },
    { id: 'biology', name: 'Biology', description: 'Biology', is_default: false, available: false },
  ],
  default_subject: 'us_history',
};

/** Render the page and let the SubjectPicker request settle. */
async function renderHome() {
  render(<Home />);
  await screen.findByRole('button', { name: /US History/i });
}

const statsSection = () => screen.getByRole('region', { name: 'Knowledge Graph Statistics' });

describe('Home Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    mockGetGraphStats.mockResolvedValue(stats);
    mockGetTopConcepts.mockResolvedValue([]);
    mockGetSubjects.mockResolvedValue(subjects);
  });

  it('renders the main heading', async () => {
    await renderHome();

    expect(screen.getByRole('heading', { level: 1, name: 'Adaptive Knowledge Graph' })).toBeInTheDocument();
  });

  it('displays graph statistics for the current subject', async () => {
    useAppStore.setState({ currentSubject: 'economics' });

    render(<Home />);

    const section = statsSection();
    expect(await within(section).findByText('150')).toBeInTheDocument();
    expect(within(section).getByText('Concepts')).toBeInTheDocument();
    expect(within(section).getByText('42')).toBeInTheDocument();
    expect(within(section).getByText('320')).toBeInTheDocument();
    expect(mockGetGraphStats).toHaveBeenCalledWith('economics', { signal: expect.any(AbortSignal) });
  });

  it('shows loading skeleton while fetching stats', async () => {
    mockGetGraphStats.mockImplementation(() => new Promise(() => {}));

    await renderHome();

    expect(screen.getByText('Knowledge Graph Statistics')).toBeInTheDocument();
    expect(screen.queryByText('150')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the backend error instead of zero statistics', async () => {
    mockGetGraphStats.mockRejectedValue(new ApiError('http', 'Database connection failed', { status: 503 }));

    await renderHome();

    const alert = await within(statsSection()).findByRole('alert');
    expect(alert).toHaveTextContent('Unable to load statistics.');
    expect(alert).toHaveTextContent('Database connection failed');
    expect(within(statsSection()).queryByText('0')).not.toBeInTheDocument();
  });

  it('loads the statistics again on retry', async () => {
    mockGetGraphStats.mockRejectedValueOnce(new ApiError('network', 'Could not reach the API'));

    await renderHome();
    fireEvent.click(await within(statsSection()).findByRole('button', { name: 'Retry' }));

    expect(await within(statsSection()).findByText('150')).toBeInTheDocument();
    expect(mockGetGraphStats).toHaveBeenCalledTimes(2);
  });

  it('reloads the statistics when the subject changes', async () => {
    await renderHome();
    await within(statsSection()).findByText('150');
    mockGetGraphStats.mockResolvedValue({ concept_count: 87, module_count: 31, relationship_count: 204 });

    act(() => useAppStore.getState().setCurrentSubject('economics'));

    expect(await within(statsSection()).findByText('87')).toBeInTheDocument();
    expect(mockGetGraphStats).toHaveBeenLastCalledWith('economics', expect.anything());
  });

  describe('Start Learning', () => {
    it('suggests the top concepts of the subject', async () => {
      mockGetTopConcepts.mockResolvedValue([
        { name: 'American Revolution', score: 0.95 },
        { name: 'Constitution', score: 0.9 },
      ]);

      await renderHome();

      expect(await screen.findByRole('heading', { name: 'Start Learning' })).toBeInTheDocument();
      expect(mockGetTopConcepts).toHaveBeenCalledWith(6, 'us_history', expect.anything());

      fireEvent.click(screen.getByRole('button', { name: /American Revolution/ }));
      expect(mockPush).toHaveBeenCalledWith('/chat?question=Explain%20American%20Revolution');
    });

    it('is hidden when there are no suggestions', async () => {
      await renderHome();
      await waitFor(() => expect(mockGetTopConcepts).toHaveBeenCalled());

      expect(screen.queryByRole('heading', { name: 'Start Learning' })).not.toBeInTheDocument();
    });

    it('shows a failed request with a retry action', async () => {
      mockGetTopConcepts
        .mockRejectedValueOnce(new ApiError('http', 'An internal error occurred', { status: 500 }))
        .mockResolvedValueOnce([{ name: 'Civil War', score: 0.9 }]);

      await renderHome();
      const section = await screen.findByRole('region', { name: 'Start Learning' });
      expect(within(section).getByRole('alert')).toHaveTextContent(
        'Unable to load suggested concepts.An internal error occurred'
      );

      fireEvent.click(within(section).getByRole('button', { name: 'Retry' }));

      expect(await screen.findByRole('button', { name: /Civil War/ })).toBeInTheDocument();
    });
  });

  describe('Learning progress', () => {
    it('invites a new learner to start', async () => {
      await renderHome();

      expect(screen.getByRole('heading', { name: 'Start Your Learning Journey' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Take Assessment' })).toHaveAttribute('href', '/assessment');
    });

    it('links each tracked concept to the tutor', async () => {
      useAppStore.setState({
        masteryMap: {
          'Stamp Act': { conceptName: 'Stamp Act', masteryLevel: 0.8, attempts: 2, lastAssessed: null },
        },
      });

      await renderHome();

      expect(screen.getByRole('link', { name: 'Stamp Act 80%' })).toHaveAttribute(
        'href',
        '/chat?question=Explain%20Stamp%20Act'
      );
    });
  });

  it('renders the calls to action', async () => {
    await renderHome();

    expect(screen.getByRole('link', { name: 'Explore Graph' })).toHaveAttribute('href', '/graph');
    expect(screen.getByRole('link', { name: 'Ask Questions' })).toHaveAttribute('href', '/chat');
  });

  it('displays feature cards', async () => {
    await renderHome();

    for (const feature of ['Knowledge Map', 'AI Tutor Chat', 'KG-Aware RAG', 'Local-First', 'Assessment']) {
      expect(screen.getByRole('heading', { level: 4, name: feature })).toBeInTheDocument();
    }
  });

  it('attributes the content of the available subjects', async () => {
    await renderHome();

    expect(
      await screen.findByText(/open textbooks \(US History, Economics\)/)
    ).toBeInTheDocument();
  });

  it('keeps a generic attribution when the subjects cannot be loaded', async () => {
    mockGetSubjects.mockRejectedValue(new ApiError('network', 'Could not reach the API'));

    render(<Home />);

    expect(await screen.findByText("Couldn't load subjects")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'OpenStax' }).parentElement).toHaveTextContent(
      /^Content adapted from OpenStax open textbooks$/
    );
  });
});
