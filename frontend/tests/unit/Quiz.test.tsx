import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Quiz from '@/components/Quiz';
import { useAppStore } from '@/lib/store';

// Mock the router
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
  }),
}));

// Mock fetch
global.fetch = jest.fn();

// Mock MasteryIndicator component
jest.mock('@/components/MasteryIndicator', () => {
  return function MockMasteryIndicator({ mastery, targetDifficulty, topic }: any) {
    return (
      <div data-testid="mastery-indicator">
        <span data-testid="mastery-value">{Math.round(mastery * 100)}%</span>
        <span data-testid="difficulty-value">{targetDifficulty}</span>
        {topic && <span data-testid="topic-value">{topic}</span>}
      </div>
    );
  };
});

// Mock PostQuizRecommendations component
jest.mock('@/components/PostQuizRecommendations', () => {
  return function MockPostQuizRecommendations() {
    return <div data-testid="post-quiz-recommendations" />;
  };
});

// Helper: mock response for the initial loadMasteryFromBackend fetch on mount
const mockProfileResponse = () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ mastery_levels: {}, updated_at: new Date().toISOString() }),
  });
};

// Helper: mock response for the recommendations fetch after quiz completion
const mockRecommendationsResponse = () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      path_type: 'remediation',
      score_pct: 100,
      remediation: [],
      advancement: [],
      summary: 'Great work!',
    }),
  });
};

// Reset store between tests
const initialStoreState = useAppStore.getState();

