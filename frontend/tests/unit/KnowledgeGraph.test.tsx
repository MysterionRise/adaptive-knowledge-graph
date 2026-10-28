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

/**
 * Type `query` into the concept search box and submit the form. The search input offers the
 * concept names in a datalist, which makes it a combobox (HTML-AAM), not a searchbox.
 */
const searchFor = (query: string) => {
  fireEvent.change(screen.getByRole('combobox', { name: 'Find a concept' }), {
    target: { value: query },
  });
  fireEvent.submit(screen.getByRole('search'));
};

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  ZoomIn: () => <svg data-testid="zoom-in-icon" />,
  ZoomOut: () => <svg data-testid="zoom-out-icon" />,
  Maximize2: () => <svg data-testid="maximize-icon" />,
  RotateCcw: () => <svg data-testid="rotate-icon" />,
  Search: () => <svg data-testid="search-icon" />,
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
  const mockOnBackgroundClick = jest.fn();

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
      expect(screen.getByText('Selected')).toBeInTheDocument();
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

    it('fills the height of its container', () => {
      const { container } = render(<KnowledgeGraph data={mockGraphData} />);

      const cytoscapeContainer = container.querySelector('.cytoscape-container');
      expect(cytoscapeContainer).toBeInTheDocument();
      expect(cytoscapeContainer).toHaveClass('h-full', 'w-full');
      expect(cytoscapeContainer).not.toHaveAttribute('style');
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

    it('reports a clicked node with its details', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);

      tapNode(lastCy(), fakeNode('concept-1', 'American Revolution', 0.9, 3));

      expect(mockOnNodeClick).toHaveBeenCalledWith('concept-1', 'American Revolution', {
        importance: 0.9,
        connections: 3,
      });
    });

    it('selects a clicked node and fades the rest of the graph', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const cy = lastCy();
      const node = fakeNode('concept-1', 'American Revolution', 0.9, 3);

      tapNode(cy, node);

      expect(cy.nodes().removeClass).toHaveBeenCalledWith('selected highlighted faded');
      expect(node.addClass).toHaveBeenCalledWith('selected');
      expect(cy.nodes().not).toHaveBeenCalledWith(node);
      expect(cy.nodes().addClass).toHaveBeenCalledWith('faded');
      expect(cy.edges().addClass).toHaveBeenCalledWith('faded');
    });

    it('reports a click on the background', () => {
      render(<KnowledgeGraph data={mockGraphData} onBackgroundClick={mockOnBackgroundClick} />);
      const cy = lastCy();
      tapNode(cy, fakeNode('concept-1', 'American Revolution', 0.9));

      act(() => cy.handlers.tap({ target: cy }));

      expect(mockOnBackgroundClick).toHaveBeenCalledTimes(1);
      expect(cy.nodes().removeClass).toHaveBeenLastCalledWith('selected highlighted faded');
    });

    it('ignores a background click that hits an element', () => {
      render(<KnowledgeGraph data={mockGraphData} onBackgroundClick={mockOnBackgroundClick} />);
      const cy = lastCy();
      tapNode(cy, fakeNode('concept-1', 'American Revolution', 0.9));

      act(() => cy.handlers.tap({ target: {} }));

      expect(mockOnBackgroundClick).not.toHaveBeenCalled();
    });

    it('reports the reset control as a background click', () => {
      render(<KnowledgeGraph data={mockGraphData} onBackgroundClick={mockOnBackgroundClick} />);
      tapNode(lastCy(), fakeNode('concept-1', 'American Revolution', 0.9));

      fireEvent.click(screen.getByRole('button', { name: /reset view/i }));

      expect(mockOnBackgroundClick).toHaveBeenCalledTimes(1);
    });

    it('shows the label of an edge while the pointer is over it', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const edge = { addClass: jest.fn(), removeClass: jest.fn() };

      lastCy().handlers['mouseover edge']({ target: edge });
      expect(edge.addClass).toHaveBeenCalledWith('hover');

      lastCy().handlers['mouseout edge']({ target: edge });
      expect(edge.removeClass).toHaveBeenCalledWith('hover');
    });
  });

  describe('Graph Lifecycle', () => {
    it('keeps the graph and its layout when a node is clicked', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);
      const cy = lastCy();

      tapNode(cy, fakeNode('concept-3', 'Constitution', 0.95));

      expect(cytoscape).toHaveBeenCalledTimes(1);
      expect(cy.destroy).not.toHaveBeenCalled();
      expect(mockOnNodeClick).toHaveBeenCalledTimes(1);
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
      expect(secondHandler).toHaveBeenCalledWith('concept-2', 'Declaration of Independence', {
        importance: 0.85,
        connections: 2,
      });
      expect(firstHandler).not.toHaveBeenCalled();
    });

    it('rebuilds the graph for new data', () => {
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

    it('wraps node labels under the node', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const node = styleOf('node');

      expect(node['text-wrap']).toBe('wrap');
      expect(node['text-max-width']).toBe('96px');
      expect(node['text-valign']).toBe('bottom');
    });

    it('reserves room for the labels in the layout', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(lastCy().options.layout).toMatchObject({
        name: 'cose-bilkent',
        nodeDimensionsIncludeLabels: true,
      });
    });

    it('shows edge labels only on hover or selection', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(styleOf('edge')).not.toHaveProperty('label');
      expect(styleOf('edge.hover').label).toBe('data(label)');
      expect(styleOf('edge.highlighted').label).toBe('data(label)');
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

  describe('Concept Search', () => {
    it('offers every concept name as a suggestion', () => {
      const { container } = render(<KnowledgeGraph data={mockGraphData} />);

      const input = screen.getByRole('combobox', { name: 'Find a concept' });
      const datalist = container.querySelector(`datalist`) as HTMLDataListElement;
      expect(input).toHaveAttribute('list', datalist.id);
      expect(Array.from(datalist.options).map((option) => option.value)).toEqual([
        'American Revolution',
        'Declaration of Independence',
        'Constitution',
        'Civil War',
      ]);
    });

    it('selects the concept with the searched name and zooms to it', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);
      const cy = lastCy();
      const node = fakeNode('concept-3', 'Constitution', 0.95, 2);
      cy.getElementById.mockReturnValue(node);

      searchFor('constitution');

      expect(cy.getElementById).toHaveBeenCalledWith('concept-3');
      expect(node.addClass).toHaveBeenCalledWith('selected');
      expect(cy.animate).toHaveBeenCalledWith(
        { center: { eles: node }, zoom: 1.5 },
        { duration: 300 }
      );
      expect(mockOnNodeClick).toHaveBeenCalledWith('concept-3', 'Constitution', {
        importance: 0.95,
        connections: 2,
      });
      expect(screen.getByRole('status')).toHaveTextContent('');
    });

    it('submits the search with the find button', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);
      const cy = lastCy();
      cy.getElementById.mockReturnValue(fakeNode('concept-4', 'Civil War', 0.88));

      fireEvent.change(screen.getByRole('combobox', { name: 'Find a concept' }), {
        target: { value: 'Civil War' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Find concept' }));

      expect(cy.getElementById).toHaveBeenCalledWith('concept-4');
      expect(mockOnNodeClick).toHaveBeenCalledTimes(1);
    });

    it('keeps the current zoom when it is closer than the search zoom', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      const cy = lastCy();
      cy.zoom.mockReturnValue(2);
      cy.getElementById.mockReturnValue(fakeNode('concept-3', 'Constitution', 0.95));

      searchFor('Constitution');

      expect(cy.animate).toHaveBeenCalledWith(expect.objectContaining({ zoom: 2 }), {
        duration: 300,
      });
    });

    it('finds a concept by part of its name', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);
      const cy = lastCy();
      cy.getElementById.mockReturnValue(fakeNode('concept-2', 'Declaration of Independence', 0.85));

      searchFor('declaration');

      expect(cy.getElementById).toHaveBeenCalledWith('concept-2');
      expect(mockOnNodeClick).toHaveBeenCalledWith(
        'concept-2',
        'Declaration of Independence',
        expect.anything()
      );
    });

    it('prefers the concept whose whole name matches', () => {
      const data: GraphData = {
        nodes: [
          { data: { id: 'a', label: 'American Revolution', importance: 0.9 } },
          { data: { id: 'b', label: 'Revolution', importance: 0.5 } },
        ],
        edges: [],
      };
      render(<KnowledgeGraph data={data} />);
      const cy = lastCy();
      cy.getElementById.mockReturnValue(fakeNode('b', 'Revolution', 0.5));

      searchFor('revolution');

      expect(cy.getElementById).toHaveBeenCalledWith('b');
    });

    it('reports when no concept matches', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);
      const cy = lastCy();

      searchFor('Photosynthesis');

      expect(screen.getByRole('status')).toHaveTextContent('No concept matches “Photosynthesis”');
      expect(cy.getElementById).not.toHaveBeenCalled();
      expect(cy.animate).not.toHaveBeenCalled();
      expect(mockOnNodeClick).not.toHaveBeenCalled();
    });

    it('clears the search message with the reset control', () => {
      render(<KnowledgeGraph data={mockGraphData} />);
      searchFor('Photosynthesis');

      fireEvent.click(screen.getByRole('button', { name: /reset view/i }));

      expect(screen.getByRole('status')).toHaveTextContent('');
    });

    it('ignores an empty search', () => {
      render(<KnowledgeGraph data={mockGraphData} onNodeClick={mockOnNodeClick} />);

      searchFor('   ');

      expect(lastCy().getElementById).not.toHaveBeenCalled();
      expect(screen.getByRole('status')).toHaveTextContent('');
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
      expect(screen.getByRole('button', { name: 'Find concept' })).toBeInTheDocument();
    });

    it('has tooltip titles on buttons', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByTitle('Zoom In')).toBeInTheDocument();
      expect(screen.getByTitle('Zoom Out')).toBeInTheDocument();
      expect(screen.getByTitle('Fit to View')).toBeInTheDocument();
      expect(screen.getByTitle('Reset View')).toBeInTheDocument();
    });
  });

  describe('Edge Types', () => {
    it('displays edge types present in graph data', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      const legend = screen.getByText('Legend').parentElement;
      expect(legend).toContainElement(screen.getByText('Prerequisite'));
      expect(legend).toContainElement(screen.getByText('Covers'));
      expect(legend).toContainElement(screen.getByText('Related'));
    });

    it('does not display Covers when graph data has no COVERS edges', () => {
      const graphDataWithoutCovers = {
        ...mockGraphData,
        edges: mockGraphData.edges.filter((edge) => edge.data.type !== 'COVERS'),
      };
      render(<KnowledgeGraph data={graphDataWithoutCovers} />);

      expect(screen.queryByText('Covers')).not.toBeInTheDocument();
    });

    it('does not display Related when graph data has no RELATED edges', () => {
      const graphDataWithoutRelated = {
        ...mockGraphData,
        edges: mockGraphData.edges.filter((edge) => edge.data.type !== 'RELATED'),
      };
      render(<KnowledgeGraph data={graphDataWithoutRelated} />);

      expect(screen.queryByText('Related')).not.toBeInTheDocument();
      expect(screen.getByText('Prerequisite')).toBeInTheDocument();
      expect(screen.getByText('Covers')).toBeInTheDocument();
    });

    it('always explains the highlighted and selected node colours', () => {
      render(<KnowledgeGraph data={{ nodes: [], edges: [] }} />);

      expect(screen.queryByText('Prerequisite')).not.toBeInTheDocument();
      expect(screen.getByText('Highlighted')).toBeInTheDocument();
      expect(screen.getByText('Selected')).toBeInTheDocument();
    });

    it('uses the highlighted node color for the legend swatch', () => {
      render(<KnowledgeGraph data={mockGraphData} />);

      expect(screen.getByText('Highlighted').previousElementSibling).toHaveClass('bg-amber-500');
      expect(screen.getByText('Selected').previousElementSibling).toHaveClass('bg-emerald-500');
      expect(screen.getByText('Prerequisite').previousElementSibling).toHaveClass('bg-red-500');
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
