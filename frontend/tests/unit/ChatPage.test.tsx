import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatPage from '@/app/chat/page';
import { apiClient, type StreamCallbacks } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';
import type { Source } from '@/lib/types';

// Mock scrollIntoView (not implemented in jsdom)
Element.prototype.scrollIntoView = jest.fn();

// Mock the API client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    askQuestionStream: jest.fn(),
  },
}));

// Mock next/navigation
const mockPush = jest.fn();
const mockSearchParams = new URLSearchParams();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
  }),
  useSearchParams: () => mockSearchParams,
}));

// Mock SubjectPicker
jest.mock('@/components/SubjectPicker', () => {
  return function MockSubjectPicker() {
    return <div data-testid="subject-picker">Subject Picker</div>;
  };
});

const mockStream = apiClient.askQuestionStream as jest.Mock;

// Reset store between tests
const initialStoreState = useAppStore.getState();

interface StreamedAnswer {
  answer: string;
  sources?: Source[];
  expanded_concepts?: string[] | null;
  retrieved_count?: number;
  model?: string;
  attribution?: string;
}

/** Stream the answer through the callbacks and finish (the promise resolves when done). */
function mockStreamResponse({
  answer,
  sources = [],
  expanded_concepts = [],
  retrieved_count = 0,
  model = 'llama3.1:8b',
  attribution = 'OpenStax US History',
}: StreamedAnswer) {
  return mockStream.mockImplementation(
    async (_request: unknown, _subject: unknown, callbacks: StreamCallbacks) => {
      callbacks.onMetadata?.({
        type: 'metadata',
        sources,
        expanded_concepts,
        retrieved_count,
        model,
        attribution,
      });
      callbacks.onToken?.(answer);
    }
  );
}

/** A stream that never finishes (until it is aborted). */
function mockStreamHanging() {
  return mockStream.mockImplementation(() => new Promise(() => {}));
}

/** A stream that fails with an API error. */
function mockStreamError(message: string) {
  return mockStream.mockRejectedValue(new ApiError('http', message, { status: 503 }));
}

const questionInput = () => screen.getByRole('textbox', { name: 'Your question' });

/** Run an interaction that starts a stream and let the stream settle inside act(). */
const settle = (interaction: () => void) =>
  act(async () => {
    interaction();
  });

async function ask(question: string) {
  await userEvent.type(questionInput(), question);
  await settle(() => fireEvent.submit(questionInput().closest('form')!));
}

