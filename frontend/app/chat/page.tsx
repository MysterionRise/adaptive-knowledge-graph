'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import type { QuestionResponse } from '@/lib/types';
import {
  ArrowLeft,
  Send,
  Loader2,
  Network,
  BookOpen,
  ExternalLink,
} from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  response?: QuestionResponse;
}

function ChatPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get('question');

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [useKgExpansion, setUseKgExpansion] = useState(true);

  // Ask initial question if provided in URL
  useEffect(() => {
    if (initialQuestion && messages.length === 0) {
      handleAskQuestion(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  const handleAskQuestion = async (question: string) => {
    if (!question.trim()) return;

    // Add user message
    const userMessage: Message = {
      role: 'user',
      content: question,
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await apiClient.askQuestion({
        question,
        use_kg_expansion: useKgExpansion,
        top_k: 5,
      });

      // Add assistant response
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        response,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error: any) {
      console.error('Error asking question:', error);
      const errorMessage: Message = {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${error.detail || 'Unknown error'}. Please try again.`,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleAskQuestion(input);
  };

  const exampleQuestions = [
    'What is photosynthesis?',
    'Explain cellular respiration',
    'How does DNA replication work?',
    'What is the difference between mitosis and meiosis?',
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex flex-col">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
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
                <h1 className="text-2xl font-bold text-gray-900">AI Tutor Chat</h1>
                <p className="text-sm text-gray-600">
                  Ask questions about Biology concepts
                </p>
              </div>
            </div>

            {/* KG Expansion Toggle */}
            <div className="flex items-center gap-2">
              <Network
                className={`w-5 h-5 ${useKgExpansion ? 'text-primary-600' : 'text-gray-400'}`}
              />
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={useKgExpansion}
                  onChange={(e) => setUseKgExpansion(e.target.checked)}
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
              </label>
              <span className="text-sm font-medium text-gray-700">
                KG Expansion
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Chat Area */}
      <main className="flex-1 overflow-hidden flex flex-col max-w-5xl mx-auto w-full">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center max-w-2xl">
                <Network className="w-16 h-16 text-primary-600 mx-auto mb-4" />
                <h2 className="text-2xl font-bold text-gray-900 mb-2">
                  Welcome to the AI Tutor!
                </h2>
                <p className="text-gray-600 mb-6">
                  Ask me anything about Biology. I use knowledge graph-aware RAG
                  to provide comprehensive answers with citations from OpenStax
                  Biology 2e.
                </p>

                {/* Example Questions */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {exampleQuestions.map((q, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleAskQuestion(q)}
                      className="px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-primary-300 hover:shadow-md transition-all text-left text-sm text-gray-700"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            messages.map((message, idx) => (
              <div
                key={idx}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-3xl rounded-lg px-6 py-4 ${message.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-white border border-gray-200 shadow-sm'
                    }`}
                >
                  {message.role === 'user' ? (
                    <p>{message.content}</p>
                  ) : (
                    <AssistantMessage
                      content={message.content}
                      response={message.response}
                    />
                  )}
                </div>
              </div>
            ))
          )}

          {/* Loading indicator */}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-white border border-gray-200 rounded-lg px-6 py-4 shadow-sm">
                <div className="flex items-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin text-primary-600" />
                  <span className="text-gray-600">Thinking...</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-200 bg-white px-4 py-4">
          <form onSubmit={handleSubmit} className="flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about Biology..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              <Send className="w-5 h-5" />
              <span>Send</span>
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

// Assistant Message Component with expanded concepts and sources
interface AssistantMessageProps {
  content: string;
  response?: QuestionResponse;
}

function AssistantMessage({ content, response }: AssistantMessageProps) {
  const [showSources, setShowSources] = useState(false);

  return (
    <div className="space-y-4">
      <p className="text-gray-800 whitespace-pre-wrap">{content}</p>

      {response && (
        <>
          {/* Expanded Concepts */}
          {response.expanded_concepts && response.expanded_concepts.length > 0 && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Network className="w-4 h-4 text-blue-600" />
                <span className="text-sm font-semibold text-blue-900">
                  KG Expansion: {response.expanded_concepts.length} related concepts
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {response.expanded_concepts.map((concept, idx) => (
                  <span
                    key={idx}
                    className="inline-block px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full"
                  >
                    {concept}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Sources */}
          {response.sources && response.sources.length > 0 && (
            <div className="mt-4">
              <button
                onClick={() => setShowSources(!showSources)}
                className="flex items-center gap-2 text-sm font-semibold text-gray-700 hover:text-gray-900"
              >
                <BookOpen className="w-4 h-4" />
                <span>
                  {showSources ? 'Hide' : 'Show'} Sources ({response.sources.length})
                </span>
              </button>

              {showSources && (
                <div className="mt-3 space-y-2">
                  {response.sources.map((source, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-gray-50 border border-gray-200 rounded-lg text-sm"
                    >
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2 text-xs text-gray-600">
                          {source.metadata?.chapter && (
                            <span className="font-medium">{source.metadata.chapter}</span>
                          )}
                          {source.metadata?.section && (
                            <span>• {source.metadata.section}</span>
                          )}
                        </div>
                        <span className="text-xs text-gray-500">
                          Score: {((source.score ?? 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-gray-700 text-sm">{source.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Attribution */}
          <div className="mt-4 pt-3 border-t border-gray-200">
            <p className="text-xs text-gray-500 flex items-center gap-1">
              <ExternalLink className="w-3 h-3" />
              {response.attribution}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Model: {response.model}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center">
        <div className="flex items-center gap-2">
          <Loader2 className="w-8 h-8 animate-spin text-primary-600" />
          <span className="text-gray-600">Loading chat...</span>
        </div>
      </div>
    }>
      <ChatPageContent />
    </Suspense>
  );
}
