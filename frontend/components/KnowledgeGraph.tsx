'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import cytoscape, {
  Core,
  NodeSingular,
  EdgeSingular,
  Stylesheet,
  LayoutOptions,
} from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import type { GraphData } from '@/lib/types';
import { ZoomIn, ZoomOut, Maximize2, RotateCcw } from 'lucide-react';

// Type for cose-bilkent layout options (not included in @types/cytoscape)
interface CoseBilkentLayoutOptions extends LayoutOptions {
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
}

// Register layout
if (typeof cytoscape !== 'undefined') {
  cytoscape.use(coseBilkent);
}

// Color mappings for chapters/topics
const CHAPTER_COLORS: Record<string, string> = {
  'Revolution': '#ef4444',
  'Constitution': '#3b82f6',
  'Civil War': '#8b5cf6',
  'Reconstruction': '#10b981',
  'Industrialization': '#f59e0b',
  'World War': '#ec4899',
  'Cold War': '#06b6d4',
  'default': '#6366f1',
};

interface KnowledgeGraphProps {
  data: GraphData;
  onNodeClick?: (nodeId: string, nodeName: string) => void;
  highlightedConcepts?: string[];
  className?: string;
}

// Helper to get color based on chapter/topic
function getNodeColor(node: NodeSingular): string {
  const label = node.data('label') || '';
  const chapter = node.data('chapter') || '';

  for (const [key, color] of Object.entries(CHAPTER_COLORS)) {
    if (key !== 'default' && (label.includes(key) || chapter.includes(key))) {
      return color;
    }
  }
  return CHAPTER_COLORS.default;
}

