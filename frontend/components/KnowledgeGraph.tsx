'use client';

import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  useCallback,
  useId,
  useMemo,
  type FormEvent,
} from 'react';
import cytoscape, {
  Core,
  NodeSingular,
  EdgeSingular,
  EventObject,
} from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import type { GraphData } from '@/lib/types';
import { ZoomIn, ZoomOut, Maximize2, RotateCcw, Search } from 'lucide-react';

// Type for cose-bilkent layout options (not included in @types/cytoscape)
type CoseBilkentLayoutOptions = {
  name: 'cose-bilkent';
  randomize?: boolean;
  nodeRepulsion?: number;
  idealEdgeLength?: number;
  edgeElasticity?: number;
  nestingFactor?: number;
  gravity?: number;
  numIter?: number;
  tile?: boolean;
  animate?: boolean | 'end' | 'during';
  animationDuration?: number;
  nodeDimensionsIncludeLabels?: boolean;
};

// Register layout
if (typeof cytoscape !== 'undefined') {
  cytoscape.use(coseBilkent);
}

// Fallback color when no subject theme is loaded yet
const DEFAULT_CHAPTER_COLORS: Record<string, string> = {
  'default': '#6366f1',
};

/** Relationship types of the graph: edge colour on the canvas and swatch in the legend. */
const EDGE_TYPES: Record<string, { label: string; color: string; swatchClass: string }> = {
  PREREQ: { label: 'Prerequisite', color: '#ef4444', swatchClass: 'bg-red-500' },
  COVERS: { label: 'Covers', color: '#3b82f6', swatchClass: 'bg-blue-500' },
  RELATED: { label: 'Related', color: '#8b5cf6', swatchClass: 'bg-purple-500' },
};
const DEFAULT_EDGE_COLOR = '#9ca3af';

// Stable default, so a missing prop never looks like new highlights on a re-render
const NO_HIGHLIGHTS: string[] = [];

// Number of concepts named in the text summary for screen readers
const SUMMARY_CONCEPT_COUNT = 10;

/** What the graph knows about a selected concept. */
export interface SelectedNodeDetails {
  importance: number;
  connections: number;
}

interface KnowledgeGraphProps {
  data: GraphData;
  onNodeClick?: (nodeId: string, nodeName: string, details: SelectedNodeDetails) => void;
  /** Called when the selection is cleared: a tap on the background or "Reset view". */
  onBackgroundClick?: () => void;
  highlightedConcepts?: string[];
  className?: string;
  chapterColors?: Record<string, string>; // Dynamic colors from subject theme
}

// Helper to get color based on chapter/topic
function getNodeColor(node: NodeSingular, chapterColors: Record<string, string>): string {
  const label = node.data('label') || '';
  const chapter = node.data('chapter') || '';

  for (const [key, color] of Object.entries(chapterColors)) {
    if (key !== 'default' && (label.includes(key) || chapter.includes(key))) {
      return color;
    }
  }
  return chapterColors.default || DEFAULT_CHAPTER_COLORS.default;
}

function getEdgeColor(edge: EdgeSingular): string {
  return EDGE_TYPES[edge.data('type')]?.color ?? DEFAULT_EDGE_COLOR;
}

function clearFocus(cy: Core) {
  cy.nodes().removeClass('selected highlighted faded');
  cy.edges().removeClass('highlighted faded');
}

/** Select `node`, highlight its neighbourhood and fade the rest of the graph. */
function focusNode(cy: Core, node: NodeSingular): SelectedNodeDetails {
  clearFocus(cy);
  node.addClass('selected');

  // Connected nodes and edges
  const neighborhood = node.neighborhood();
  const connectedNodes = neighborhood.nodes();
  const connectedEdges = neighborhood.edges();
  connectedNodes.addClass('highlighted');
  connectedEdges.addClass('highlighted');

  // Fade non-connected elements for focus
  cy.nodes().not(node).not(connectedNodes).addClass('faded');
  cy.edges().not(connectedEdges).addClass('faded');

  return {
    importance: Number(node.data('importance') ?? 0),
    connections: connectedNodes.length,
  };
}

