import { act, render, screen, fireEvent } from '@testing-library/react';
import cytoscapeModule from 'cytoscape';
import KnowledgeGraph from '@/components/KnowledgeGraph';
import type { GraphData } from '@/lib/types';
import { fakeNode, type CytoscapeMock, type FakeCy } from './helpers/cytoscapeMock';

// Fake Cytoscape: one fake instance per build of the graph (see the helper)
jest.mock('cytoscape', () => require('./helpers/cytoscapeMock').createCytoscapeMock());
jest.mock('cytoscape-cose-bilkent', () => jest.fn());

const cytoscape = cytoscapeModule as unknown as CytoscapeMock;
const mockCyInstances = cytoscape.instances;

/** The Cytoscape instance created by the latest build of the graph. */
const lastCy = (): any => mockCyInstances[mockCyInstances.length - 1];

const tapNode = (cy: FakeCy, node: ReturnType<typeof fakeNode>) =>
  act(() => cy.handlers['tap node']({ target: node }));

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
    mockCyInstances.length = 0;
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

      expect(lastCy().zoom).toHaveBeenCalledWith(1.3);
    });

    it('calls zoom out handler when zoom out button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const zoomOutButton = screen.getByRole('button', { name: /zoom out/i });
      fireEvent.click(zoomOutButton);

      expect(lastCy().zoom).toHaveBeenCalledWith(1 / 1.3);
    });

    it('calls fit handler when fit to view button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const fitButton = screen.getByRole('button', { name: /fit to view/i });
      fireEvent.click(fitButton);

      expect(lastCy().fit).toHaveBeenCalledWith(undefined, 50);
    });

    it('calls reset handler when reset view button is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const resetButton = screen.getByRole('button', { name: /reset view/i });
      fireEvent.click(resetButton);

      expect(lastCy().fit).toHaveBeenCalled();
      expect(lastCy().nodes().removeClass).toHaveBeenCalledWith('selected highlighted faded');
    });
  });

  describe('Node Interaction', () => {
    it('registers tap handlers for nodes and the background', () => {
      render(
        <KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />
      );

      expect(lastCy().on).toHaveBeenCalledWith('tap', 'node', expect.any(Function));
      expect(lastCy().on).toHaveBeenCalledWith('tap', expect.any(Function));
    });

    it('shows a pointer cursor over nodes', () => {
      const { container } = render(<KnowledgeGraph data={mockGraphData} />);
      const canvasContainer = container.querySelector('.cytoscape-container') as HTMLElement;

      lastCy().handlers['mouseover node']({});
      expect(canvasContainer.style.cursor).toBe('pointer');

      lastCy().handlers['mouseout node']({});
      expect(canvasContainer.style.cursor).toBe('');
    });

    it('reports a clicked node and shows its details', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);

      tapNode(lastCy(), fakeNode('concept-1', 'American Revolution', 0.9, 3));

      expect(mockOnNodeClick).toHaveBeenCalledWith('concept-1', 'American Revolution');
      expect(screen.getByText('Selected Concept')).toBeInTheDocument();
      expect(screen.getByText('90%')).toBeInTheDocument();
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('clears the selection when the background is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const cy = lastCy();
      tapNode(cy, fakeNode('concept-1', 'American Revolution', 0.9));

      act(() => cy.handlers.tap({ target: cy }));

      expect(screen.queryByText('Selected Concept')).not.toBeInTheDocument();
    });

    it('keeps the selection when a click on the background hits an element', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const cy = lastCy();
      tapNode(cy, fakeNode('concept-1', 'American Revolution', 0.9));

      act(() => cy.handlers.tap({ target: {} }));

      expect(screen.getByText('Selected Concept')).toBeInTheDocument();
    });

    it('clears the selection with the reset control', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      tapNode(lastCy(), fakeNode('concept-1', 'American Revolution', 0.9));

      fireEvent.click(screen.getByRole('button', { name: /reset view/i }));

      expect(screen.queryByText('Selected Concept')).not.toBeInTheDocument();
    });
  });

  describe('Graph Lifecycle', () => {
    it('keeps the graph and its layout when a node is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);
      const cy = lastCy();

      tapNode(cy, fakeNode('concept-3', 'Constitution', 0.95));

      expect(cytoscape).toHaveBeenCalledTimes(1);
      expect(cy.destroy).not.toHaveBeenCalled();
      expect(screen.getByText('Selected Concept')).toBeInTheDocument();
    });

    it('does not rebuild the graph when the parent passes a new click handler', () => {
      const firstHandler = jest.fn();
      const secondHandler = jest.fn();
      const { rerender } = render(
        <KnowledgeGraph data={mockGraphData} onNodeClick={firstHandler} />
      );
      const cy = lastCy();

      rerender(<KnowledgeGraph data={mockGraphData} onNodeClick={secondHandler} />);
      tapNode(cy, fakeNode('concept-2', 'Declaration of Independence', 0.85));

      expect(cytoscape).toHaveBeenCalledTimes(1);
      expect(cy.destroy).not.toHaveBeenCalled();
      // The graph calls the latest handler
      expect(secondHandler).toHaveBeenCalledWith('concept-2', 'Declaration of Independence');
      expect(firstHandler).not.toHaveBeenCalled();
    });

    it('rebuilds the graph for new data and drops the old selection', () => {
      const { rerender } = render(<KnowledgeGraph data={mockGraphData} />);
      const firstCy = lastCy();
      tapNode(firstCy, fakeNode('concept-1', 'American Revolution', 0.9));

      const newData: GraphData = {
        nodes: [{ data: { id: 'e1', label: 'Supply and Demand', importance: 0.9 } }],
        edges: [],
      };
      rerender(<KnowledgeGraph data={newData} />);

      expect(cytoscape).toHaveBeenCalledTimes(2);
      expect(firstCy.destroy).toHaveBeenCalledTimes(1);
      expect(lastCy().options.elements.nodes).toEqual(newData.nodes);
      expect(screen.queryByText('Selected Concept')).not.toBeInTheDocument();
    });

    it('recolours the nodes for a new theme without rebuilding the graph', () => {
      const { rerender } = render(
        <KnowledgeGraph data={mockGraphData} chapterColors={{ Revolution: '#ff0000' }} />
      );
      const cy = lastCy();

      rerender(<KnowledgeGraph data={mockGraphData} chapterColors={{ Revolution: '#00ff00' }} />);

      expect(cytoscape).toHaveBeenCalledTimes(1);
      expect(cy.styleUpdate).toHaveBeenCalled();
      const nodeStyle = cy.options.style.find((entry: any) => entry.selector === 'node').style;
      const revolutionNode = { data: (key: string) => (key === 'chapter' ? 'Revolution' : 'Boston Tea Party') };
      const otherNode = { data: (key: string) => (key === 'label' ? 'Taxes' : '') };
      expect(nodeStyle['background-color'](revolutionNode)).toBe('#00ff00');
      expect(nodeStyle['background-color'](otherNode)).toBe('#6366f1');
    });

    it('destroys cytoscape instance on unmount', () => {
      const { unmount } = render(<KnowledgeGraph data={mockGraphData} />);

      unmount();

      expect(lastCy().destroy).toHaveBeenCalled();
    });
  });

  describe('Styles', () => {
    const styleOf = (selector: string) =>
      lastCy().options.style.find((entry: any) => entry.selector === selector).style;
    const element = (data: Record<string, unknown>) => ({ data: (key: string) => data[key] });

    it('sizes nodes by importance', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const node = styleOf('node');

      expect(node.width(element({ importance: 1 }))).toBe(70);
      expect(node.height(element({ importance: 0 }))).toBe(47.5); // missing importance = 0.5
    });

    it.each([
      ['PREREQ', '#ef4444'],
      ['COVERS', '#3b82f6'],
      ['RELATED', '#8b5cf6'],
      ['OTHER', '#9ca3af'],
    ])('colours %s edges', (type, color) => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const edge = styleOf('edge');

      expect(edge['line-color'](element({ type }))).toBe(color);
      expect(edge['target-arrow-color'](element({ type }))).toBe(color);
    });
  });

  describe('Highlighted Concepts', () => {
    it('highlights the matching nodes and fits the view to them', () => {
      render(
        <KnowledgeGraph
          data={mockGraphData}
          highlightedConcepts={['american revolution', 'Constitution']}
        />
      );
      const cy = lastCy();

      const matches = cy.nodes().filter.mock.results[0].value;
      expect(matches.length).toBe(2);
      expect(matches.addClass).toHaveBeenCalledWith('highlighted');
      expect(cy.nodes().not).toHaveBeenCalledWith(matches);
      expect(cy.fit).toHaveBeenCalledWith(matches, 80);
    });

    it('re-applies the highlights after the graph is rebuilt', () => {
      const highlights = ['Supply and Demand'];
      const { rerender } = render(
        <KnowledgeGraph data={mockGraphData} highlightedConcepts={highlights} />
      );

      const newData: GraphData = {
        nodes: [{ data: { id: 'e1', label: 'Supply and Demand', importance: 0.9 } }],
        edges: [],
      };
      rerender(<KnowledgeGraph data={newData} highlightedConcepts={highlights} />);

      const cy = lastCy();
      expect(cytoscape).toHaveBeenCalledTimes(2);
      expect(cy.fit).toHaveBeenCalledTimes(1);
      expect(cy.nodes().filter.mock.results[0].value.addClass).toHaveBeenCalledWith('highlighted');
    });

    it('does not re-apply highlights on unrelated re-renders', () => {
      const highlights = ['Constitution'];
      const { rerender } = render(
        <KnowledgeGraph data={mockGraphData} highlightedConcepts={highlights} />
      );

      rerender(
        <KnowledgeGraph data={mockGraphData} highlightedConcepts={highlights} className="wide" />
      );

      expect(lastCy().fit).toHaveBeenCalledTimes(1);
    });

    it('keeps the graph readable when no highlighted concept is on it', () => {
      render(<KnowledgeGraph data={mockGraphData} highlightedConcepts={['Photosynthesis']} />);
      const cy = lastCy();

      expect(cy.nodes().addClass).not.toHaveBeenCalledWith('faded');
      expect(cy.fit).not.toHaveBeenCalled();
    });

    it('handles empty highlightedConcepts array', () => {
      render(
        <KnowledgeGraph data={mockGraphData} highlightedConcepts={[]} />
      );

      expect(lastCy().nodes().removeClass).toHaveBeenCalledWith('highlighted faded');
      expect(lastCy().nodes().filter).not.toHaveBeenCalled();
    });
  });

  describe('Text Alternative', () => {
    it('labels the canvas with the size of the graph', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(
        screen.getByRole('img', { name: 'Knowledge graph with 4 concepts and 3 relationships' })
      ).toBeInTheDocument();
    });

    it('describes the most important concepts and the highlights', () => {
      render(<KnowledgeGraph data={mockGraphData} highlightedConcepts={['Civil War']} />);

      const graph = screen.getByRole('img', { name: /Knowledge graph/ });
      expect(graph).toHaveAccessibleDescription(
        'Most important concepts: Constitution, American Revolution, Civil War, Declaration of Independence. Highlighted concepts: Civil War.'
      );
    });

    it('explains an empty graph', () => {
      render(<KnowledgeGraph data={{ nodes: [], edges: [] }} />);

      expect(screen.getByRole('img', { name: /Knowledge graph/ })).toHaveAccessibleDescription(
        'The graph has no concepts yet.'
      );
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