describe('ChatPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockStream.mockReset();
    useAppStore.setState(initialStoreState);
    mockSearchParams.delete('question');
  });

  describe('Initial Rendering', () => {
    it('renders the chat page header', () => {
      render(<ChatPage />);

      expect(screen.getByRole('heading', { level: 1, name: 'AI Tutor Chat' })).toBeInTheDocument();
      expect(screen.getByText(/Ask questions about your selected subject/i)).toBeInTheDocument();
    });

    it('renders welcome message when no messages', () => {
      render(<ChatPage />);

      expect(screen.getByText('Welcome to the AI Tutor!')).toBeInTheDocument();
    });

    it('renders example questions', () => {
      render(<ChatPage />);

      expect(screen.getByText('What caused the American Revolution?')).toBeInTheDocument();
      expect(screen.getByText('Explain the significance of the Constitution')).toBeInTheDocument();
      expect(screen.getByText('How did the Civil War affect American society?')).toBeInTheDocument();
      expect(screen.getByText('What was the impact of Industrialization?')).toBeInTheDocument();
    });

    it('renders example questions of the current subject', () => {
      useAppStore.setState({ currentSubject: 'economics' });

      render(<ChatPage />);

      expect(screen.getByText('How do supply and demand determine prices?')).toBeInTheDocument();
    });

    it('renders a labelled chat input', () => {
      render(<ChatPage />);

      expect(questionInput()).toHaveAttribute('placeholder', 'Ask a question...');
      expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
    });

    it('renders a labelled KG expansion toggle', () => {
      render(<ChatPage />);

      expect(screen.getByRole('checkbox', { name: 'KG Expansion' })).toBeInTheDocument();
    });

    it('renders the conversation as a polite live region', () => {
      render(<ChatPage />);

      const log = screen.getByRole('log', { name: 'Conversation' });
      expect(log).toHaveAttribute('aria-live', 'polite');
      expect(log).toHaveAttribute('aria-busy', 'false');
    });
  });

  describe('KG Expansion Toggle', () => {
    it('has KG expansion enabled by default', () => {
      render(<ChatPage />);

      expect(screen.getByRole('checkbox', { name: 'KG Expansion' })).toBeChecked();
    });

    it('toggles KG expansion from its label', () => {
      render(<ChatPage />);

      fireEvent.click(screen.getByText('KG Expansion'));

      expect(screen.getByRole('checkbox', { name: 'KG Expansion' })).not.toBeChecked();
    });

    it('sends the KG expansion setting with the question', async () => {
      mockStreamResponse({ answer: 'Answer' });
      render(<ChatPage />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'KG Expansion' }));

      await ask('Why?');

      await waitFor(() => expect(mockStream).toHaveBeenCalled());
      expect(mockStream.mock.calls[0][0]).toEqual({ question: 'Why?', use_kg_expansion: false, top_k: 5 });
    });
  });

  describe('Sending Messages', () => {
    it('sends message when form is submitted', async () => {
      mockStreamResponse({ answer: 'Test answer' });

      render(<ChatPage />);

      await userEvent.type(questionInput(), 'What is history?');
      await settle(() => fireEvent.click(screen.getByRole('button', { name: /send/i })));

      await waitFor(() => {
        expect(mockStream).toHaveBeenCalledWith(
          {
            question: 'What is history?',
            use_kg_expansion: true,
            top_k: 5,
          },
          'us_history',
          expect.any(Object),
          expect.any(AbortSignal)
        );
      });
    });

    it('displays the question and the streamed answer', async () => {
      mockStreamResponse({ answer: 'This is the assistant response' });

      render(<ChatPage />);
      await ask('My question');

      expect(await screen.findByText('This is the assistant response')).toBeInTheDocument();
      expect(screen.getByText('My question')).toBeInTheDocument();
    });

    it('clears input after sending', async () => {
      mockStreamResponse({ answer: 'Test answer' });

      render(<ChatPage />);
      await ask('My question');

      await waitFor(() => expect(questionInput()).toHaveValue(''));
    });

    it('disables input and marks the conversation busy while loading', async () => {
      mockStreamHanging();

      render(<ChatPage />);
      await ask('My question');

      await waitFor(() => expect(questionInput()).toBeDisabled());
      expect(screen.getByRole('log')).toHaveAttribute('aria-busy', 'true');
    });

    it('shows thinking indicator while waiting for response', async () => {
      mockStreamHanging();

      render(<ChatPage />);
      await ask('My question');

      expect(await screen.findByText('Thinking...')).toBeInTheDocument();
    });

    it('does not send empty messages', async () => {
      render(<ChatPage />);

      const sendButton = screen.getByRole('button', { name: /send/i });
      expect(sendButton).toBeDisabled();
      fireEvent.submit(questionInput().closest('form')!);

      expect(mockStream).not.toHaveBeenCalled();
    });

    it('does not send whitespace-only messages', async () => {
      render(<ChatPage />);

      await userEvent.type(questionInput(), '   ');

      expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
    });

    it('cancels the stream when the page is left', async () => {
      mockStreamHanging();
      const { unmount } = render(<ChatPage />);
      await ask('My question');
      await waitFor(() => expect(mockStream).toHaveBeenCalled());
      const signal: AbortSignal = mockStream.mock.calls[0][3];

      unmount();

      expect(signal.aborted).toBe(true);
    });
  });

  describe('Question in the URL', () => {
    it('asks the question once on load', async () => {
      mockSearchParams.set('question', 'Explain the Constitution');
      mockStreamResponse({ answer: 'The Constitution is...' });

      render(<ChatPage />);

      expect(await screen.findByText('The Constitution is...')).toBeInTheDocument();
      expect(screen.getByText('Explain the Constitution')).toBeInTheDocument();
      expect(mockStream).toHaveBeenCalledTimes(1);
    });

    it('does not ask when the page is left right away', () => {
      jest.useFakeTimers();
      try {
        mockSearchParams.set('question', 'Explain the Constitution');
        const { unmount } = render(<ChatPage />);

        unmount();
        act(() => jest.runOnlyPendingTimers());

        expect(mockStream).not.toHaveBeenCalled();
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('Example Questions', () => {
    it('sends example question when clicked', async () => {
      mockStreamResponse({ answer: 'The American Revolution was caused by...' });

      render(<ChatPage />);

      await settle(() => fireEvent.click(screen.getByText('What caused the American Revolution?')));

      await waitFor(() => {
        expect(mockStream).toHaveBeenCalledWith(
          {
            question: 'What caused the American Revolution?',
            use_kg_expansion: true,
            top_k: 5,
          },
          'us_history',
          expect.any(Object),
          expect.any(AbortSignal)
        );
      });
    });
  });

  describe('Error Handling', () => {
    it('shows the backend error with a retry action', async () => {
      mockStreamError('LLM service temporarily unavailable');

      render(<ChatPage />);
      await ask('My question');

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent(
        'Sorry, I encountered an error: LLM service temporarily unavailable.'
      );
      expect(questionInput()).toBeEnabled();
    });

    it('answers the question again on retry', async () => {
      mockStreamError('LLM service temporarily unavailable');
      render(<ChatPage />);
      await ask('My question');
      await screen.findByRole('alert');

      mockStreamResponse({ answer: 'Second time lucky' });
      await settle(() => fireEvent.click(screen.getByRole('button', { name: 'Retry' })));

      expect(await screen.findByText('Second time lucky')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(mockStream).toHaveBeenCalledTimes(2);
      expect(mockStream.mock.calls[1][0]).toEqual(
        expect.objectContaining({ question: 'My question' })
      );
      // The question is not repeated in the conversation
      expect(screen.getAllByText('My question')).toHaveLength(1);
    });

    it('keeps a partial answer when the stream fails midway', async () => {
      mockStream.mockImplementation(
        async (_request: unknown, _subject: unknown, callbacks: StreamCallbacks) => {
          callbacks.onToken?.('Partial answer');
          throw new ApiError('stream', 'An error occurred during streaming');
        }
      );

      render(<ChatPage />);
      await ask('My question');

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Sorry, I encountered an error: An error occurred during streaming.'
      );
      expect(screen.getByText('Partial answer')).toBeInTheDocument();
    });

    it('describes unexpected errors generically', async () => {
      mockStream.mockRejectedValue(new TypeError('boom'));

      render(<ChatPage />);
      await ask('My question');

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Sorry, I encountered an error: Something went wrong. Please try again.'
      );
    });
  });

  describe('Response Display', () => {
    it('displays expanded concepts when present', async () => {
      mockStreamResponse({ answer: 'Answer', expanded_concepts: ['Concept 1', 'Concept 2', 'Concept 3'] });

      render(<ChatPage />);
      await ask('Question');

      expect(await screen.findByText('KG Expansion: 3 related concepts')).toBeInTheDocument();
      expect(screen.getByText('Concept 1')).toBeInTheDocument();
      expect(screen.getByText('Concept 2')).toBeInTheDocument();
      expect(screen.getByText('Concept 3')).toBeInTheDocument();
    });

    it('displays attribution and model', async () => {
      mockStreamResponse({ answer: 'Answer', attribution: 'OpenStax US History' });

      render(<ChatPage />);
      await ask('Question');

      expect(await screen.findByText('OpenStax US History')).toBeInTheDocument();
      expect(screen.getByText(/Model: llama3.1:8b/i)).toBeInTheDocument();
    });
  });

  describe('Sources Display', () => {
    const sources: Source[] = [
      {
        text: 'Source content here',
        score: 0.95,
        metadata: { chapter: 'Chapter 1', section: 'Section A' },
      },
    ];

    it('toggles sources visibility', async () => {
      mockStreamResponse({ answer: 'Answer', sources, retrieved_count: 1 });

      render(<ChatPage />);
      await ask('Question');

      const toggle = await screen.findByRole('button', { name: 'Show Sources (1)' });
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(toggle);

      expect(screen.getByText('Source content here')).toBeInTheDocument();
      expect(screen.getByText('Chapter 1')).toBeInTheDocument();
      expect(screen.getByText('Score: 95%')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Hide Sources (1)' })).toHaveAttribute(
        'aria-expanded',
        'true'
      );
    });
  });

  describe('View on Graph', () => {
    it('navigates to graph page with the expanded concepts highlighted', async () => {
      mockStreamResponse({ answer: 'Answer', expanded_concepts: ['Concept 1'] });

      render(<ChatPage />);
      await ask('Question');

      fireEvent.click(await screen.findByRole('button', { name: 'View on Graph' }));

      expect(mockPush).toHaveBeenCalledWith('/graph');
      expect(useAppStore.getState().highlightedConcepts).toEqual(['Concept 1']);
    });
  });

  describe('Store Integration', () => {
    it('updates highlighted concepts and the last query in store', async () => {
      mockStreamResponse({ answer: 'Answer', expanded_concepts: ['Concept A', 'Concept B'] });

      render(<ChatPage />);
      await ask('My test query');

      await waitFor(() => {
        expect(useAppStore.getState()).toMatchObject({
          highlightedConcepts: ['Concept A', 'Concept B'],
          lastQuery: 'My test query',
        });
      });
    });
  });
});
