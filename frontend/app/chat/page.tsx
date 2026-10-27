'use client';

import { Suspense, useEffect, useEffectEvent, useId, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import { describeError, isAbortError } from '@/lib/api-errors';
import type { KGExpansionStatus, QuestionResponse, Source, StreamMetadata } from '@/lib/types';
import {
  Send,
  Loader2,
  Network,
  ExternalLink,
  MapPin,
  AlertCircle,
  RefreshCw,
  Cpu,
} from 'lucide-react';
import { useAppStore } from '@/lib/store';
import MarkdownContent from '@/components/MarkdownContent';
import PageHeader from '@/components/PageHeader';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  /** Assistant messages: the question they answer (used by Retry). */
  question?: string;
  response?: QuestionResponse;
  isStreaming?: boolean;
  /** Why the answer failed. */
  error?: string;
}

/** The page fills the viewport below the nav bar; the conversation scrolls inside it. */
const PAGE_HEIGHT = 'h-[calc(100dvh-theme(spacing.nav))]';

const withoutFinalPeriod = (text: string) => text.replace(/\.+$/, '');

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="max-w-3xl rounded-lg px-6 py-4 bg-white border border-gray-200 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex gap-1" aria-hidden="true">
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          <span className="text-sm text-gray-500">Thinking...</span>
        </div>
      </div>
    </div>
  );
}

