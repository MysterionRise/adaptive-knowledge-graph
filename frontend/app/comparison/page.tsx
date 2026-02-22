'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import type { QuestionResponse } from '@/lib/types';
import { ArrowLeft, Loader2, Network, Sparkles, AlertCircle } from 'lucide-react';
import { useAppStore } from '@/lib/store';
import SubjectPicker from '@/components/SubjectPicker';

export default function ComparisonPage() {
  const router = useRouter();
  const [question, setQuestion] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [withKG, setWithKG] = useState<QuestionResponse | null>(null);
  const [withoutKG, setWithoutKG] = useState<QuestionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { currentSubject } = useAppStore();

  const handleCompare = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setIsLoading(true);
    setWithKG(null);
    setWithoutKG(null);
    setError(null);

    try {
      // Fetch both responses in parallel
      const [responseWithKG, responseWithoutKG] = await Promise.all([
        apiClient.askQuestion({
          question,
          use_kg_expansion: true,
          top_k: 5,
        }, currentSubject),
        apiClient.askQuestion({
          question,
          use_kg_expansion: false,
          top_k: 5,
        }, currentSubject),
      ]);

      setWithKG(responseWithKG);
      setWithoutKG(responseWithoutKG);
    } catch (err: any) {
      console.error('Error comparing responses:', err);
      setError(err.detail || 'Failed to get responses. Please ensure the backend is running.');
    } finally {
      setIsLoading(false);
    }
  };

  const SUBJECT_EXAMPLES: Record<string, string[]> = {
    us_history: [
      'What caused the American Revolution?',
      'Explain the significance of the Constitution',
      'How did the Civil War affect society?',
    ],
    economics: [
      'How do supply and demand determine prices?',
      'What is the role of the Federal Reserve?',
      'Explain the causes of inflation',
    ],
    biology: [
      'What is the process of photosynthesis?',
      'How does DNA replication work?',
      'Explain natural selection and evolution',
    ],
    world_history: [
      'What caused the fall of the Roman Empire?',
      'Explain the impact of the Renaissance',
      'How did colonialism shape the modern world?',
    ],
  };
  const exampleQuestions = SUBJECT_EXAMPLES[currentSubject] || SUBJECT_EXAMPLES.us_history;

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
                  KG-RAG vs Regular RAG Comparison
                </h1>
                <p className="mt-2 text-gray-600">
                  See how knowledge graph expansion improves answer quality
                </p>
              </div>
            </div>
            <SubjectPicker />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Question Input */}
        <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 mb-8">
          <form onSubmit={handleCompare}>
            <div className="mb-4">
              <label
                htmlFor="question"
                className="block text-sm font-medium text-gray-700 mb-2"
              >
                Ask a question to compare both approaches:
              </label>
              <input
                id="question"
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g., What caused the American Revolution?"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                disabled={isLoading}
              />
            </div>

            {/* Example Questions */}
            <div className="mb-4">
              <p className="text-sm text-gray-600 mb-2">Try these examples:</p>
              <div className="flex flex-wrap gap-2">
                {exampleQuestions.map((q, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setQuestion(q)}
                    className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded-full hover:bg-gray-200 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading || !question.trim()}
              className="w-full px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Comparing...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-5 h-5" />
                  <span>Compare Approaches</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {/* Comparison Results */}
        {(withKG || withoutKG) && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* With KG Expansion */}
            <div className="bg-white rounded-lg shadow-md border-2 border-green-300 overflow-hidden">
              <div className="bg-green-50 border-b border-green-200 px-6 py-4">
                <div className="flex items-center gap-2">
                  <Network className="w-5 h-5 text-green-600" />
                  <h3 className="text-lg font-semibold text-green-900">
                    With KG Expansion
                  </h3>
                </div>
                <p className="text-sm text-green-700 mt-1">
                  Enhanced with knowledge graph relationships
                </p>
              </div>
              <div className="p-6">
                {withKG ? (
                  <ComparisonResult response={withKG} showKGInfo={true} />
                ) : (
                  <div className="flex items-center justify-center h-32">
                    <Loader2 className="w-8 h-8 animate-spin text-green-600" />
                  </div>
                )}
              </div>
            </div>

            {/* Without KG Expansion */}
            <div className="bg-white rounded-lg shadow-md border-2 border-gray-300 overflow-hidden">
              <div className="bg-gray-50 border-b border-gray-200 px-6 py-4">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-gray-900">
                    Regular RAG
                  </h3>
                </div>
                <p className="text-sm text-gray-700 mt-1">
                  Standard semantic search without KG
                </p>
              </div>
              <div className="p-6">
                {withoutKG ? (
                  <ComparisonResult response={withoutKG} showKGInfo={false} />
                ) : (
                  <div className="flex items-center justify-center h-32">
                    <Loader2 className="w-8 h-8 animate-spin text-gray-600" />
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Explanation */}
        {(withKG || withoutKG) && (
          <div className="mt-8 bg-blue-50 border border-blue-200 rounded-lg p-6">
            <h3 className="text-lg font-semibold text-blue-900 mb-3">
              Why KG Expansion Matters
            </h3>
            <div className="space-y-2 text-sm text-blue-800">
              <p>
                <strong>Knowledge Graph Expansion</strong> improves answer quality by:
              </p>
              <ul className="list-disc list-inside space-y-1 ml-4">
                <li>
                  Identifying prerequisite concepts needed to understand the answer
                </li>
                <li>
                  Including related concepts that provide additional context
                </li>
                <li>
                  Retrieving more comprehensive and relevant chunks from the textbook
                </li>
                <li>Providing a more complete understanding of the topic</li>
              </ul>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// Comparison Result Component
interface ComparisonResultProps {
  response: QuestionResponse;
  showKGInfo: boolean;
}

function ComparisonResult({ response, showKGInfo }: ComparisonResultProps) {
  return (
    <div className="space-y-4">
      {/* Answer */}
      <div>
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Answer:</h4>
        <p className="text-gray-800 text-sm leading-relaxed">{response.answer}</p>
      </div>

      {/* KG Expansion Info */}
      {showKGInfo && response.expanded_concepts && response.expanded_concepts.length > 0 && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-lg">
          <h4 className="text-sm font-semibold text-green-900 mb-2">
            Expanded Concepts ({response.expanded_concepts.length}):
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {response.expanded_concepts.map((concept, idx) => (
              <span
                key={idx}
                className="inline-block px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full"
              >
                {concept}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-200">
        <div>
          <p className="text-xs text-gray-600">Retrieved Chunks</p>
          <p className="text-lg font-semibold text-gray-900">
            {response.retrieved_count}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-600">Concepts Used</p>
          <p className="text-lg font-semibold text-gray-900">
            {response.expanded_concepts?.length || 0}
          </p>
        </div>
      </div>

      {/* Sources Count */}
      {response.sources && response.sources.length > 0 && (
        <div className="pt-2">
          <p className="text-xs text-gray-600">
            Based on {response.sources.length} source
            {response.sources.length > 1 ? 's' : ''} from the knowledge base
          </p>
        </div>
      )}
    </div>
  );
}