export default function KnowledgeGraph({
  data,
  onNodeClick,
  highlightedConcepts = [],
  className = '',
}: KnowledgeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [isAnimating, setIsAnimating] = useState(false);
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    if (!containerRef.current || !data) return;

    // Initialize Cytoscape
    const cy = cytoscape({
      container: containerRef.current,
      elements: {
        nodes: data.nodes,
        edges: data.edges,
      },
      style: [
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'background-color': (ele: NodeSingular) => getNodeColor(ele),
            'width': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              return 25 + importance * 45; // Size 25-70px based on importance
            },
            'height': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              return 25 + importance * 45;
            },
            'font-size': 11,
            'font-weight': 'bold' as const,
            'text-valign': 'center' as const,
            'text-halign': 'center' as const,
            'color': '#1f2937',
            'text-outline-color': '#ffffff',
            'text-outline-width': 2,
            'border-width': 3,
            'border-color': '#ffffff',
            'border-opacity': 0.8,
            'background-opacity': 0.9,
            'transition-property': 'background-color, border-color, border-width, width, height',
            'transition-duration': 300,
          } as Stylesheet['style'],
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
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': (ele: EdgeSingular) => {
              const type = ele.data('type');
              switch (type) {
                case 'PREREQ':
                  return '#ef4444'; // Red for prerequisites
                case 'COVERS':
                  return '#3b82f6'; // Blue for covers
                case 'RELATED':
                  return '#8b5cf6'; // Purple for related
                default:
                  return '#9ca3af'; // Gray default
              }
            },
            'target-arrow-shape': 'triangle' as const,
            'target-arrow-color': (ele: EdgeSingular) => {
              const type = ele.data('type');
              switch (type) {
                case 'PREREQ':
                  return '#ef4444';
                case 'COVERS':
                  return '#3b82f6';
                case 'RELATED':
                  return '#8b5cf6';
                default:
                  return '#9ca3af';
              }
            },
            'curve-style': 'bezier' as const,
            'label': 'data(label)',
            'font-size': 9,
            'text-rotation': 'autorotate' as const,
            'text-background-color': '#ffffff',
            'text-background-opacity': 0.9,
            'text-background-padding': 3,
            'text-background-shape': 'roundrectangle' as const,
            'opacity': 0.7,
            'transition-property': 'opacity, width, line-color',
            'transition-duration': 300,
          } as Stylesheet['style'],
        },
        {
          selector: 'edge.highlighted',
          style: {
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
      } as CoseBilkentLayoutOptions,
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cyRef.current = cy;

    // Node click handler with enhanced visual feedback
    cy.on('tap', 'node', (event) => {
      const node = event.target;
      const nodeId = node.id();
      const nodeName = node.data('label');

      // Remove all previous classes
      cy.nodes().removeClass('selected highlighted faded');
      cy.edges().removeClass('highlighted faded');

      // Add selection to clicked node
      node.addClass('selected');

      // Get neighborhood (connected nodes and edges)
      const neighborhood = node.neighborhood();
      const connectedNodes = neighborhood.nodes();
      const connectedEdges = neighborhood.edges();

      // Highlight connected elements
      connectedNodes.addClass('highlighted');
      connectedEdges.addClass('highlighted');

      // Fade non-connected elements for focus
      cy.nodes().not(node).not(connectedNodes).addClass('faded');
      cy.edges().not(connectedEdges).addClass('faded');

      setSelectedNode(nodeId);

      // Call parent callback if provided
      if (onNodeClick) {
        onNodeClick(nodeId, nodeName);
      }
    });

    // Click on background to reset view
    cy.on('tap', (event) => {
      if (event.target === cy) {
        cy.nodes().removeClass('selected highlighted faded');
        cy.edges().removeClass('highlighted faded');
        setSelectedNode(null);
      }
    });

    // Hover effects for better interactivity
    cy.on('mouseover', 'node', (event) => {
      const node = event.target;
      if (!node.hasClass('selected')) {
        node.style('cursor', 'pointer');
      }
    });

    // Cleanup
    return () => {
      cy.destroy();
    };
  }, [data, onNodeClick]);

  // Update highlighted concepts when prop changes (from chat page)
  useEffect(() => {
    if (!cyRef.current) return;

    const cy = cyRef.current;

    // Remove all highlights and fades
    cy.nodes().removeClass('highlighted faded');
    cy.edges().removeClass('highlighted faded');

    // Add highlights for specified concepts
    if (highlightedConcepts.length > 0) {
      const highlightedNodes = cy.collection();

      highlightedConcepts.forEach((conceptName) => {
        const node = cy.nodes().filter((n) => {
          const label = n.data('label') || '';
          return label.toLowerCase() === conceptName.toLowerCase() ||
                 label.toLowerCase().includes(conceptName.toLowerCase());
        });
        if (node.length > 0) {
          highlightedNodes.merge(node);
        }
      });

      // Highlight matched nodes
      highlightedNodes.addClass('highlighted');

      // Get all connected edges between highlighted nodes
      const connectedEdges = highlightedNodes.edgesWith(highlightedNodes);
      connectedEdges.addClass('highlighted');

      // Fade non-highlighted nodes for focus
      cy.nodes().not(highlightedNodes).addClass('faded');
      cy.edges().not(connectedEdges).addClass('faded');

      // Fit view to highlighted nodes
      if (highlightedNodes.length > 0) {
        cy.fit(highlightedNodes, 80);
      }
    }
  }, [highlightedConcepts]);

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
    if (!cyRef.current) return;
    cyRef.current.nodes().removeClass('selected highlighted faded');
    cyRef.current.edges().removeClass('highlighted faded');
    setSelectedNode(null);
    cyRef.current.fit(undefined, 50);
  }, []);

  return (
    <div className={`relative ${className}`}>
      <div
        ref={containerRef}
        className="cytoscape-container w-full h-full bg-gray-50 rounded-lg border border-gray-200"
        style={{ minHeight: '600px' }}
      />

      {/* Legend */}
      <div className="absolute top-4 right-4 bg-white rounded-lg shadow-md p-4 border border-gray-200">
        <h4 className="font-semibold text-sm text-gray-900 mb-2">Legend</h4>
        <div className="space-y-2 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-4 h-0.5 bg-red-500"></div>
            <span className="text-gray-700">Prerequisite</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-0.5 bg-blue-500"></div>
            <span className="text-gray-700">Covers</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-0.5 bg-purple-500"></div>
            <span className="text-gray-700">Related</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-orange-500"></div>
            <span className="text-gray-700">Highlighted</span>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-2">
        <button
          onClick={handleZoomIn}
          className="p-2.5 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-all"
          aria-label="Zoom in"
          title="Zoom In"
        >
          <ZoomIn className="w-5 h-5 text-gray-700" />
        </button>
        <button
          onClick={handleZoomOut}
          className="p-2.5 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-all"
          aria-label="Zoom out"
          title="Zoom Out"
        >
          <ZoomOut className="w-5 h-5 text-gray-700" />
        </button>
        <button
          onClick={handleFitToView}
          className="p-2.5 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-all"
          aria-label="Fit to view"
          title="Fit to View"
        >
          <Maximize2 className="w-5 h-5 text-gray-700" />
        </button>
        <button
          onClick={handleResetView}
          className="p-2.5 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-all"
          aria-label="Reset view"
          title="Reset View"
        >
          <RotateCcw className="w-5 h-5 text-gray-700" />
        </button>
      </div>

      {/* Selected Node Info */}
      {selectedNode && (
        <div className="absolute bottom-4 left-4 bg-white rounded-xl shadow-lg p-5 border border-gray-200 max-w-xs animate-in slide-in-from-left duration-300">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
            <h4 className="font-semibold text-sm text-gray-500 uppercase tracking-wide">
              Selected Concept
            </h4>
          </div>
          <p className="text-lg font-bold text-gray-900 mb-2">
            {cyRef.current?.getElementById(selectedNode).data('label')}
          </p>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">Importance:</span>
              <span className="font-semibold text-emerald-600">
                {(cyRef.current?.getElementById(selectedNode).data('importance') * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">Connections:</span>
              <span className="font-semibold text-blue-600">
                {cyRef.current?.getElementById(selectedNode).neighborhood().nodes().length}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