/** Highlight the nodes whose label matches one of `concepts` and fade the others. */
function applyHighlights(cy: Core, concepts: string[]) {
  cy.nodes().removeClass('highlighted faded');
  cy.edges().removeClass('highlighted faded');

  const wanted = concepts.map((concept) => concept.trim().toLowerCase()).filter(Boolean);
  if (wanted.length === 0) return;

  const highlightedNodes = cy.nodes().filter((node) => {
    const label = String(node.data('label') ?? '').toLowerCase();
    return wanted.some((concept) => label === concept || label.includes(concept));
  });
  // No concept is on this graph: keep the graph readable instead of fading every node.
  if (highlightedNodes.length === 0) return;

  highlightedNodes.addClass('highlighted');

  // Get all connected edges between highlighted nodes
  const connectedEdges = highlightedNodes.edgesWith(highlightedNodes);
  connectedEdges.addClass('highlighted');

  // Fade non-highlighted nodes for focus
  cy.nodes().not(highlightedNodes).addClass('faded');
  cy.edges().not(connectedEdges).addClass('faded');

  // Fit view to highlighted nodes
  cy.fit(highlightedNodes, 80);
}

/** The node whose label equals `query` (case-insensitive), else the first whose label contains it. */
function findNode(data: GraphData, query: string) {
  const wanted = query.trim().toLowerCase();
  if (!wanted) return undefined;
  return (
    data.nodes.find((node) => node.data.label.toLowerCase() === wanted) ??
    data.nodes.find((node) => node.data.label.toLowerCase().includes(wanted))
  );
}

const CONTROL_BUTTON_CLASS =
  'p-2.5 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-all';

