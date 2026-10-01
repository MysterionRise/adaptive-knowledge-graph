'use client';

import { useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api-client';
import { describeError, isAbortError } from '@/lib/api-errors';
import type { QuestionResponse } from '@/lib/types';
import { Loader2, Network, Sparkles } from 'lucide-react';
import { useAppStore } from '@/lib/store';
import ErrorMessage from '@/components/ErrorMessage';
import MarkdownContent from '@/components/MarkdownContent';
import SubjectPicker from '@/components/SubjectPicker';

type Variant = 'kg' | 'plain';

type AnswerState =
  | { status: 'loading' }
  | { status: 'success'; response: QuestionResponse }
  | { status: 'error'; message: string };

const VARIANTS: Variant[] = ['kg', 'plain'];

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

export default function ComparisonPage() {
  const currentSubject = useAppStore((state) => state.currentSubject);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                KG-RAG vs Regular RAG Comparison
              </h1>
              <p className="mt-2 text-gray-600">
                See how knowledge graph expansion improves answer quality
              </p>
            </div>
            <SubjectPicker />
          </div>
        </div>
      </header>

      {/* Main Content: a new subject starts a fresh comparison (and cancels running ones) */}
      <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <ComparisonWorkspace key={currentSubject} subject={currentSubject} />
      </main>
    </div>
  );
}

function ComparisonWorkspace({ subject }: { subject: string }) {
  const [question, setQuestion] = useState('');
  const [askedQuestion, setAskedQuestion] = useState('');
  const [answers, setAnswers] = useState<Partial<Record<Variant, AnswerState>>>({});
  const controllersRef = useRef<Partial<Record<Variant, AbortController>>>({});

  // Cancel the answers still being generated when the comparison goes away
  useEffect(() => {
    const controllers = controllersRef.current;
    return () => VARIANTS.forEach((variant) => controllers[variant]?.abort());
  }, []);

  // Both answers are requested at once and shown as soon as each arrives; one failing does
  // not hide the other. The LLM timeout of the API client allows for Ollama queueing them.
  const requestAnswer = async (variant: Variant, text: string) => {
    controllersRef.current[variant]?.abort();
    const controller = new AbortController();
    controllersRef.current[variant] = controller;
    setAnswers((prev) => ({ ...prev, [variant]: { status: 'loading' } }));

    try {
      const response = await apiClient.askQuestion(
        { question: text, use_kg_expansion: variant === 'kg', top_k: 5 },
        subject,
        { signal: controller.signal }
      );
      setAnswers((prev) => ({ ...prev, [variant]: { status: 'success', response } }));
    } catch (error) {
      if (isAbortError(error)) return;
      setAnswers((prev) => ({
        ...prev,
        [variant]: { status: 'error', message: describeError(error) },
      }));
    }
  };

  const handleCompare = (e: React.FormEvent) => {
    e.preventDefault();
    const text = question.trim();
    if (!text) return;

    setAskedQuestion(text);
    VARIANTS.forEach((variant) => void requestAnswer(variant, text));
  };

  const isLoading = VARIANTS.some((variant) => answers[variant]?.status === 'loading');
  const hasResults = VARIANTS.some((variant) => answers[variant] !== undefined);
  const hasAnswer = VARIANTS.some((variant) => answers[variant]?.status === 'success');
  const exampleQuestions = SUBJECT_EXAMPLES[subject] || SUBJECT_EXAMPLES.us_history;

  return (
    <>
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
              maxLength={500}
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
                  disabled={isLoading}
                  className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded-full hover:bg-gray-200 disabled:opacity-50 transition-colors"
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
                <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />
                <span>Comparing...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-5 h-5" aria-hidden="true" />
                <span>Compare Approaches</span>
              </>
            )}
          </button>
        </form>
      </div>

      {/* Comparison Results */}
      {hasResults && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* With KG Expansion */}
          <section
            aria-labelledby="answer-kg-heading"
            className="bg-white rounded-lg shadow-md border-2 border-green-300 overflow-hidden"
          >
            <div className="bg-green-50 border-b border-green-200 px-6 py-4">
              <div className="flex items-center gap-2">
                <Network className="w-5 h-5 text-green-600" aria-hidden="true" />
                <h3 id="answer-kg-heading" className="text-lg font-semibold text-green-900">
                  With KG Expansion
                </h3>
              </div>
              <p className="text-sm text-green-700 mt-1">
                Enhanced with knowledge graph relationships
              </p>
            </div>
            <div className="p-6">
              <AnswerPanel
                state={answers.kg}
                showKGInfo={true}
                spinnerClassName="text-green-600"
                onRetry={() => void requestAnswer('kg', askedQuestion)}
              />
            </div>
          </section>

          {/* Without KG Expansion */}
          <section
            aria-labelledby="answer-plain-heading"
            className="bg-white rounded-lg shadow-md border-2 border-gray-300 overflow-hidden"
          >
            <div className="bg-gray-50 border-b border-gray-200 px-6 py-4">
              <div className="flex items-center gap-2">
                <h3 id="answer-plain-heading" className="text-lg font-semibold text-gray-900">
                  Regular RAG
                </h3>
              </div>
              <p className="text-sm text-gray-700 mt-1">
                Standard semantic search without KG
              </p>
            </div>
            <div className="p-6">
              <AnswerPanel
                state={answers.plain}
                showKGInfo={false}
                spinnerClassName="text-gray-600"
                onRetry={() => void requestAnswer('plain', askedQuestion)}
              />
            </div>
          </section>
        </div>
      )}

      {/* Explanation */}
      {hasAnswer && (
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
    </>
  );
}

interface AnswerPanelProps {
  state: AnswerState | undefined;
  showKGInfo: boolean;
  spinnerClassName: string;
  onRetry: () => void;
}

function AnswerPanel({ state, showKGInfo, spinnerClassName, onRetry }: AnswerPanelProps) {
  if (!state || state.status === 'loading') {
    return (
      <div className="flex items-center justify-center h-32" role="status">
        <Loader2 className={`w-8 h-8 animate-spin ${spinnerClassName}`} aria-hidden="true" />
        <span className="sr-only">Generating answer</span>
      </div>
    );
  }
  if (state.status === 'error') {
    return <ErrorMessage title="Unable to get this answer." message={state.message} onRetry={onRetry} />;
  }
  return <ComparisonResult response={state.response} showKGInfo={showKGInfo} />;
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
        <MarkdownContent>{response.answer}</MarkdownContent>
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
