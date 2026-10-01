import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import GraphPage from '@/app/graph/page';
import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';

// Mock the API client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getGraphData: jest.fn(),
  },
}));

// Mock SubjectPicker to avoid side effects
jest.mock('@/components/SubjectPicker', () => {
  return function MockSubjectPicker() {
    return <div data-testid="subject-picker">Subject Picker</div>;
  };
});

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
  }),
}));

// Props the (mocked) KnowledgeGraph received on each render
var mockGraphRenders: Array<{ onNodeClick?: unknown; chapterColors?: unknown }>;

// Mock next/dynamic to avoid SSR issues
jest.mock('next/dynamic', () => {
  mockGraphRenders = [];
  return function dynamic() {
    // Return a mock component
    return function MockKnowledgeGraph({ data, onNodeClick, highlightedConcepts, className, chapterColors }: any) {
      mockGraphRenders.push({ onNodeClick, chapterColors });
      return (
        <div data-testid="knowledge-graph" className={className}>
          <div data-testid="graph-nodes">{data?.nodes?.length || 0} nodes</div>
          <div data-testid="graph-edges">{data?.edges?.length || 0} edges</div>
          {highlightedConcepts?.length > 0 && (
            <div data-testid="highlighted-concepts">{highlightedConcepts.join(', ')}</div>
          )}
          <button
            data-testid="mock-node-click"
            onClick={() => onNodeClick?.('node-1', 'Test Concept')}
          >
            Click Node
          </button>
        </div>
      );
    };
  };
});

// Mock Skeleton component
jest.mock('@/components/Skeleton', () => ({
  GraphSkeleton: () => <div data-testid="graph-skeleton">Loading graph...</div>,
}));

// Reset store between tests
const initialStoreState = useAppStore.getState();
const mockGetGraphData = apiClient.getGraphData as jest.Mock;

const mockGraphData = {
  nodes: [
    { data: { id: 'node-1', label: 'Concept 1', importance: 0.8 } },
    { data: { id: 'node-2', label: 'Concept 2', importance: 0.6 } },
    { data: { id: 'node-3', label: 'Concept 3', importance: 0.9 } },
  ],
  edges: [
    { data: { id: 'edge-1', source: 'node-1', target: 'node-2', type: 'PREREQ' } },
    { data: { id: 'edge-2', source: 'node-2', target: 'node-3', type: 'RELATED' } },
  ],
};

/** Render the page and wait until the graph request has settled (skeleton gone). */
async function renderGraphPage() {
  render(<GraphPage />);
  await waitFor(() => {
    expect(screen.queryByTestId('graph-skeleton')).not.toBeInTheDocument();
  });
}

