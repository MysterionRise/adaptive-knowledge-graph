/**
 * The graph page together with the real KnowledgeGraph (only Cytoscape is faked): clicking a
 * node re-renders the page, which must not rebuild and re-lay out the graph.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import cytoscapeModule from 'cytoscape';
import GraphPage from '@/app/graph/page';
import { apiClient } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';
import { fakeNode, type CytoscapeMock } from './helpers/cytoscapeMock';

jest.mock('cytoscape', () => require('./helpers/cytoscapeMock').createCytoscapeMock());
jest.mock('cytoscape-cose-bilkent', () => jest.fn());

// Load the real graph component synchronously instead of with next/dynamic
jest.mock('next/dynamic', () => () => require('@/components/KnowledgeGraph').default);

jest.mock('@/lib/api-client', () => ({
  apiClient: { getGraphData: jest.fn() },
}));

jest.mock('@/components/SubjectPicker', () => function MockSubjectPicker() {
  return null;
});

const cytoscape = cytoscapeModule as unknown as CytoscapeMock;
const initialStoreState = useAppStore.getState();

const graphData = {
  nodes: [
    { data: { id: 'c1', label: 'Colonial America', importance: 0.7 } },
    { data: { id: 'c2', label: 'American Revolution', importance: 0.95 } },
  ],
  edges: [{ data: { id: 'e1', source: 'c1', target: 'c2', type: 'PREREQ', label: 'PREREQ' } }],
};

describe('Graph page interactions', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    cytoscape.instances.length = 0;
    useAppStore.setState(initialStoreState);
    (apiClient.getGraphData as jest.Mock).mockResolvedValue(graphData);
  });

  it('keeps the graph, its layout and the selection when a node is clicked', async () => {
    render(<GraphPage />);
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1));
    const cy = cytoscape.instances[0];

    act(() => cy.handlers['tap node']({ target: fakeNode('c2', 'American Revolution', 0.95, 1) }));

    // The page re-rendered with the selection...
    expect(screen.getByRole('heading', { name: 'Selected Concept', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask AI Tutor About This' })).toBeInTheDocument();
    // ...without destroying the graph or running the layout again
    expect(cy.destroy).not.toHaveBeenCalled();
    expect(cytoscape).toHaveBeenCalledTimes(1);
  });

  it('keeps the graph when highlights are cleared and re-applies them', async () => {
    useAppStore.setState({ highlightedConcepts: ['American Revolution'], lastQuery: 'Why?' });
    render(<GraphPage />);
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1));
    const cy = cytoscape.instances[0];
    expect(cy.fit).toHaveBeenCalledTimes(1);

    act(() => useAppStore.getState().clearHighlightedConcepts());

    expect(cy.destroy).not.toHaveBeenCalled();
    expect(cy.nodes().removeClass).toHaveBeenLastCalledWith('highlighted faded');
  });
});