export default function KnowledgeGraph({
  data,
  onNodeClick,
  onBackgroundClick,
  highlightedConcepts = NO_HIGHLIGHTS,
  className = '',
  chapterColors,
}: KnowledgeGraphProps) {
  // Merge provided colors with defaults (memoized to prevent unnecessary re-renders)
  const effectiveColors = useMemo(
    () => ({ ...DEFAULT_CHAPTER_COLORS, ...chapterColors }),
    [chapterColors]
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const colorsRef = useRef(effectiveColors);
  const summaryId = useId();
  const searchId = useId();
  const listId = useId();

  const [searchQuery, setSearchQuery] = useState('');
  // A search result belongs to one data set: a new graph starts without a stale message.
  const [searchStatus, setSearchStatus] = useState<{ data: GraphData; text: string } | null>(null);
  const searchMessage = searchStatus?.data === data ? searchStatus.text : '';

  // Called from Cytoscape handlers. As effect events they always see the latest props, so a
  // parent passing a new onNodeClick function never rebuilds (and re-lays out) the graph.
  const handleNodeTap = useEffectEvent((node: NodeSingular, details: SelectedNodeDetails) => {
    onNodeClick?.(node.id(), node.data('label'), details);
  });
  const handleBackgroundTap = useEffectEvent(() => onBackgroundClick?.());

  // Build the graph and run the layout once per data set.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Initialize Cytoscape
    const cy = cytoscape({
      container,
      elements: {
        nodes: data.nodes,
        edges: data.edges,
      },
      style: [
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'background-color': (ele: NodeSingular) => getNodeColor(ele, colorsRef.current),
            'width': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              return 25 + importance * 45; // Size 25-70px based on importance
            },
            'height': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              return 25 + importance * 45;
            },
            'font-size': 10,
            'font-weight': 'bold' as const,
            // Labels wrap under the node, so long concept names stay readable
            'text-wrap': 'wrap' as const,
            'text-max-width': '96px',
            'text-valign': 'bottom' as const,
            'text-halign': 'center' as const,
            'text-margin-y': 5,
            'color': '#1f2937',
            'text-outline-color': '#ffffff',
            'text-outline-width': 2,
            'border-width': 3,
            'border-color': '#ffffff',
            'border-opacity': 0.8,
            'background-opacity': 0.9,
            'transition-property': 'background-color, border-color, border-width, width, height',
            'transition-duration': 300,
          },
        },
        {
          selector: 'node.highlighted',
          style: {
            'background-color': '#f59e0b',
            'border-color': '#fbbf24',
            'border-width': 5,
            'z-index': 10,
          },
        },
        {
          selector: 'node.selected',
          style: {
            'background-color': '#10b981',
            'border-color': '#34d399',
            'border-width': 5,
            'z-index': 20,
          },
        },
        {
          selector: 'node.faded',
          style: {
            'opacity': 0.3,
          },
        },
        {
          // Edge labels only appear on hover or on the selected neighbourhood (see below)
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': getEdgeColor,
            'target-arrow-shape': 'triangle' as const,
            'target-arrow-color': getEdgeColor,
            'curve-style': 'bezier' as const,
            'font-size': 9,
            'text-rotation': 'autorotate' as const,
            'text-background-color': '#ffffff',
            'text-background-opacity': 0.9,
            'text-background-padding': '3px',
            'text-background-shape': 'roundrectangle' as const,
            'opacity': 0.7,
            'transition-property': 'opacity, width, line-color',
            'transition-duration': 300,
          },
        },
        {
          selector: 'edge.hover',
          style: {
            'label': 'data(label)',
          },
        },
        {
          selector: 'edge.highlighted',
          style: {
            'label': 'data(label)',
            'width': 4,
            'opacity': 1,
            'z-index': 10,
          },
        },
        {
          selector: 'edge.faded',
          style: {
            'opacity': 0.15,
          },
        },
      ],
      layout: {
        name: 'cose-bilkent',
        randomize: false,
        nodeRepulsion: 8000,
        idealEdgeLength: 100,
        edgeElasticity: 0.45,
        nestingFactor: 0.1,
        gravity: 0.25,
        numIter: 2500,
        tile: true,
        animate: 'end',
        animationDuration: 1000,
        nodeDimensionsIncludeLabels: true,
      } as CoseBilkentLayoutOptions,
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cyRef.current = cy;

    // Node click: select it and highlight its neighbourhood
    cy.on('tap', 'node', (event: EventObject) => {
      const node = event.target as NodeSingular;
      handleNodeTap(node, focusNode(cy, node));
    });

    // Click on background to reset view
    cy.on('tap', (event: EventObject) => {
      if (event.target === cy) {
        clearFocus(cy);
        handleBackgroundTap();
      }
    });

    // Pointer cursor over nodes
    cy.on('mouseover', 'node', () => {
      container.style.cursor = 'pointer';
    });
    cy.on('mouseout', 'node', () => {
      container.style.cursor = '';
    });

    // Edge labels on hover
    cy.on('mouseover', 'edge', (event: EventObject) => {
      (event.target as EdgeSingular).addClass('hover');
    });
    cy.on('mouseout', 'edge', (event: EventObject) => {
      (event.target as EdgeSingular).removeClass('hover');
    });

    // Cleanup
    return () => {
      cy.destroy();
      if (cyRef.current === cy) cyRef.current = null;
    };
  }, [data]);

  // Recolour the nodes when the subject theme changes, without rebuilding the graph.
  useEffect(() => {
    colorsRef.current = effectiveColors;
    cyRef.current?.style().update();
  }, [effectiveColors]);

  // Highlight the concepts sent from the chat page, again after every rebuild of the graph.
  useEffect(() => {
    if (!cyRef.current) return;
    applyHighlights(cyRef.current, highlightedConcepts);
  }, [data, highlightedConcepts]);

  // Text alternative for the canvas: the most important concepts of the graph.
  const summary = useMemo(() => {
    const topConcepts = [...data.nodes]
      .sort((a, b) => (b.data.importance ?? 0) - (a.data.importance ?? 0))
      .slice(0, SUMMARY_CONCEPT_COUNT)
      .map((node) => node.data.label);
    return topConcepts.length > 0
      ? `Most important concepts: ${topConcepts.join(', ')}.`
      : 'The graph has no concepts yet.';
  }, [data]);

  // Relationship types on this graph, in the legend's fixed order
  const presentEdgeTypes = useMemo(
    () => Object.keys(EDGE_TYPES).filter((type) => data.edges.some((edge) => edge.data.type === type)),
    [data]
  );

  // Find a concept by name: select it on the canvas, zoom to it and tell the parent
  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const cy = cyRef.current;
    const query = searchQuery.trim();
    if (!cy || !query) return;

    const match = findNode(data, query);
    if (!match) {
      setSearchStatus({ data, text: `No concept matches “${query}”` });
      return;
    }
    setSearchStatus(null);

    const node = cy.getElementById(match.data.id);
    const details = focusNode(cy, node);
    cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.5) }, { duration: 300 });
    onNodeClick?.(match.data.id, match.data.label, details);
  };

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    cyRef.current?.zoom(cyRef.current.zoom() * 1.3);
    cyRef.current?.center();
  }, []);

  const handleZoomOut = useCallback(() => {
    cyRef.current?.zoom(cyRef.current.zoom() / 1.3);
    cyRef.current?.center();
  }, []);

  const handleFitToView = useCallback(() => {
    if (!cyRef.current) return;
    cyRef.current.fit(undefined, 50);
  }, []);

  const handleResetView = useCallback(() => {
    setSearchStatus(null);
    onBackgroundClick?.();
    if (!cyRef.current) return;
    clearFocus(cyRef.current);
    cyRef.current.fit(undefined, 50);
  }, [onBackgroundClick]);

  return (
    <div className={`relative ${className}`}>
      <div
        ref={containerRef}
        role="img"
        aria-label={`Knowledge graph with ${data.nodes.length} concepts and ${data.edges.length} relationships`}
        aria-describedby={summaryId}
        className="cytoscape-container h-full w-full bg-gray-50 rounded-lg border border-gray-200"
      />
      <div id={summaryId} className="sr-only">
        <p>{summary}</p>
        {highlightedConcepts.length > 0 && (
          <p>Highlighted concepts: {highlightedConcepts.join(', ')}.</p>
        )}
      </div>

      {/* Concept search */}
      <form
        role="search"
        onSubmit={handleSearch}
        className="absolute left-4 top-4 flex flex-wrap items-start gap-2"
      >
        <label htmlFor={searchId} className="sr-only">
          Find a concept
        </label>
        <input
          id={searchId}
          type="search"
          list={listId}
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Find a concept…"
          autoComplete="off"
          className="w-56 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm shadow-md focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
        <datalist id={listId}>
          {data.nodes.map((node) => (
            <option key={node.data.id} value={node.data.label} />
          ))}
        </datalist>
        <button
          type="submit"
          className={CONTROL_BUTTON_CLASS}
          aria-label="Find concept"
          title="Find concept"
        >
          <Search className="w-5 h-5 text-gray-700" />
        </button>
        <p
          role="status"
          className={`basis-full text-xs text-gray-700 ${
            searchMessage ? 'rounded-md bg-white/90 px-2 py-1 shadow-sm' : ''
          }`}
        >
          {searchMessage}
        </p>
      </form>

      {/* Legend */}
      <div className="absolute top-4 right-4 bg-white rounded-lg shadow-md p-4 border border-gray-200">
        <h4 className="font-semibold text-sm text-gray-900 mb-2">Legend</h4>
        <div className="space-y-2 text-xs">
          {presentEdgeTypes.map((type) => (
            <div key={type} className="flex items-center gap-2">
              <div className={`w-4 h-0.5 ${EDGE_TYPES[type].swatchClass}`}></div>
              <span className="text-gray-700">{EDGE_TYPES[type].label}</span>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-amber-500"></div>
            <span className="text-gray-700">Highlighted</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-emerald-500"></div>
            <span className="text-gray-700">Selected</span>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-2">
        <button
          onClick={handleZoomIn}
          className={CONTROL_BUTTON_CLASS}
          aria-label="Zoom in"
          title="Zoom In"
        >
          <ZoomIn className="w-5 h-5 text-gray-700" />
        </button>
        <button
          onClick={handleZoomOut}
          className={CONTROL_BUTTON_CLASS}
          aria-label="Zoom out"
          title="Zoom Out"
        >
          <ZoomOut className="w-5 h-5 text-gray-700" />
        </button>
        <button
          onClick={handleFitToView}
          className={CONTROL_BUTTON_CLASS}
          aria-label="Fit to view"
          title="Fit to View"
        >
          <Maximize2 className="w-5 h-5 text-gray-700" />
        </button>
        <button
          onClick={handleResetView}
          className={CONTROL_BUTTON_CLASS}
          aria-label="Reset view"
          title="Reset View"
        >
          <RotateCcw className="w-5 h-5 text-gray-700" />
        </button>
      </div>
    </div>
  );
}
