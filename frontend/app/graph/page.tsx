'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { apiClient } from '@/lib/api-client';
import type { GraphData } from '@/lib/types';
import { ArrowLeft, Loader2 } from 'lucide-react';

// Dynamic import to avoid SSR issues with Cytoscape
const KnowledgeGraph = dynamic(() => import('@/components/KnowledgeGraph'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-[600px] bg-gray-50 rounded-lg">
      <Loader2 className="w-8 h-8 animate-spin text-primary-600" />
    </div>
  ),
});

export default function GraphPage() {
  const router = useRouter();
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedConcept, setSelectedConcept] = useState<{
    id: string;
    name: string;
  } | null>(null);

  useEffect(() => {
    const fetchGraphData = async () => {
      try {
        setIsLoading(true);
        const data = await apiClient.getGraphData();
        setGraphData(data);
        setError(null);
      } catch (err: any) {
        console.error('Error fetching graph data:', err);
        setError(err.detail || 'Failed to load graph data. Showing demo data.');
        // Fallback to mock data from API client
        const mockData = await apiClient.getGraphData();
        setGraphData(mockData);
      } finally {
        setIsLoading(false);
      }
    };

    fetchGraphData();
  }, []);

  const handleNodeClick = (nodeId: string, nodeName: string) => {
    setSelectedConcept({ id: nodeId, name: nodeName });
  };

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
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push('/')}
                className="text-gray-600 hover:text-gray-900"
                aria-label="Back to home"
              >
                <ArrowLeft className="w-6 h-6" />
              </button>
              <div>
                <h1 className="text-3xl font-bold text-gray-900">
                  Knowledge Graph Visualization
                </h1>
                <p className="mt-2 text-gray-600">
                  Explore Biology concepts and their relationships
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {error && (
          <div className="mb-4 p-4 bg-yellow-50 border border-yellow-200 rounded-md">
            <p className="text-sm text-yellow-800">{error}</p>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Graph Visualization */}
          <div className="lg:col-span-3">
            {isLoading ? (
              <div className="flex items-center justify-center h-[600px] bg-gray-50 rounded-lg border border-gray-200">
                <div className="text-center">
                  <Loader2 className="w-12 h-12 animate-spin text-primary-600 mx-auto mb-4" />
                  <p className="text-gray-600">Loading knowledge graph...</p>
                </div>
              </div>
            ) : graphData ? (
              <KnowledgeGraph
                data={graphData}
                onNodeClick={handleNodeClick}
                className="h-[600px]"
              />
            ) : (
              <div className="flex items-center justify-center h-[600px] bg-gray-50 rounded-lg border border-gray-200">
                <p className="text-gray-600">No graph data available</p>
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
                  <span className="text-primary-600">•</span>
                  <span>Click nodes to see details and relationships</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-primary-600">•</span>
                  <span>Drag to pan, scroll to zoom</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-primary-600">•</span>
                  <span>Node size indicates importance</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-primary-600">•</span>
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
