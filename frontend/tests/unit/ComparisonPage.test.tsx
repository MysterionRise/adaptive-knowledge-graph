import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ComparisonPage from '@/app/comparison/page';
import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';
import type { QuestionResponse } from '@/lib/types';

jest.mock('@/lib/api-client', () => ({
  apiClient: {
    askQuestion: jest.fn(),
  },
}));

jest.mock('@/components/SubjectPicker', () => function MockSubjectPicker() {
  return <div data-testid="subject-picker" />;
});

// react-markdown is ESM-only; the real rendering is covered by the Playwright suite
jest.mock('react-markdown', () => function MockMarkdown({ children }: { children: string }) {
  return <div data-testid="markdown">{children}</div>;
});

const mockAskQuestion = apiClient.askQuestion as jest.Mock;
const initialStoreState = useAppStore.getState();

const kgAnswer: QuestionResponse = {
  question: 'What caused the American Revolution?',
  answer: '**Taxation** without representation:\n\n- Stamp Act\n- Tea Act',
  sources: [
    { text: 'Source one', score: 0.9 },
    { text: 'Source two', score: 0.8 },
  ],
  expanded_concepts: ['Stamp Act', 'Boston Tea Party'],
  retrieved_count: 8,
  model: 'llama3.1:8b',
  attribution: 'OpenStax',
};

const plainAnswer: QuestionResponse = {
  ...kgAnswer,
  answer: 'Colonists opposed British taxes.',
  sources: [{ text: 'Source one', score: 0.9 }],
  expanded_concepts: null,
  retrieved_count: 5,
};

/** Answer by the use_kg_expansion flag of the request. */
function answerWith(kg: () => Promise<QuestionResponse>, plain: () => Promise<QuestionResponse>) {
  mockAskQuestion.mockImplementation((request: { use_kg_expansion: boolean }) =>
    request.use_kg_expansion ? kg() : plain()
  );
}

const questionInput = () => screen.getByLabelText('Ask a question to compare both approaches:');
const compareButton = () => screen.getByRole('button', { name: /Compare Approaches|Comparing/ });
const kgPanel = () => screen.getByRole('region', { name: 'With KG Expansion' });
const plainPanel = () => screen.getByRole('region', { name: 'Regular RAG' });

function compare(question = 'What caused the American Revolution?') {
  fireEvent.change(questionInput(), { target: { value: question } });
  fireEvent.click(compareButton());
}

