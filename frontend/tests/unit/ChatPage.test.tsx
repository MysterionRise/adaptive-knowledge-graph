import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatPage from '@/app/chat/page';
import { apiClient } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';

// Mock the API client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    askQuestion: jest.fn(),
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

// Mock the Skeleton component
jest.mock('@/components/Skeleton', () => ({
  ChatMessageSkeleton: () => <div data-testid="chat-skeleton">Loading...</div>,
}));

// Reset store between tests
const initialStoreState = useAppStore.getState();

describe('ChatPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    mockSearchParams.delete('question');
  });

  describe('Initial Rendering', () => {
    it('renders the chat page header', () => {
      render(<ChatPage />);

      expect(screen.getByText('AI Tutor Chat')).toBeInTheDocument();
      expect(screen.getByText(/Ask questions about US History/i)).toBeInTheDocument();
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

    it('renders chat input form', () => {
      render(<ChatPage />);

      expect(screen.getByPlaceholderText(/Ask a question about US History/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
    });

    it('renders back button', () => {
      render(<ChatPage />);

      expect(screen.getByRole('button', { name: /back to home/i })).toBeInTheDocument();
    });

    it('renders KG expansion toggle', () => {
      render(<ChatPage />);

      expect(screen.getByText('KG Expansion')).toBeInTheDocument();
      expect(screen.getByRole('checkbox')).toBeInTheDocument();
    });
  });

  describe('Navigation', () => {
    it('navigates back to home when back button is clicked', () => {
      render(<ChatPage />);

      const backButton = screen.getByRole('button', { name: /back to home/i });
      fireEvent.click(backButton);

      expect(mockPush).toHaveBeenCalledWith('/');
    });
  });

  describe('KG Expansion Toggle', () => {
    it('has KG expansion enabled by default', () => {
      render(<ChatPage />);

      const toggle = screen.getByRole('checkbox');
      expect(toggle).toBeChecked();
    });

    it('toggles KG expansion when clicked', () => {
      render(<ChatPage />);

      const toggle = screen.getByRole('checkbox');
      fireEvent.click(toggle);

      expect(toggle).not.toBeChecked();
    });
  });

  describe('Sending Messages', () => {
    it('sends message when form is submitted', async () => {
      const mockResponse = {
        question: 'Test question',
        answer: 'Test answer',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      const sendButton = screen.getByRole('button', { name: /send/i });

      await userEvent.type(input, 'What is history?');
      fireEvent.click(sendButton);

      await waitFor(() => {
        expect(apiClient.askQuestion).toHaveBeenCalledWith({
          question: 'What is history?',
          use_kg_expansion: true,
          top_k: 5,
        });
      });
    });

    it('displays user message after sending', async () => {
      const mockResponse = {
        question: 'Test question',
        answer: 'Test answer',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('My question')).toBeInTheDocument();
      });
    });

    it('displays assistant response after receiving', async () => {
      const mockResponse = {
        question: 'Test question',
        answer: 'This is the assistant response',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('This is the assistant response')).toBeInTheDocument();
      });
    });

    it('clears input after sending', async () => {
      const mockResponse = {
        question: 'Test question',
        answer: 'Test answer',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i) as HTMLInputElement;
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(input.value).toBe('');
      });
    });

    it('disables input while loading', async () => {
      (apiClient.askQuestion as jest.Mock).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(input).toBeDisabled();
      });
    });

    it('shows loading skeleton while waiting for response', async () => {
      (apiClient.askQuestion as jest.Mock).mockImplementation(
        () => new Promise(() => {})
      );

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByTestId('chat-skeleton')).toBeInTheDocument();
      });
    });

    it('does not send empty messages', async () => {
      render(<ChatPage />);

      const sendButton = screen.getByRole('button', { name: /send/i });
      expect(sendButton).toBeDisabled();

      fireEvent.click(sendButton);

      expect(apiClient.askQuestion).not.toHaveBeenCalled();
    });

    it('does not send whitespace-only messages', async () => {
      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, '   ');

      const sendButton = screen.getByRole('button', { name: /send/i });
      expect(sendButton).toBeDisabled();
    });
  });

  describe('Example Questions', () => {
    it('sends example question when clicked', async () => {
      const mockResponse = {
        question: 'What caused the American Revolution?',
        answer: 'The American Revolution was caused by...',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const exampleButton = screen.getByText('What caused the American Revolution?');
      fireEvent.click(exampleButton);

      await waitFor(() => {
        expect(apiClient.askQuestion).toHaveBeenCalledWith({
          question: 'What caused the American Revolution?',
          use_kg_expansion: true,
          top_k: 5,
        });
      });
    });
  });

  describe('Error Handling', () => {
    it('displays error message when API call fails', async () => {
      (apiClient.askQuestion as jest.Mock).mockRejectedValueOnce({
        detail: 'Server error',
      });

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText(/Sorry, I encountered an error/i)).toBeInTheDocument();
      });
    });

    it('handles unknown error format', async () => {
      (apiClient.askQuestion as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText(/Sorry, I encountered an error/i)).toBeInTheDocument();
      });
    });
  });

  describe('Response Display', () => {
    it('displays expanded concepts when present', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [],
        expanded_concepts: ['Concept 1', 'Concept 2', 'Concept 3'],
        retrieved_count: 3,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('KG Expansion: 3 related concepts')).toBeInTheDocument();
        expect(screen.getByText('Concept 1')).toBeInTheDocument();
        expect(screen.getByText('Concept 2')).toBeInTheDocument();
        expect(screen.getByText('Concept 3')).toBeInTheDocument();
      });
    });

    it('displays attribution', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax US History',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('OpenStax US History')).toBeInTheDocument();
      });
    });

    it('displays model name', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText(/Model: llama3.1:8b/i)).toBeInTheDocument();
      });
    });
  });

  describe('Sources Display', () => {
    it('shows sources toggle button when sources exist', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [
          {
            text: 'Source text',
            score: 0.95,
            metadata: { chapter: 'Chapter 1', section: 'Section A' },
          },
        ],
        expanded_concepts: [],
        retrieved_count: 1,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText(/Show Sources/i)).toBeInTheDocument();
      });
    });

    it('toggles sources visibility', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [
          {
            text: 'Source content here',
            score: 0.95,
            metadata: { chapter: 'Chapter 1', section: 'Section A' },
          },
        ],
        expanded_concepts: [],
        retrieved_count: 1,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText(/Show Sources/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/Show Sources/i));

      await waitFor(() => {
        expect(screen.getByText('Source content here')).toBeInTheDocument();
        expect(screen.getByText('Hide Sources (1)')).toBeInTheDocument();
      });
    });
  });

  describe('View on Graph', () => {
    it('shows View on Graph button when concepts exist', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [],
        expanded_concepts: ['Concept 1'],
        retrieved_count: 1,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('View on Graph')).toBeInTheDocument();
      });
    });

    it('navigates to graph page when View on Graph is clicked', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [],
        expanded_concepts: ['Concept 1'],
        retrieved_count: 1,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('View on Graph')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('View on Graph'));

      expect(mockPush).toHaveBeenCalledWith('/graph');
    });
  });

  describe('Store Integration', () => {
    it('updates highlighted concepts in store', async () => {
      const mockResponse = {
        question: 'Test',
        answer: 'Answer',
        sources: [],
        expanded_concepts: ['Concept A', 'Concept B'],
        retrieved_count: 2,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'Question');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        const state = useAppStore.getState();
        expect(state.highlightedConcepts).toEqual(['Concept A', 'Concept B']);
      });
    });

    it('updates last query in store', async () => {
      const mockResponse = {
        question: 'My test query',
        answer: 'Answer',
        sources: [],
        expanded_concepts: [],
        retrieved_count: 0,
        model: 'llama3.1:8b',
        attribution: 'OpenStax',
      };

      (apiClient.askQuestion as jest.Mock).mockResolvedValueOnce(mockResponse);

      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/Ask a question about US History/i);
      await userEvent.type(input, 'My test query');
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        const state = useAppStore.getState();
        expect(state.lastQuery).toBe('My test query');
      });
    });
  });
});
