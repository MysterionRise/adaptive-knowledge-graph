'use client';

import { useEffect, useRef, useState } from 'react';
import cytoscape, { Core, NodeSingular } from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import type { GraphData } from '@/lib/types';

// Register layout
if (typeof cytoscape !== 'undefined') {
  cytoscape.use(coseBilkent);
}

interface KnowledgeGraphProps {
  data: GraphData;
  onNodeClick?: (nodeId: string, nodeName: string) => void;
  highlightedConcepts?: string[];
  className?: string;
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
            'background-color': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              // Color gradient from light blue to dark blue based on importance
              const intensity = Math.floor(importance * 200 + 55);
              return `rgb(${255 - intensity}, ${255 - intensity / 2}, 255)`;
            },
            'width': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              return 20 + importance * 40; // Size 20-60px based on importance
            },
            'height': (ele: NodeSingular) => {
              const importance = ele.data('importance') || 0.5;
              return 20 + importance * 40;
            },
            'font-size': '12px',
            'text-valign': 'center',
            'text-halign': 'center',
            'color': '#333',
            'text-outline-color': '#fff',
            'text-outline-width': 2,
            'border-width': 2,
            'border-color': '#666',
          },
        },
        {
          selector: 'node.highlighted',
          style: {
            'background-color': '#f59e0b',
            'border-color': '#d97706',
            'border-width': 4,
          },
        },
        {
          selector: 'node.selected',
          style: {
            'background-color': '#10b981',
            'border-color': '#059669',
            'border-width': 4,
          },
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': (ele) => {
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
            'target-arrow-shape': 'triangle',
            'target-arrow-color': (ele) => {
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
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '10px',
            'text-rotation': 'autorotate',
            'text-background-color': '#fff',
            'text-background-opacity': 0.8,
            'text-background-padding': '2px',
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
      },
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cyRef.current = cy;

    // Node click handler
    cy.on('tap', 'node', (event) => {
      const node = event.target;
      const nodeId = node.id();
      const nodeName = node.data('label');

      // Remove previous selection
      cy.nodes().removeClass('selected');
      // Add selection to clicked node
      node.addClass('selected');

      setSelectedNode(nodeId);

      // Highlight connected nodes
      const neighborhood = node.neighborhood();
      neighborhood.nodes().addClass('highlighted');

      // Call parent callback if provided
      if (onNodeClick) {
        onNodeClick(nodeId, nodeName);
      }
    });

    // Click on background to deselect
    cy.on('tap', (event) => {
      if (event.target === cy) {
        cy.nodes().removeClass('selected highlighted');
        setSelectedNode(null);
      }
    });

    // Cleanup
    return () => {
      cy.destroy();
    };
  }, [data, onNodeClick]);

  // Update highlighted concepts when prop changes
  useEffect(() => {
    if (!cyRef.current) return;

    const cy = cyRef.current;

    // Remove all highlights
    cy.nodes().removeClass('highlighted');

    // Add highlights for specified concepts
    if (highlightedConcepts.length > 0) {
      highlightedConcepts.forEach((conceptName) => {
        const node = cy.nodes().filter((n) => n.data('label') === conceptName);
        if (node.length > 0) {
          node.addClass('highlighted');
          // Also highlight connected nodes
          node.neighborhood().nodes().addClass('highlighted');
        }
      });
    }
  }, [highlightedConcepts]);

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
          onClick={() => cyRef.current?.fit(undefined, 50)}
          className="px-3 py-2 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 text-sm font-medium text-gray-700"
          aria-label="Fit graph to view"
        >
          Fit to View
        </button>
        <button
          onClick={() => cyRef.current?.center()}
          className="px-3 py-2 bg-white rounded-lg shadow-md border border-gray-200 hover:bg-gray-50 text-sm font-medium text-gray-700"
          aria-label="Center graph"
        >
          Center
        </button>
      </div>

      {/* Selected Node Info */}
      {selectedNode && (
        <div className="absolute bottom-4 left-4 bg-white rounded-lg shadow-md p-4 border border-gray-200 max-w-xs">
          <h4 className="font-semibold text-sm text-gray-900 mb-1">
            Selected Concept
          </h4>
          <p className="text-sm text-gray-700">
            {cyRef.current?.getElementById(selectedNode).data('label')}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Importance:{' '}
            {(cyRef.current?.getElementById(selectedNode).data('importance') * 100).toFixed(0)}
            %
          </p>
        </div>
      )}
    </div>
  );
}
