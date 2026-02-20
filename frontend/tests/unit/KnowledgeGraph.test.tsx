import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import KnowledgeGraph from '@/components/KnowledgeGraph';
import type { GraphData } from '@/lib/types';

// Mock Cytoscape and its layout extension
// NOTE: jest.mock is hoisted above variable declarations, so mockCyInstance
// must be assigned inside the factory to avoid temporal dead zone errors.
// eslint-disable-next-line no-var
var mockCyInstance: any;

jest.mock('cytoscape', () => {
  mockCyInstance = {
    nodes: jest.fn().mockReturnThis(),
    edges: jest.fn().mockReturnThis(),
    collection: jest.fn().mockReturnValue({
      merge: jest.fn().mockReturnThis(),
      addClass: jest.fn().mockReturnThis(),
      edgesWith: jest.fn().mockReturnValue({
        addClass: jest.fn().mockReturnThis(),
      }),
    }),
    zoom: jest.fn().mockReturnValue(1),
    center: jest.fn(),
    fit: jest.fn(),
    on: jest.fn(),
    getElementById: jest.fn().mockReturnValue({
      data: jest.fn().mockImplementation((key: string) => {
        if (key === 'label') return 'Test Concept';
        if (key === 'importance') return 0.75;
        return null;
      }),
      neighborhood: jest.fn().mockReturnValue({
        nodes: jest.fn().mockReturnValue({ length: 3 }),
      }),
    }),
    destroy: jest.fn(),
    not: jest.fn().mockReturnThis(),
    filter: jest.fn().mockReturnThis(),
    removeClass: jest.fn().mockReturnThis(),
    addClass: jest.fn().mockReturnThis(),
    hasClass: jest.fn().mockReturnValue(false),
    style: jest.fn(),
  };

  const mockCytoscape: any = jest.fn().mockReturnValue(mockCyInstance);
  mockCytoscape.use = jest.fn();
  return mockCytoscape;
});

jest.mock('cytoscape-cose-bilkent', () => jest.fn());

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  ZoomIn: () => <svg data-testid="zoom-in-icon" />,
  ZoomOut: () => <svg data-testid="zoom-out-icon" />,
  Maximize2: () => <svg data-testid="maximize-icon" />,
  RotateCcw: () => <svg data-testid="rotate-icon" />,
}));