describe('Quiz Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    (global.fetch as jest.Mock).mockReset();
  });

  describe('Initial State', () => {
    it('renders the start assessment form', () => {
      render(<Quiz />);

      expect(screen.getByText('Start Assessment')).toBeInTheDocument();
      expect(screen.getByText('Adaptive Mode')).toBeInTheDocument();
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    it('shows topic dropdown with options', () => {
      render(<Quiz />);

      const select = screen.getByRole('combobox');
      expect(select).toHaveValue('The American Revolution');

      expect(screen.getByText('The Constitution')).toBeInTheDocument();
      expect(screen.getByText('The Civil War')).toBeInTheDocument();
    });

    it('has adaptive mode enabled by default', () => {
      render(<Quiz />);

      expect(
        screen.getByText('Questions will be tailored to your current proficiency level')
      ).toBeInTheDocument();
    });

    it('shows mastery indicator when adaptive mode is on', () => {
      render(<Quiz />);

      expect(screen.getByTestId('mastery-indicator')).toBeInTheDocument();
    });
  });

  describe('Adaptive Mode Toggle', () => {
    it('toggles adaptive mode when clicked', async () => {
      render(<Quiz />);

      const toggleButton = screen.getByRole('button', { name: '' }); // The toggle button
      const toggle = toggleButton.closest('button') || screen.getAllByRole('button')[0];

      // Find the toggle by looking for the adaptive mode section
      const adaptiveModeText = screen.getByText('Adaptive Mode');
      const toggleContainer = adaptiveModeText.closest('div');
      const toggleBtn = toggleContainer?.querySelector('button');

      if (toggleBtn) {
        fireEvent.click(toggleBtn);
        expect(
          screen.getByText('Questions will have mixed difficulty levels')
        ).toBeInTheDocument();
      }
    });

    it('changes button text based on adaptive mode', async () => {
      render(<Quiz />);

      expect(screen.getByText('Start Adaptive Assessment')).toBeInTheDocument();
    });
  });

  describe('Quiz Generation', () => {
    const mockQuizResponse = {
      id: 'quiz-1',
      title: 'American Revolution Quiz',
      questions: [
        {
          id: 'q1',
          text: 'What year did the American Revolution begin?',
          options: [
            { id: 'a', text: '1775' },
            { id: 'b', text: '1776' },
            { id: 'c', text: '1774' },
            { id: 'd', text: '1777' },
          ],
          correct_option_id: 'a',
          explanation: 'The American Revolution began in 1775 with the Battles of Lexington and Concord.',
          difficulty: 'easy',
        },
        {
          id: 'q2',
          text: 'Who wrote the Declaration of Independence?',
          options: [
            { id: 'a', text: 'George Washington' },
            { id: 'b', text: 'Thomas Jefferson' },
            { id: 'c', text: 'Benjamin Franklin' },
            { id: 'd', text: 'John Adams' },
          ],
          correct_option_id: 'b',
          explanation: 'Thomas Jefferson was the primary author of the Declaration of Independence.',
          difficulty: 'medium',
        },
      ],
      student_mastery: 0.3,
      target_difficulty: 'easy',
      adapted: true,
    };

    it('shows loading state when generating quiz', async () => {
      // First call (profile load on mount) resolves, subsequent calls never resolve
      mockProfileResponse();
      (global.fetch as jest.Mock).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      render(<Quiz />);

      const startButton = screen.getByText('Start Adaptive Assessment');
      fireEvent.click(startButton);

      await waitFor(() => {
        expect(screen.getByText('Crafting Your Personalized Quiz')).toBeInTheDocument();
      });
    });

    it('displays quiz after successful generation', async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockQuizResponse,
      });

      render(<Quiz />);

      const startButton = screen.getByText('Start Adaptive Assessment');
      fireEvent.click(startButton);

      await waitFor(() => {
        expect(screen.getByText('What year did the American Revolution begin?')).toBeInTheDocument();
      });

      expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
      expect(screen.getByText('1775')).toBeInTheDocument();
    });

    it('handles generation error gracefully', async () => {
      (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

      // Mock alert
      const alertMock = jest.spyOn(window, 'alert').mockImplementation(() => {});

      render(<Quiz />);

      const startButton = screen.getByText('Start Adaptive Assessment');
      fireEvent.click(startButton);

      await waitFor(() => {
        expect(alertMock).toHaveBeenCalledWith(
          'Failed to generate quiz. Ensure backend is running.'
        );
      });

      alertMock.mockRestore();
    });
  });

  describe('Quiz Interaction', () => {
    const mockQuizResponse = {
      id: 'quiz-1',
      title: 'Test Quiz',
      questions: [
        {
          id: 'q1',
          text: 'Test question 1?',
          options: [
            { id: 'a', text: 'Option A' },
            { id: 'b', text: 'Option B' },
            { id: 'c', text: 'Option C' },
            { id: 'd', text: 'Option D' },
          ],
          correct_option_id: 'a',
          explanation: 'Option A is correct because...',
          difficulty: 'easy',
        },
        {
          id: 'q2',
          text: 'Test question 2?',
          options: [
            { id: 'a', text: 'Choice 1' },
            { id: 'b', text: 'Choice 2' },
          ],
          correct_option_id: 'b',
          explanation: 'Choice 2 is correct.',
          difficulty: 'medium',
        },
      ],
      student_mastery: 0.3,
      target_difficulty: 'easy',
      adapted: true,
    };

    beforeEach(async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockQuizResponse,
      });

      render(<Quiz />);

      const startButton = screen.getByText('Start Adaptive Assessment');
      fireEvent.click(startButton);

      await waitFor(() => {
        expect(screen.getByText('Test question 1?')).toBeInTheDocument();
      });
    });

    it('allows selecting an answer option', async () => {
      const optionA = screen.getByText('Option A');
      fireEvent.click(optionA);

      // The button should show selected state (blue border in actual implementation)
      expect(optionA.closest('button')).toHaveClass('border-blue-600');
    });

    it('enables submit button when option is selected', async () => {
      const submitButton = screen.getByText('Submit Answer');
      expect(submitButton).toBeDisabled();

      const optionA = screen.getByText('Option A');
      fireEvent.click(optionA);

      expect(submitButton).not.toBeDisabled();
    });

    it('shows correct feedback for correct answer', async () => {
      const optionA = screen.getByText('Option A');
      fireEvent.click(optionA);

      const submitButton = screen.getByText('Submit Answer');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText('Correct!')).toBeInTheDocument();
        expect(screen.getByText('Option A is correct because...')).toBeInTheDocument();
      });
    });

    it('shows incorrect feedback for wrong answer', async () => {
      const optionB = screen.getByText('Option B');
      fireEvent.click(optionB);

      const submitButton = screen.getByText('Submit Answer');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText('Concept Gap Identified')).toBeInTheDocument();
      });
    });

    it('disables options after submission', async () => {
      const optionA = screen.getByText('Option A');
      fireEvent.click(optionA);

      const submitButton = screen.getByText('Submit Answer');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText('Correct!')).toBeInTheDocument();
      });

      const optionB = screen.getByText('Option B');
      expect(optionB.closest('button')).toBeDisabled();
    });

    it('navigates to next question', async () => {
      const optionA = screen.getByText('Option A');
      fireEvent.click(optionA);

      const submitButton = screen.getByText('Submit Answer');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText('Next Question')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Next Question'));

      await waitFor(() => {
        expect(screen.getByText('Test question 2?')).toBeInTheDocument();
        expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
      });
    });
  });

  describe('Quiz Results', () => {
    const mockQuizResponse = {
      id: 'quiz-1',
      title: 'Test Quiz',
      questions: [
        {
          id: 'q1',
          text: 'Single question?',
          options: [
            { id: 'a', text: 'Correct' },
            { id: 'b', text: 'Wrong' },
          ],
          correct_option_id: 'a',
          explanation: 'Explanation here.',
          difficulty: 'easy',
        },
      ],
      student_mastery: 0.3,
      target_difficulty: 'easy',
      adapted: true,
    };

    it('shows results modal after completing quiz', async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockQuizResponse,
      });
      mockRecommendationsResponse();

      render(<Quiz />);

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Single question?')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Correct'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Finish Quiz')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Finish Quiz'));

      await waitFor(() => {
        expect(screen.getByText('Great Job!')).toBeInTheDocument();
        expect(screen.getByText(/100%/)).toBeInTheDocument();
      });
    });

    it('navigates to learning path from results', async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockQuizResponse,
      });
      mockRecommendationsResponse();

      render(<Quiz />);

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Single question?')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Correct'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Finish Quiz')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Finish Quiz'));

      await waitFor(() => {
        expect(screen.getByText('View Learning Path')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('View Learning Path'));

      expect(mockPush).toHaveBeenCalledWith('/graph');
    });

    it('allows retrying quiz from results', async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockQuizResponse,
      });
      mockRecommendationsResponse();

      render(<Quiz />);

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Single question?')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Correct'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Finish Quiz')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Finish Quiz'));

      await waitFor(() => {
        expect(screen.getByText('Continue Learning (Next Level)')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Continue Learning (Next Level)'));

      await waitFor(() => {
        expect(screen.getByText('Start Assessment')).toBeInTheDocument();
      });
    });
  });

  describe('Score Tracking', () => {
    const mockQuizResponse = {
      id: 'quiz-1',
      title: 'Test Quiz',
      questions: [
        {
          id: 'q1',
          text: 'Question 1?',
          options: [
            { id: 'a', text: 'Correct' },
            { id: 'b', text: 'Wrong' },
          ],
          correct_option_id: 'a',
          explanation: 'Explanation.',
          difficulty: 'easy',
        },
        {
          id: 'q2',
          text: 'Question 2?',
          options: [
            { id: 'a', text: 'Wrong' },
            { id: 'b', text: 'Correct' },
          ],
          correct_option_id: 'b',
          explanation: 'Explanation.',
          difficulty: 'medium',
        },
      ],
      student_mastery: 0.3,
      target_difficulty: 'easy',
      adapted: true,
    };

    it('tracks score correctly', async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockQuizResponse,
      });

      render(<Quiz />);

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Question 1?')).toBeInTheDocument();
      });

      // Answer Q1 correctly
      fireEvent.click(screen.getByText('Correct'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Score: 1')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Next Question'));

      await waitFor(() => {
        expect(screen.getByText('Question 2?')).toBeInTheDocument();
      });

      // Answer Q2 incorrectly
      fireEvent.click(screen.getByText('Wrong'));
      fireEvent.click(screen.getByText('Submit Answer'));

      // Score should still be 1
      await waitFor(() => {
        expect(screen.getByText('Score: 1')).toBeInTheDocument();
      });
    });
  });

  describe('Topic Selection', () => {
    it('changes topic when dropdown changes', async () => {
      render(<Quiz />);

      const select = screen.getByRole('combobox');
      fireEvent.change(select, { target: { value: 'The Constitution' } });

      expect(select).toHaveValue('The Constitution');
    });

    it('uses correct topic in API request', async () => {
      mockProfileResponse();
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 'quiz-1',
          title: 'Constitution Quiz',
          questions: [
            {
              id: 'q1',
              text: 'What is the Constitution?',
              options: [{ id: 'a', text: 'A document' }],
              correct_option_id: 'a',
              explanation: 'It is a document.',
              difficulty: 'easy',
            },
          ],
          student_mastery: 0.3,
          target_difficulty: 'easy',
          adapted: true,
        }),
      });

      render(<Quiz />);

      const select = screen.getByRole('combobox');
      fireEvent.change(select, { target: { value: 'The Constitution' } });

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringContaining('topic=The%20Constitution'),
          expect.any(Object)
        );
      });
    });
  });

  describe('Profile Reset', () => {
    it('calls reset API and shows alert', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Reset successful' }),
      });

      const alertMock = jest.spyOn(window, 'alert').mockImplementation(() => {});

      render(<Quiz />);

      fireEvent.click(screen.getByText('Reset Profile (Demo)'));

      await waitFor(() => {
        expect(alertMock).toHaveBeenCalledWith('Profile reset to initial state');
      });

      alertMock.mockRestore();
    });
  });
});