describe('GraphPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGraphRenders.length = 0;
    useAppStore.setState(initialStoreState);
    // mockReset drops queued *Once responses that a previous test did not consume
    mockGetGraphData.mockReset();
    mockGetGraphData.mockResolvedValue(mockGraphData);
  });

  describe('Initial Rendering', () => {
    it('renders the page header', async () => {
      await renderGraphPage();

      expect(screen.getByRole('heading', { level: 1, name: 'Knowledge Graph Visualization' })).toBeInTheDocument();
      expect(screen.getByText(/Explore concepts and their relationships/i)).toBeInTheDocument();
      expect(screen.getByTestId('subject-picker')).toBeInTheDocument();
    });

    it('shows loading skeleton initially', () => {
      mockGetGraphData.mockImplementation(() => new Promise(() => {}));

      render(<GraphPage />);

      expect(screen.getByTestId('graph-skeleton')).toBeInTheDocument();
      expect(screen.queryByText('Graph Stats')).not.toBeInTheDocument();
    });

    it('renders how to use instructions', async () => {
      await renderGraphPage();

      expect(screen.getByText('How to Use')).toBeInTheDocument();
      expect(screen.getByText(/Click nodes to see details/i)).toBeInTheDocument();
      expect(screen.getByText(/Drag to pan, scroll to zoom/i)).toBeInTheDocument();
      expect(screen.getByText(/Node size indicates importance/i)).toBeInTheDocument();
      expect(screen.getByText(/Edge colors show relationship types/i)).toBeInTheDocument();
    });
  });

  describe('Graph Loading', () => {
    it('fetches the graph of the current subject', async () => {
      useAppStore.setState({ currentSubject: 'economics' });

      await renderGraphPage();

      expect(mockGetGraphData).toHaveBeenCalledTimes(1);
      expect(mockGetGraphData).toHaveBeenCalledWith(100, 'economics', {
        signal: expect.any(AbortSignal),
      });
      expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
    });

    it('displays graph stats after loading', async () => {
      await renderGraphPage();

      expect(screen.getByText('Graph Stats')).toBeInTheDocument();
      expect(screen.getByText('Nodes:').nextSibling).toHaveTextContent('3');
      expect(screen.getByText('Edges:').nextSibling).toHaveTextContent('2');
    });

    it('passes the chapter colours of the subject theme', async () => {
      const chapterColors = { Revolution: '#dc2626' };
      useAppStore.setState({
        subjectTheme: {
          subject_id: 'us_history',
          primary_color: '#dc2626',
          secondary_color: '#fca5a5',
          accent_color: '#b91c1c',
          chapter_colors: chapterColors,
        },
      });

      await renderGraphPage();

      expect(mockGraphRenders.at(-1)?.chapterColors).toBe(chapterColors);
    });

    it('loads the new subject graph when the subject changes', async () => {
      await renderGraphPage();
      const economicsGraph = { nodes: [{ data: { id: 'e1', label: 'Supply', importance: 1 } }], edges: [] };
      mockGetGraphData.mockResolvedValueOnce(economicsGraph);

      act(() => useAppStore.getState().setCurrentSubject('economics'));

      await waitFor(() => expect(screen.getByTestId('graph-nodes')).toHaveTextContent('1 nodes'));
      expect(mockGetGraphData).toHaveBeenLastCalledWith(100, 'economics', expect.anything());
    });
  });

  describe('Error Handling', () => {
    it('shows the backend error with a retry action instead of the graph', async () => {
      mockGetGraphData.mockRejectedValueOnce(
        new ApiError('http', 'Database connection failed', { status: 503 })
      );

      await renderGraphPage();

      expect(screen.getByRole('alert')).toHaveTextContent('Unable to load the knowledge graph.');
      expect(screen.getByText('Database connection failed')).toBeInTheDocument();
      expect(screen.queryByTestId('knowledge-graph')).not.toBeInTheDocument();
      expect(screen.queryByText('Graph Stats')).not.toBeInTheDocument();
    });

    it('loads the graph again on retry', async () => {
      mockGetGraphData.mockRejectedValueOnce(new ApiError('network', 'Could not reach the API'));
      await renderGraphPage();

      fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

      expect(await screen.findByTestId('knowledge-graph')).toBeInTheDocument();
      expect(mockGetGraphData).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('shows a generic message for unexpected errors', async () => {
      mockGetGraphData.mockRejectedValueOnce(new TypeError('boom'));

      await renderGraphPage();

      expect(screen.getByText('Something went wrong. Please try again.')).toBeInTheDocument();
    });
  });

  describe('Node Selection', () => {
    it('shows selected concept details when node is clicked', async () => {
      await renderGraphPage();

      fireEvent.click(screen.getByTestId('mock-node-click'));

      expect(screen.getByText('Selected Concept')).toBeInTheDocument();
      expect(screen.getByText('Test Concept')).toBeInTheDocument();
    });

    it('navigates to chat with question when Ask AI Tutor is clicked', async () => {
      await renderGraphPage();
      fireEvent.click(screen.getByTestId('mock-node-click'));

      fireEvent.click(screen.getByText('Ask AI Tutor About This'));

      expect(mockPush).toHaveBeenCalledWith('/chat?question=Explain%20Test%20Concept');
    });

    it('passes the same click handler on every render', async () => {
      await renderGraphPage();

      fireEvent.click(screen.getByTestId('mock-node-click'));
      act(() => useAppStore.getState().setHighlightedConcepts(['Concept 1']));

      const handlers = new Set(mockGraphRenders.map((props) => props.onNodeClick));
      expect(mockGraphRenders.length).toBeGreaterThan(1);
      expect(handlers.size).toBe(1);
    });

    it('does not re-render the graph for unrelated store updates', async () => {
      await renderGraphPage();
      const renders = mockGraphRenders.length;

      act(() => {
        useAppStore.setState({
          masteryMap: {
            A: { conceptName: 'A', masteryLevel: 0.8, attempts: 1, lastAssessed: null },
          },
        });
      });

      expect(mockGraphRenders.length).toBe(renders);
    });

    it('forgets the selected concept when the subject changes', async () => {
      await renderGraphPage();
      fireEvent.click(screen.getByTestId('mock-node-click'));

      act(() => useAppStore.getState().setCurrentSubject('economics'));

      expect(screen.queryByText('Selected Concept')).not.toBeInTheDocument();
      await waitFor(() => expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument());
    });
  });

  describe('Highlighted Concepts', () => {
    it('displays highlighted concepts banner when concepts are highlighted', async () => {
      useAppStore.setState({
        highlightedConcepts: ['Concept A', 'Concept B'],
        lastQuery: 'What is Concept A?',
      });

      await renderGraphPage();

      expect(screen.getByText(/Highlighting 2 concepts/i)).toBeInTheDocument();
      expect(screen.getByText(/from query:/i)).toBeInTheDocument();
    });

    it('clears highlighted concepts when X button is clicked', async () => {
      useAppStore.setState({
        highlightedConcepts: ['Concept A', 'Concept B'],
        lastQuery: 'Test query',
      });

      await renderGraphPage();

      const clearButton = screen.getByRole('button', { name: /clear highlights/i });
      fireEvent.click(clearButton);

      expect(screen.queryByText(/Highlighting/i)).not.toBeInTheDocument();
      expect(useAppStore.getState().highlightedConcepts).toEqual([]);
    });

    it('passes highlighted concepts to KnowledgeGraph component', async () => {
      useAppStore.setState({ highlightedConcepts: ['Concept X', 'Concept Y'] });

      await renderGraphPage();

      expect(screen.getByTestId('highlighted-concepts')).toHaveTextContent('Concept X, Concept Y');
    });
  });

  describe('Empty States', () => {
    it('shows no data message when graph data is null', async () => {
      mockGetGraphData.mockResolvedValueOnce(null);

      await renderGraphPage();

      expect(screen.getByText('No graph data available')).toBeInTheDocument();
    });

    it('explains an empty graph', async () => {
      mockGetGraphData.mockResolvedValueOnce({ nodes: [], edges: [] });

      await renderGraphPage();

      expect(screen.getByText('No graph data available')).toBeInTheDocument();
      expect(
        screen.getByText('This subject has no concepts in the knowledge graph yet.')
      ).toBeInTheDocument();
      expect(screen.queryByTestId('knowledge-graph')).not.toBeInTheDocument();
    });
  });
});
