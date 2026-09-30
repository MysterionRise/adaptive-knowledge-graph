'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { apiClient } from '@/lib/api-client';
import { describeError } from '@/lib/api-errors';
import { X, Loader2 } from 'lucide-react';
import { useAppStore } from '@/lib/store';
import { useApiQuery } from '@/lib/useApiQuery';
import { GraphSkeleton } from '@/components/Skeleton';
import ErrorMessage from '@/components/ErrorMessage';
import SubjectPicker from '@/components/SubjectPicker';

// Dynamic import to avoid SSR issues with Cytoscape
const KnowledgeGraph = dynamic(() => import('@/components/KnowledgeGraph'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-[600px] bg-gray-50 rounded-lg">
      <Loader2 className="w-8 h-8 animate-spin text-primary-600" aria-label="Loading graph" />
    </div>
  ),
});

// Maximum number of concepts requested for the visualization
const GRAPH_CONCEPT_LIMIT = 100;

interface SelectedConcept {
  subject: string;
  id: string;
  name: string;
}

export default function GraphPage() {
  const router = useRouter();
  // Narrow selectors: the page only re-renders when these values change
  const currentSubject = useAppStore((state) => state.currentSubject);
  const highlightedConcepts = useAppStore((state) => state.highlightedConcepts);
  const clearHighlightedConcepts = useAppStore((state) => state.clearHighlightedConcepts);
  const lastQuery = useAppStore((state) => state.lastQuery);
  const chapterColors = useAppStore((state) => state.subjectTheme?.chapter_colors);

  const graph = useApiQuery(`graph:${currentSubject}`, (signal) =>
    apiClient.getGraphData(GRAPH_CONCEPT_LIMIT, currentSubject, { signal })
  );
  const graphData = graph.isLoading || graph.error ? null : graph.data;

  const [selected, setSelected] = useState<SelectedConcept | null>(null);
  // A concept selected on another subject's graph is not shown
  const selectedConcept = selected?.subject === currentSubject ? selected : null;

  // Stable handler, so re-renders of this page never rebuild the graph
  const handleNodeClick = useCallback(
    (nodeId: string, nodeName: string) => {
      setSelected({ subject: currentSubject, id: nodeId, name: nodeName });
    },
    [currentSubject]
  );

  const handleAskAboutConcept = () => {
    if (selectedConcept) {
      router.push(`/chat?question=${encodeURIComponent(`Explain ${selectedConcept.name}`)}`);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                Knowledge Graph Visualization
              </h1>
              <p className="mt-2 text-gray-600">
                Explore concepts and their relationships
              </p>
            </div>
            <SubjectPicker />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Graph Visualization */}
          <div className="lg:col-span-3">
            {/* Highlighted concepts banner */}
            {highlightedConcepts.length > 0 && (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-amber-900">
                    Highlighting {highlightedConcepts.length} concepts
                    {lastQuery && (
                      <span className="text-amber-700 ml-1">
                        from query: &quot;{lastQuery.substring(0, 30)}...&quot;
                      </span>
                    )}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={clearHighlightedConcepts}
                  className="p-1 hover:bg-amber-100 rounded transition-colors"
                  aria-label="Clear highlights"
                >
                  <X className="w-4 h-4 text-amber-700" aria-hidden="true" />
                </button>
              </div>
            )}

            {graph.isLoading ? (
              <GraphSkeleton />
            ) : graph.error ? (
              <ErrorMessage
                title="Unable to load the knowledge graph."
                message={describeError(graph.error)}
                onRetry={graph.retry}
              />
            ) : graphData && graphData.nodes.length > 0 ? (
              <KnowledgeGraph
                data={graphData}
                onNodeClick={handleNodeClick}
                highlightedConcepts={highlightedConcepts}
                chapterColors={chapterColors}
                className="h-[600px]"
              />
            ) : (
              <div className="flex flex-col items-center justify-center gap-1 h-[600px] bg-gray-50 rounded-lg border border-gray-200 text-center px-4">
                <p className="text-gray-600">No graph data available</p>
                <p className="text-sm text-gray-500">
                  This subject has no concepts in the knowledge graph yet.
                </p>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="lg:col-span-1 space-y-4">
            {/* Instructions */}
            <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
              <h3 className="font-semibold text-gray-900 mb-3">How to Use</h3>
              <ul className="space-y-2 text-sm text-gray-600">
                <li className="flex gap-2">
                  <span className="text-primary-600" aria-hidden="true">•</span>
                  <span>Click nodes to see details and relationships</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-primary-600" aria-hidden="true">•</span>
                  <span>Drag to pan, scroll to zoom</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-primary-600" aria-hidden="true">•</span>
                  <span>Node size indicates importance</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-primary-600" aria-hidden="true">•</span>
                  <span>Edge colors show relationship types</span>
                </li>
              </ul>
            </div>

            {/* Selected Concept Details */}
            {selectedConcept && (
              <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
                <h3 className="font-semibold text-gray-900 mb-3">
                  Selected Concept
                </h3>
                <p className="text-lg font-medium text-primary-600 mb-4">
                  {selectedConcept.name}
                </p>
                <button
                  type="button"
                  onClick={handleAskAboutConcept}
                  className="w-full px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 transition-colors text-sm font-medium"
                >
                  Ask AI Tutor About This
                </button>
              </div>
            )}

            {/* Graph Stats */}
            {graphData && (
              <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
                <h3 className="font-semibold text-gray-900 mb-3">Graph Stats</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Nodes:</span>
                    <span className="font-medium text-gray-900">
                      {graphData.nodes.length}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Edges:</span>
                    <span className="font-medium text-gray-900">
                      {graphData.edges.length}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