function ChatPageContent() {
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get('question');

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [useKgExpansion, setUseKgExpansion] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const nextMessageIdRef = useRef(0);

  // Zustand store for cross-page state
  const currentSubject = useAppStore((state) => state.currentSubject);
  const setLastQuery = useAppStore((state) => state.setLastQuery);
  const setHighlightedConcepts = useAppStore((state) => state.setHighlightedConcepts);

  // Abort any in-flight stream on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isThinking]);

  const updateMessage = (id: number, update: (message: Message) => Message) => {
    setMessages((prev) => prev.map((message) => (message.id === id ? update(message) : message)));
  };

  /** Stream the answer to `question` into the assistant message `assistantId`. */
  const streamAnswer = async (assistantId: number, question: string) => {
    // Abort any previous stream
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setIsLoading(true);
    setIsThinking(true);

    // Metadata to collect during streaming
    let metadata = null as StreamMetadata | null;

    try {
      await apiClient.askQuestionStream(
        {
          question,
          use_kg_expansion: useKgExpansion,
          top_k: 5,
        },
        currentSubject,
        {
          onMetadata: (data) => {
            metadata = data;
            setIsThinking(false);

            // Store expanded concepts for cross-page highlighting
            if (data.expanded_concepts && data.expanded_concepts.length > 0) {
              setHighlightedConcepts(data.expanded_concepts);
            }
            setLastQuery(question);
          },
          onToken: (token) => {
            setIsThinking(false);
            updateMessage(assistantId, (message) => ({
              ...message,
              content: message.content + token,
            }));
          },
        },
        controller.signal
      );

      // Finalize the streamed message with the full response metadata
      updateMessage(assistantId, (message) => ({
        ...message,
        isStreaming: false,
        response: {
          question,
          answer: message.content,
          sources: metadata?.sources ?? [],
          expanded_concepts: metadata?.expanded_concepts ?? null,
          kg_expansion_status: metadata?.kg_expansion_status,
          retrieved_count: metadata?.retrieved_count ?? 0,
          window_expanded_count: metadata?.window_expanded_count ?? null,
          model: metadata?.model ?? '',
          attribution: metadata?.attribution ?? '',
        },
      }));
    } catch (error) {
      // A newer question or leaving the page cancelled this stream
      if (isAbortError(error)) return;
      updateMessage(assistantId, (message) => ({
        ...message,
        isStreaming: false,
        error: describeError(error),
      }));
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setIsLoading(false);
        setIsThinking(false);
      }
    }
  };

  const handleAskQuestion = (question: string) => {
    const text = question.trim();
    if (!text) return;

    const userId = ++nextMessageIdRef.current;
    const assistantId = ++nextMessageIdRef.current;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '', question: text, isStreaming: true },
    ]);
    setInput('');
    void streamAnswer(assistantId, text);
  };

  const handleRetry = (message: Message) => {
    if (!message.question || isLoading) return;
    updateMessage(message.id, (current) => ({
      ...current,
      content: '',
      error: undefined,
      response: undefined,
      isStreaming: true,
    }));
    void streamAnswer(message.id, message.question);
  };

  // Ask the question from the URL (e.g. "Ask the tutor" links). Deferred to a task so that the
  // development-mode double mount of StrictMode asks it only once.
  const askInitialQuestion = useEffectEvent((question: string) => handleAskQuestion(question));
  useEffect(() => {
    if (!initialQuestion) return;
    const timer = setTimeout(() => askInitialQuestion(initialQuestion), 0);
    return () => clearTimeout(timer);
  }, [initialQuestion]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleAskQuestion(input);
  };

  const SUBJECT_EXAMPLES: Record<string, string[]> = {
    us_history: [
      'What caused the American Revolution?',
      'Explain the significance of the Constitution',
      'How did the Civil War affect American society?',
      'What was the impact of Industrialization?',
    ],
    economics: [
      'How do supply and demand determine prices?',
      'What is the role of the Federal Reserve?',
      'Explain the causes of inflation',
      'What is comparative advantage in trade?',
    ],
    biology: [
      'What is the process of photosynthesis?',
      'How does DNA replication work?',
      'Explain natural selection and evolution',
      'What are the stages of cellular respiration?',
    ],
    world_history: [
      'What caused the fall of the Roman Empire?',
      'Explain the impact of the Renaissance',
      'How did colonialism shape the modern world?',
      'What were the causes of World War I?',
    ],
  };
  const exampleQuestions = SUBJECT_EXAMPLES[currentSubject] || SUBJECT_EXAMPLES.us_history;

  return (
    <div className={`flex ${PAGE_HEIGHT} flex-col bg-gray-50`}>
      {/* Header, with the KG expansion toggle: the label (and its text) names the checkbox */}
      <PageHeader
        title="AI Tutor Chat"
        maxWidthClassName="max-w-5xl"
        className="shrink-0"
        actions={
          <label className="flex items-center gap-2 cursor-pointer">
            <Network
              className={`w-5 h-5 ${useKgExpansion ? 'text-primary-600' : 'text-gray-400'}`}
              aria-hidden="true"
            />
            <input
              type="checkbox"
              className="sr-only peer"
              checked={useKgExpansion}
              onChange={(e) => setUseKgExpansion(e.target.checked)}
            />
            <span
              aria-hidden="true"
              className="relative w-11 h-6 bg-gray-200 peer-focus-visible:outline-none peer-focus-visible:ring-4 peer-focus-visible:ring-primary-300 rounded-full peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"
            ></span>
            <span className="text-sm font-medium text-gray-700">KG Expansion</span>
          </label>
        }
      />

      {/* Chat Area: min-h-0 lets the message list scroll instead of growing the page */}
      <main id="main-content" className="flex min-h-0 flex-1 flex-col max-w-5xl mx-auto w-full">
        {/* Messages: a polite live region, busy while an answer streams in */}
        <div
          role="log"
          aria-live="polite"
          aria-busy={isLoading}
          aria-label="Conversation"
          className="flex-1 overflow-y-auto px-4 py-6 space-y-6"
        >
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center max-w-2xl">
                <Network className="w-16 h-16 text-primary-600 mx-auto mb-4" aria-hidden="true" />
                <h2 className="text-2xl font-bold text-gray-900 mb-2">
                  Welcome to the AI Tutor!
                </h2>
                <p className="text-gray-600 mb-6">
                  Ask me anything about your selected subject. I use knowledge graph-aware RAG
                  to provide comprehensive answers with citations from OpenStax textbooks.
                </p>

                {/* Example Questions */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {exampleQuestions.map((q, idx) => (
                    <button
                      key={idx}
                      type="button"
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
            messages.map((message) => (
              <div
                key={message.id}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-3xl rounded-lg px-6 py-4 ${message.role === 'user'
                      ? 'bg-primary-600 text-white'
                      : 'bg-white border border-gray-200 shadow-sm'
                    }`}
                >
                  {message.role === 'user' ? (
                    <p>{message.content}</p>
                  ) : (
                    <AssistantMessage
                      content={message.content}
                      response={message.response}
                      isStreaming={message.isStreaming}
                      error={message.error}
                      onRetry={message.question ? () => handleRetry(message) : undefined}
                      retryDisabled={isLoading}
                    />
                  )}
                </div>
              </div>
            ))
          )}

          {/* Thinking indicator — shown while retrieving context before tokens start */}
          {isThinking && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="shrink-0 border-t border-gray-200 bg-white px-4 py-4">
          <form onSubmit={handleSubmit} className="flex gap-3">
            <label htmlFor="chat-question" className="sr-only">
              Your question
            </label>
            <input
              id="chat-question"
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question..."
              maxLength={500}
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              <Send className="w-5 h-5" aria-hidden="true" />
              <span>Send</span>
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

/** Pulsing block at the end of the answer while tokens stream in. */
function StreamingCursor() {
  return (
    <span
      className="ml-0.5 inline-block h-5 w-2 animate-pulse bg-primary-500 align-text-bottom"
      aria-hidden="true"
    />
  );
}

// What KG expansion did for the question (the badge's class strings are literal so Tailwind
// generates them)
const KG_STATUS_BADGES: Record<
  KGExpansionStatus,
  { label: string; title: string; className: string }
> = {
  ok: {
    label: 'KG expansion: ok',
    title:
      'Concepts from the question were found in the knowledge graph and their neighbours were added to the retrieval.',
    className: 'rounded-full border px-2 py-0.5 border-emerald-200 bg-emerald-50 text-emerald-700',
  },
  empty: {
    label: 'KG expansion: no matches',
    title: 'No concept from the question was found in the knowledge graph; plain retrieval was used.',
    className: 'rounded-full border px-2 py-0.5 border-gray-200 bg-gray-50 text-gray-600',
  },
  failed: {
    label: 'KG expansion: failed, plain retrieval',
    title: 'The knowledge graph could not be queried, so the answer comes from plain retrieval.',
    className: 'rounded-full border px-2 py-0.5 border-amber-200 bg-amber-50 text-amber-700',
  },
  disabled: {
    label: 'KG expansion: off',
    title: 'KG expansion was turned off for this question.',
    className: 'rounded-full border px-2 py-0.5 border-gray-200 bg-gray-50 text-gray-600',
  },
};

/** One line on what retrieval did: KG expansion outcome, chunk count, window expansion. */
function RetrievalSummary({ response }: { response: QuestionResponse }) {
  // Backends older than v0.4.0 send no status; an unknown value gets no badge either
  const badge = response.kg_expansion_status
    ? KG_STATUS_BADGES[response.kg_expansion_status]
    : undefined;
  const count = response.retrieved_count;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
      {badge && (
        <span className={badge.className} title={badge.title}>
          {badge.label}
        </span>
      )}
      <span>{`${count} ${count === 1 ? 'chunk' : 'chunks'} retrieved`}</span>
      {typeof response.window_expanded_count === 'number' && (
        <span>{`· ${response.window_expanded_count} after window expansion`}</span>
      )}
    </div>
  );
}

const SOURCE_PREVIEW_LENGTH = 240;

const sourceTitle = (source: Source) => source.section ?? source.module_title ?? 'Source';
const sourceScore = (source: Source) => `${((source.score ?? 0) * 100).toFixed(0)}%`;

/** Numbered source chips; at most one source's text is open at a time. */
function SourceList({ sources }: { sources: Source[] }) {
  const id = useId();
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [showFull, setShowFull] = useState(false);
  const panelId = (index: number) => `${id}-source-${index}`;

  const toggle = (index: number) => {
    setOpenIndex((current) => (current === index ? null : index));
    setShowFull(false);
  };

  const open = openIndex === null ? undefined : sources[openIndex];
  const isLong = open !== undefined && open.text.length > SOURCE_PREVIEW_LENGTH;
  const text =
    open === undefined
      ? ''
      : isLong && !showFull
        ? `${open.text.slice(0, SOURCE_PREVIEW_LENGTH).trimEnd()}…`
        : open.text;

  return (
    <div>
      <ul aria-label="Sources" className="flex flex-wrap gap-1.5">
        {sources.map((source, index) => {
          const isOpen = openIndex === index;
          return (
            <li key={index}>
              <button
                type="button"
                onClick={() => toggle(index)}
                aria-expanded={isOpen}
                aria-controls={panelId(index)}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-left text-xs transition-colors ${
                  isOpen
                    ? 'border-primary-300 bg-primary-50 text-primary-900'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                <span className="sr-only">Source </span>
                <span className="rounded-full bg-gray-100 px-1.5 font-mono text-xs">{index + 1}</span>{' '}
                <span>{sourceTitle(source)}</span>{' '}
                <span className="text-gray-400">{sourceScore(source)}</span>
              </button>
            </li>
          );
        })}
      </ul>

      {open !== undefined && openIndex !== null && (
        <div
          id={panelId(openIndex)}
          className="mt-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm"
        >
          <div className="mb-2 flex flex-wrap items-center gap-x-2 text-xs text-gray-600">
            {open.chapter && <span className="font-medium">{open.chapter}</span>}
            <span className="ml-auto text-gray-500">{`Score: ${sourceScore(open)}`}</span>
          </div>
          <p className="text-gray-700">{text}</p>
          {isLong && (
            <button
              type="button"
              onClick={() => setShowFull((current) => !current)}
              className="mt-2 text-xs font-medium text-primary-700 hover:text-primary-800"
            >
              {showFull ? 'Show less' : 'Show full text'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Assistant Message Component with expanded concepts and sources
interface AssistantMessageProps {
  content: string;
  response?: QuestionResponse;
  isStreaming?: boolean;
  error?: string;
  onRetry?: () => void;
  retryDisabled?: boolean;
}

function AssistantMessage({
  content,
  response,
  isStreaming,
  error,
  onRetry,
  retryDisabled,
}: AssistantMessageProps) {
  const router = useRouter();
  const setHighlightedConcepts = useAppStore((state) => state.setHighlightedConcepts);

  const handleViewOnGraph = () => {
    if (response?.expanded_concepts) {
      setHighlightedConcepts(response.expanded_concepts);
    }
    router.push('/graph');
  };

  return (
    <div className="space-y-4">
      {(content || isStreaming) && (
        <MarkdownContent trailing={isStreaming ? <StreamingCursor /> : undefined}>
          {content}
        </MarkdownContent>
      )}

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" aria-hidden="true" />
          <p className="flex-1 text-sm text-red-700">
            Sorry, I encountered an error: {withoutFinalPeriod(error)}.
          </p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              disabled={retryDisabled}
              className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              Retry
            </button>
          )}
        </div>
      )}

      {response && !isStreaming && (
        <>
          <RetrievalSummary response={response} />

          {/* Expanded Concepts */}
          {response.expanded_concepts && response.expanded_concepts.length > 0 && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Network className="w-4 h-4 text-blue-600" aria-hidden="true" />
                  <span className="text-sm font-semibold text-blue-900">
                    KG Expansion: {response.expanded_concepts.length} related concepts
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleViewOnGraph}
                  className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-blue-700 hover:text-blue-900 hover:bg-blue-100 rounded transition-colors"
                >
                  <MapPin className="w-3 h-3" aria-hidden="true" />
                  View on Graph
                </button>
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
            <SourceList sources={response.sources} />
          )}

          {/* Attribution and model */}
          <footer className="mt-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-gray-100 pt-2 text-[11px] text-gray-400">
            <span className="inline-flex items-center gap-1">
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
              {response.attribution}
            </span>
            <span className="inline-flex items-center gap-1">
              <Cpu className="h-3 w-3" aria-hidden="true" />
              {`Model: ${response.model}`}
            </span>
          </footer>
        </>
      )}
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className={`flex ${PAGE_HEIGHT} items-center justify-center bg-gray-50`}>
        <div className="flex items-center gap-2" role="status">
          <Loader2 className="w-8 h-8 animate-spin text-primary-600" aria-hidden="true" />
          <span className="text-gray-600">Loading chat...</span>
        </div>
      </div>
    }>
      <ChatPageContent />
    </Suspense>
  );
}