describe('ComparisonPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    answerWith(
      () => Promise.resolve(kgAnswer),
      () => Promise.resolve(plainAnswer)
    );
  });

  describe('form', () => {
    it('renders the heading, the question field and the subject picker', () => {
      render(<ComparisonPage />);

      expect(
        screen.getByRole('heading', { level: 1, name: 'KG-RAG vs Regular RAG Comparison' })
      ).toBeInTheDocument();
      expect(questionInput()).toHaveAttribute('placeholder', 'e.g., What caused the American Revolution?');
      expect(screen.getByTestId('subject-picker')).toBeInTheDocument();
    });

    it('enables Compare only when a question is entered', () => {
      render(<ComparisonPage />);

      expect(compareButton()).toBeDisabled();
      fireEvent.change(questionInput(), { target: { value: '   ' } });
      expect(compareButton()).toBeDisabled();
      fireEvent.change(questionInput(), { target: { value: 'Why?' } });
      expect(compareButton()).toBeEnabled();
    });

    it('offers example questions for the current subject', () => {
      useAppStore.setState({ currentSubject: 'economics' });

      render(<ComparisonPage />);

      fireEvent.click(screen.getByRole('button', { name: 'Explain the causes of inflation' }));
      expect(questionInput()).toHaveValue('Explain the causes of inflation');
    });

    it('falls back to the US History examples for other subjects', () => {
      useAppStore.setState({ currentSubject: 'chemistry' });

      render(<ComparisonPage />);

      expect(screen.getByRole('button', { name: 'What caused the American Revolution?' })).toBeInTheDocument();
    });
  });

  describe('comparing', () => {
    it('asks the question with and without KG expansion', async () => {
      useAppStore.setState({ currentSubject: 'economics' });
      render(<ComparisonPage />);

      compare('  How do prices form?  ');

      await screen.findByText('Why KG Expansion Matters');
      expect(mockAskQuestion).toHaveBeenCalledTimes(2);
      expect(mockAskQuestion).toHaveBeenCalledWith(
        { question: 'How do prices form?', use_kg_expansion: true, top_k: 5 },
        'economics',
        { signal: expect.any(AbortSignal) }
      );
      expect(mockAskQuestion).toHaveBeenCalledWith(
        { question: 'How do prices form?', use_kg_expansion: false, top_k: 5 },
        'economics',
        { signal: expect.any(AbortSignal) }
      );
    });

    it('renders both answers as Markdown with their details', async () => {
      render(<ComparisonPage />);

      compare();

      const kg = await screen.findByRole('region', { name: 'With KG Expansion' });
      expect(within(kg).getByTestId('markdown')).toHaveTextContent('**Taxation** without representation');
      expect(within(kg).getByText('Expanded Concepts (2):')).toBeInTheDocument();
      expect(within(kg).getByText('Boston Tea Party')).toBeInTheDocument();
      expect(within(kg).getByText('Retrieved Chunks').nextSibling).toHaveTextContent('8');
      expect(within(kg).getByText('Concepts Used').nextSibling).toHaveTextContent('2');
      expect(within(kg).getByText(/Based on 2 sources from the knowledge base/)).toBeInTheDocument();

      const plain = plainPanel();
      expect(within(plain).getByTestId('markdown')).toHaveTextContent('Colonists opposed British taxes.');
      expect(within(plain).queryByText(/Expanded Concepts/)).not.toBeInTheDocument();
      expect(within(plain).getByText('Concepts Used').nextSibling).toHaveTextContent('0');
      expect(within(plain).getByText(/Based on 1 source from the knowledge base/)).toBeInTheDocument();
    });

    it('shows each answer as soon as it arrives', async () => {
      let answerPlain!: (response: QuestionResponse) => void;
      answerWith(
        () => Promise.resolve(kgAnswer),
        () => new Promise((resolve) => (answerPlain = resolve))
      );
      render(<ComparisonPage />);

      compare();

      await within(kgPanel()).findByTestId('markdown');
      expect(within(plainPanel()).getByRole('status')).toHaveTextContent('Generating answer');
      expect(compareButton()).toHaveTextContent('Comparing...');
      expect(compareButton()).toBeDisabled();
      expect(questionInput()).toBeDisabled();

      await act(async () => answerPlain(plainAnswer));

      expect(within(plainPanel()).getByTestId('markdown')).toBeInTheDocument();
      expect(compareButton()).toHaveTextContent('Compare Approaches');
    });

    it('shows a failed answer with its error while keeping the other one', async () => {
      answerWith(
        () => Promise.resolve(kgAnswer),
        () => Promise.reject(new ApiError('timeout', 'The server did not respond within 180 seconds.'))
      );
      render(<ComparisonPage />);

      compare();

      const alert = await within(plainPanel()).findByRole('alert');
      expect(alert).toHaveTextContent('Unable to get this answer.');
      expect(alert).toHaveTextContent('The server did not respond within 180 seconds.');
      expect(within(kgPanel()).getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('Why KG Expansion Matters')).toBeInTheDocument();
    });

    it('retries only the failed answer', async () => {
      let plainAttempts = 0;
      answerWith(
        () => Promise.resolve(kgAnswer),
        () =>
          ++plainAttempts === 1
            ? Promise.reject(new ApiError('http', 'LLM service temporarily unavailable', { status: 503 }))
            : Promise.resolve(plainAnswer)
      );
      render(<ComparisonPage />);
      compare();

      fireEvent.click(await within(plainPanel()).findByRole('button', { name: 'Retry' }));

      expect(await within(plainPanel()).findByTestId('markdown')).toHaveTextContent(
        'Colonists opposed British taxes.'
      );
      expect(mockAskQuestion).toHaveBeenCalledTimes(3);
      expect(mockAskQuestion).toHaveBeenLastCalledWith(
        expect.objectContaining({ question: 'What caused the American Revolution?', use_kg_expansion: false }),
        'us_history',
        expect.anything()
      );
    });

    it('shows both errors when the backend fails', async () => {
      const failure = () => Promise.reject(new ApiError('http', 'An internal error occurred', { status: 500 }));
      answerWith(failure, failure);
      render(<ComparisonPage />);

      compare();

      await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2));
      for (const alert of screen.getAllByRole('alert')) {
        expect(alert).toHaveTextContent('An internal error occurred');
      }
      expect(screen.queryByText('Why KG Expansion Matters')).not.toBeInTheDocument();
    });

    it('describes unexpected errors generically', async () => {
      answerWith(
        () => Promise.resolve(kgAnswer),
        () => Promise.reject(new TypeError('x is undefined'))
      );
      render(<ComparisonPage />);

      compare();

      expect(await within(plainPanel()).findByRole('alert')).toHaveTextContent(
        'Something went wrong. Please try again.'
      );
    });
  });

  describe('cancellation', () => {
    it('starts over and cancels running requests when the subject changes', async () => {
      mockAskQuestion.mockImplementation(() => new Promise(() => {}));
      render(<ComparisonPage />);
      compare();
      const signals: AbortSignal[] = mockAskQuestion.mock.calls.map((call) => call[2].signal);

      act(() => useAppStore.getState().setCurrentSubject('economics'));

      expect(signals.every((signal) => signal.aborted)).toBe(true);
      expect(questionInput()).toHaveValue('');
      expect(screen.queryByRole('region', { name: 'With KG Expansion' })).not.toBeInTheDocument();
    });

    it('cancels running requests when the page is left', () => {
      mockAskQuestion.mockImplementation(() => new Promise(() => {}));
      const { unmount } = render(<ComparisonPage />);
      compare();
      const signals: AbortSignal[] = mockAskQuestion.mock.calls.map((call) => call[2].signal);

      unmount();

      expect(signals.every((signal) => signal.aborted)).toBe(true);
    });

    it('ignores an answer that arrives after it was cancelled', async () => {
      const replies: Array<(error: unknown) => void> = [];
      mockAskQuestion.mockImplementation(
        () => new Promise((_resolve, reject) => replies.push(reject))
      );
      render(<ComparisonPage />);
      compare();

      act(() => useAppStore.getState().setCurrentSubject('economics'));
      await act(async () => replies.forEach((reject) => reject(new ApiError('aborted', 'The request was cancelled.'))));

      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