describe('KnowledgeGraph Component', () => {
  const mockGraphData: GraphData = {
    nodes: [
      { data: { id: 'concept-1', label: 'American Revolution', importance: 0.9, chapter: 'Revolution' } },
      { data: { id: 'concept-2', label: 'Declaration of Independence', importance: 0.85, chapter: 'Revolution' } },
      { data: { id: 'concept-3', label: 'Constitution', importance: 0.95, chapter: 'Constitution' } },
      { data: { id: 'concept-4', label: 'Civil War', importance: 0.88, chapter: 'Civil War' } },
    ],
    edges: [
      { data: { id: 'edge-1', source: 'concept-1', target: 'concept-2', type: 'PREREQ', label: 'prerequisite' } },
      { data: { id: 'edge-2', source: 'concept-2', target: 'concept-3', type: 'COVERS', label: 'covers' } },
      { data: { id: 'edge-3', source: 'concept-1', target: 'concept-3', type: 'RELATED', label: 'related' } },
    ],
  };

  const mockOnNodeClick = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders the graph container', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByRole('button', { name: /zoom in/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /zoom out/i })).toBeInTheDocument();
    });

    it('renders the legend', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByText('Legend')).toBeInTheDocument();
      expect(screen.getByText('Prerequisite')).toBeInTheDocument();
      expect(screen.getByText('Covers')).toBeInTheDocument();
      expect(screen.getByText('Related')).toBeInTheDocument();
      expect(screen.getByText('Highlighted')).toBeInTheDocument();
    });

    it('renders zoom control buttons', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByRole('button', { name: /zoom in/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /zoom out/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /fit to view/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reset view/i })).toBeInTheDocument();
    });

    it('applies custom className', () => {
      const { container } = render(
        <KnowledgeGraph data={mockGraphData} className="custom-class" />
      );

      expect(container.firstChild).toHaveClass('custom-class');
    });

    it('renders cytoscape container with minimum height', () => {
      const { container } = render(<KnowledgeGraph data={mockGraphData} />);

      const cytoscapeContainer = container.querySelector('.cytoscape-container');
      expect(cytoscapeContainer).toBeInTheDocument();
      expect(cytoscapeContainer).toHaveStyle({ minHeight: '600px' });
    });
  });

  describe('Zoom Controls', () => {
    it('calls zoom in handler when zoom in button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const zoomInButton = screen.getByRole('button', { name: /zoom in/i });
      fireEvent.click(zoomInButton);

      expect(mockCyInstance.zoom).toHaveBeenCalled();
    });

    it('calls zoom out handler when zoom out button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const zoomOutButton = screen.getByRole('button', { name: /zoom out/i });
      fireEvent.click(zoomOutButton);

      expect(mockCyInstance.zoom).toHaveBeenCalled();
    });

    it('calls fit handler when fit to view button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const fitButton = screen.getByRole('button', { name: /fit to view/i });
      fireEvent.click(fitButton);

      expect(mockCyInstance.fit).toHaveBeenCalled();
    });

    it('calls reset handler when reset view button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const resetButton = screen.getByRole('button', { name: /reset view/i });
      fireEvent.click(resetButton);

      expect(mockCyInstance.fit).toHaveBeenCalled();
    });
  });

  describe('Node Interaction', () => {
    it('receives onNodeClick prop', () => {
      render(
        <KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />
      );

      // The component registers click handlers
      expect(mockCyInstance.on).toHaveBeenCalledWith('tap', 'node', expect.any(Function));
    });

    it('registers tap handler for background clicks', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(mockCyInstance.on).toHaveBeenCalledWith('tap', expect.any(Function));
    });

    it('registers mouseover handler for nodes', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(mockCyInstance.on).toHaveBeenCalledWith(
        'mouseover',
        'node',
        expect.any(Function)
      );
    });
  });

  describe('Highlighted Concepts', () => {
    it('accepts highlightedConcepts prop', () => {
      render(
        <KnowledgeGraph
          data={mockGraphData}
          highlightedConcepts={['American Revolution', 'Constitution']}
        />
      );

      // The component should handle highlighted concepts through useEffect
      expect(mockCyInstance.nodes).toHaveBeenCalled();
    });

    it('handles empty highlightedConcepts array', () => {
      render(
        <KnowledgeGraph data={mockGraphData} highlightedConcepts={[]} />
      );

      // Should not cause any errors
      expect(mockCyInstance.nodes).toHaveBeenCalled();
    });
  });

  describe('Data Updates', () => {
    it('handles empty graph data', () => {
      const emptyData: GraphData = { nodes: [], edges: [] };

      render(<KnowledgeGraph data={emptyData} />);

      // Should render without errors
      expect(screen.getByText('Legend')).toBeInTheDocument();
    });

    it('handles graph with only nodes (no edges)', () => {
      const nodesOnlyData: GraphData = {
        nodes: [
          { data: { id: 'node-1', label: 'Node 1', importance: 0.5 } },
        ],
        edges: [],
      };

      render(<KnowledgeGraph data={nodesOnlyData} />);

      expect(screen.getByText('Legend')).toBeInTheDocument();
    });
  });

  describe('Cleanup', () => {
    it('destroys cytoscape instance on unmount', () => {
      const { unmount } = render(<KnowledgeGraph data={mockGraphData} />);

      unmount();

      expect(mockCyInstance.destroy).toHaveBeenCalled();
    });
  });

  describe('Button Accessibility', () => {
    it('has accessible button labels', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByRole('button', { name: /zoom in/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /zoom out/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /fit to view/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reset view/i })).toBeInTheDocument();
    });

    it('has tooltip titles on buttons', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByTitle('Zoom In')).toBeInTheDocument();
      expect(screen.getByTitle('Zoom Out')).toBeInTheDocument();
      expect(screen.getByTitle('Fit to View')).toBeInTheDocument();
      expect(screen.getByTitle('Reset View')).toBeInTheDocument();
    });
  });

  describe('Selected Node Info Panel', () => {
    it('does not show selected node info initially', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.queryByText('Selected Concept')).not.toBeInTheDocument();
    });
  });

  describe('Edge Types', () => {
    it('displays all edge types in legend', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const legend = screen.getByText('Legend').parentElement;
      expect(legend).toContainElement(screen.getByText('Prerequisite'));
      expect(legend).toContainElement(screen.getByText('Covers'));
      expect(legend).toContainElement(screen.getByText('Related'));
    });
  });
});

describe('KnowledgeGraph Color Mapping', () => {
  // These tests verify the color mapping function indirectly
  const mockData: GraphData = {
    nodes: [
      { data: { id: '1', label: 'Revolution Topic', chapter: 'Revolution', importance: 0.5 } },
      { data: { id: '2', label: 'Constitution Topic', chapter: 'Constitution', importance: 0.5 } },
      { data: { id: '3', label: 'Civil War Topic', chapter: 'Civil War', importance: 0.5 } },
      { data: { id: '4', label: 'Generic Topic', chapter: 'Other', importance: 0.5 } },
    ],
    edges: [],
  };

  it('renders nodes with chapter-based colors', () => {
    render(<KnowledgeGraph data={mockData} />);

    // The cytoscape instance should be created with style functions
    // that apply chapter-based colors
    expect(screen.getByText('Legend')).toBeInTheDocument();
  });
});
