import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import GraphPage from '@/app/graph/page';
import { apiClient } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';

// Mock the API client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getGraphData: jest.fn(),
    getSubjects: jest.fn().mockResolvedValue({
      subjects: [],
      default_subject: 'us_history',
    }),
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

// Mock next/dynamic to avoid SSR issues
jest.mock('next/dynamic', () => {
  return function dynamic(importFn: any, options: any) {
    // Return a mock component
    return function MockKnowledgeGraph({ data, onNodeClick, highlightedConcepts, className }: any) {
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

describe('GraphPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    (apiClient.getGraphData as jest.Mock).mockResolvedValue(mockGraphData);
  });

  describe('Initial Rendering', () => {
    it('renders the page header', async () => {
      render(<GraphPage />);

      expect(screen.getByText('Knowledge Graph Visualization')).toBeInTheDocument();
      expect(screen.getByText(/Explore concepts and their relationships/i)).toBeInTheDocument();
    });

    it('renders back button', async () => {
      render(<GraphPage />);

      expect(screen.getByRole('button', { name: /back to home/i })).toBeInTheDocument();
    });

    it('shows loading skeleton initially', () => {
      (apiClient.getGraphData as jest.Mock).mockImplementation(
        () => new Promise(() => {})
      );

      render(<GraphPage />);

      expect(screen.getByTestId('graph-skeleton')).toBeInTheDocument();
    });

    it('renders how to use instructions', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText('How to Use')).toBeInTheDocument();
      });

      expect(screen.getByText(/Click nodes to see details/i)).toBeInTheDocument();
      expect(screen.getByText(/Drag to pan, scroll to zoom/i)).toBeInTheDocument();
      expect(screen.getByText(/Node size indicates importance/i)).toBeInTheDocument();
      expect(screen.getByText(/Edge colors show relationship types/i)).toBeInTheDocument();
    });
  });

  describe('Graph Loading', () => {
    it('fetches graph data on mount', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(apiClient.getGraphData).toHaveBeenCalledTimes(1);
      });
    });

    it('displays graph after loading', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
      });
    });

    it('displays graph stats after loading', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText('Graph Stats')).toBeInTheDocument();
        expect(screen.getByText('Nodes:')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('Edges:')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays error message when API fails', async () => {
      (apiClient.getGraphData as jest.Mock)
        .mockRejectedValueOnce(new Error('Server error'))
        .mockResolvedValueOnce(mockGraphData); // For fallback

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText(/Failed to load graph data/i)).toBeInTheDocument();
      });
    });

    it('shows demo data when API fails', async () => {
      (apiClient.getGraphData as jest.Mock)
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(mockGraphData);

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
      });
    });
  });

  describe('Navigation', () => {
    it('navigates back to home when back button is clicked', async () => {
      render(<GraphPage />);

      const backButton = screen.getByRole('button', { name: /back to home/i });
      fireEvent.click(backButton);

      expect(mockPush).toHaveBeenCalledWith('/');
    });
  });

  describe('Node Selection', () => {
    it('shows selected concept details when node is clicked', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
      });

      const mockNodeClick = screen.getByTestId('mock-node-click');
      fireEvent.click(mockNodeClick);

      await waitFor(() => {
        expect(screen.getByText('Selected Concept')).toBeInTheDocument();
        expect(screen.getByText('Test Concept')).toBeInTheDocument();
      });
    });

    it('shows Ask AI Tutor button when concept is selected', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('mock-node-click'));

      await waitFor(() => {
        expect(screen.getByText('Ask AI Tutor About This')).toBeInTheDocument();
      });
    });

    it('navigates to chat with question when Ask AI Tutor is clicked', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('mock-node-click'));

      await waitFor(() => {
        expect(screen.getByText('Ask AI Tutor About This')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Ask AI Tutor About This'));

      expect(mockPush).toHaveBeenCalledWith('/chat?question=Explain%20Test%20Concept');
    });
  });

  describe('Highlighted Concepts', () => {
    it('displays highlighted concepts banner when concepts are highlighted', async () => {
      useAppStore.setState({
        ...initialStoreState,
        highlightedConcepts: ['Concept A', 'Concept B'],
        lastQuery: 'What is Concept A?',
      });

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText(/Highlighting 2 concepts/i)).toBeInTheDocument();
      });
    });

    it('shows query context in highlighted banner', async () => {
      useAppStore.setState({
        ...initialStoreState,
        highlightedConcepts: ['Concept A'],
        lastQuery: 'What is the American Revolution?',
      });

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText(/from query:/i)).toBeInTheDocument();
      });
    });

    it('shows clear highlights button', async () => {
      useAppStore.setState({
        ...initialStoreState,
        highlightedConcepts: ['Concept A'],
        lastQuery: 'Test query',
      });

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /clear highlights/i })).toBeInTheDocument();
      });
    });

    it('clears highlighted concepts when X button is clicked', async () => {
      useAppStore.setState({
        ...initialStoreState,
        highlightedConcepts: ['Concept A', 'Concept B'],
        lastQuery: 'Test query',
      });

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText(/Highlighting 2 concepts/i)).toBeInTheDocument();
      });

      const clearButton = screen.getByRole('button', { name: /clear highlights/i });
      fireEvent.click(clearButton);

      await waitFor(() => {
        expect(screen.queryByText(/Highlighting/i)).not.toBeInTheDocument();
      });

      const state = useAppStore.getState();
      expect(state.highlightedConcepts).toEqual([]);
    });

    it('passes highlighted concepts to KnowledgeGraph component', async () => {
      useAppStore.setState({
        ...initialStoreState,
        highlightedConcepts: ['Concept X', 'Concept Y'],
      });

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByTestId('highlighted-concepts')).toHaveTextContent('Concept X, Concept Y');
      });
    });
  });

  describe('Empty States', () => {
    it('shows no data message when graph data is null', async () => {
      (apiClient.getGraphData as jest.Mock).mockResolvedValueOnce(null);

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText('No graph data available')).toBeInTheDocument();
      });
    });
  });

  describe('Graph Stats', () => {
    it('does not show stats when graph data is not loaded', () => {
      (apiClient.getGraphData as jest.Mock).mockImplementation(
        () => new Promise(() => {})
      );

      render(<GraphPage />);

      expect(screen.queryByText('Graph Stats')).not.toBeInTheDocument();
    });

    it('updates stats when graph data changes', async () => {
      const largerGraphData = {
        nodes: Array(10).fill(null).map((_, i) => ({
          data: { id: `node-${i}`, label: `Concept ${i}`, importance: 0.5 },
        })),
        edges: Array(15).fill(null).map((_, i) => ({
          data: { id: `edge-${i}`, source: 'node-0', target: `node-${(i % 9) + 1}`, type: 'RELATED' },
        })),
      };

      (apiClient.getGraphData as jest.Mock).mockResolvedValueOnce(largerGraphData);

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.getByText('10')).toBeInTheDocument(); // Nodes
        expect(screen.getByText('15')).toBeInTheDocument(); // Edges
      });
    });
  });

  describe('Accessibility', () => {
    it('has accessible back button', async () => {
      render(<GraphPage />);

      const backButton = screen.getByRole('button', { name: /back to home/i });
      expect(backButton).toHaveAttribute('aria-label', 'Back to home');
    });

    it('has accessible clear highlights button', async () => {
      useAppStore.setState({
        ...initialStoreState,
        highlightedConcepts: ['Test'],
      });

      render(<GraphPage />);

      await waitFor(() => {
        const clearButton = screen.getByRole('button', { name: /clear highlights/i });
        expect(clearButton).toHaveAttribute('aria-label', 'Clear highlights');
      });
    });
  });

  describe('Loading States', () => {
    it('shows skeleton while loading', () => {
      (apiClient.getGraphData as jest.Mock).mockImplementation(
        () => new Promise(() => {})
      );

      render(<GraphPage />);

      expect(screen.getByTestId('graph-skeleton')).toBeInTheDocument();
    });

    it('hides skeleton after loading completes', async () => {
      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.queryByTestId('graph-skeleton')).not.toBeInTheDocument();
      });
    });

    it('hides skeleton even when error occurs', async () => {
      (apiClient.getGraphData as jest.Mock)
        .mockRejectedValueOnce(new Error('Error'))
        .mockResolvedValueOnce(mockGraphData);

      render(<GraphPage />);

      await waitFor(() => {
        expect(screen.queryByTestId('graph-skeleton')).not.toBeInTheDocument();
      });
    });
  });
});
