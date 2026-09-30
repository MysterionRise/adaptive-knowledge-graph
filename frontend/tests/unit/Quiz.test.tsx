import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
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

// The real LearningPath loads its data through the axios API client, which would open a real
// connection to localhost:8000 (30 s timeout) and keep Jest alive after the suite finishes.
jest.mock('@/components/LearningPath', () => {
  return function MockLearningPath({ conceptName }: { conceptName: string }) {
    return <div data-testid="learning-path">{conceptName}</div>;
  };
});

// ---------------------------------------------------------------------------
// fetch mock, routed by "<METHOD> <pathname>" so that background requests (profile load on
// mount, per-answer mastery sync) can never consume a response meant for another request.
// ---------------------------------------------------------------------------

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
};
type RouteHandler = (url: URL, init?: RequestInit) => MockResponse | Promise<MockResponse>;

const PROFILE = 'GET /api/v1/student/profile';
const MASTERY = 'POST /api/v1/student/mastery';
const RESET = 'POST /api/v1/student/reset';
const GENERATE_ADAPTIVE = 'POST /api/v1/quiz/generate-adaptive';
const GENERATE = 'POST /api/v1/quiz/generate';
const RECOMMENDATIONS = 'POST /api/v1/quiz/recommendations';

const jsonResponse = (body: unknown, status = 200): MockResponse => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
});

const profileResponse = (masteryLevels: Record<string, number> = {}) =>
  jsonResponse({
    student_id: 'default',
    overall_ability: 0.3,
    mastery_levels: masteryLevels,
    updated_at: '2026-01-01T00:00:00Z',
  });

const defaultRoutes: Record<string, RouteHandler> = {
  [PROFILE]: () => profileResponse(),
  [MASTERY]: (_url, init) => {
    const { concept, correct } = JSON.parse(String(init?.body));
    return jsonResponse({
      concept,
      previous_mastery: 0.3,
      new_mastery: correct ? 0.45 : 0.2,
      target_difficulty: correct ? 'medium' : 'easy',
      total_attempts: 1,
    });
  },
  [RECOMMENDATIONS]: () =>
    jsonResponse({
      path_type: 'advancement',
      score_pct: 100,
      remediation: [],
      advancement: [],
      summary: 'Great work!',
    }),
};

const routeKey = (input: unknown, init?: RequestInit) =>
  `${init?.method ?? 'GET'} ${new URL(String(input)).pathname}`;

const fetchMock = jest.fn();
const originalFetch = global.fetch;
let unexpectedRequests: string[] = [];

/** Serve the default routes plus `routes`; any other request is recorded and rejected. */
function mockBackend(routes: Record<string, RouteHandler> = {}) {
  const handlers = { ...defaultRoutes, ...routes };
  fetchMock.mockImplementation(async (input: unknown, init?: RequestInit) => {
    const key = routeKey(input, init);
    const handler = handlers[key];
    if (!handler) {
      unexpectedRequests.push(key);
      throw new Error(`Unexpected request: ${key}`);
    }
    return handler(new URL(String(input)), init);
  });
}

const callsTo = (route: string) =>
  fetchMock.mock.calls.filter(([input, init]) => routeKey(input, init) === route);

/** Render the quiz and let the profile request it fires on mount settle. */
async function renderQuiz() {
  const utils = render(<Quiz />);
  await waitFor(() => expect(callsTo(PROFILE)).toHaveLength(1));
  await waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));
  return utils;
}

/** Wait until the per-answer mastery sync has been applied to the store. */
const waitForMasterySync = () =>
  waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));

// The adaptive-mode toggle is an unlabeled <button> next to the "Adaptive Mode" label.
function getAdaptiveToggle(): HTMLElement {
  const toggle = screen.getByText('Adaptive Mode').closest('div')?.parentElement?.querySelector('button');
  if (!toggle) throw new Error('Adaptive mode toggle not found');
  return toggle;
}

// Reset store between tests
const initialStoreState = useAppStore.getState();

beforeAll(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
});

afterAll(() => {
  global.fetch = originalFetch;
});

describe('Quiz Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    fetchMock.mockReset();
    unexpectedRequests = [];
    useAppStore.setState(initialStoreState);
    mockBackend();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
    expect(unexpectedRequests).toEqual([]);
  });

  describe('Initial State', () => {
    it('renders the start assessment form', async () => {
      await renderQuiz();

      expect(screen.getByText('Start Assessment')).toBeInTheDocument();
      expect(screen.getByText('Adaptive Mode')).toBeInTheDocument();
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    it('shows topic dropdown with options', async () => {
      await renderQuiz();

      const select = screen.getByRole('combobox');
      expect(select).toHaveValue('The American Revolution');

      expect(screen.getByText('The Constitution')).toBeInTheDocument();
      expect(screen.getByText('The Civil War')).toBeInTheDocument();
    });

    it('has adaptive mode enabled by default', async () => {
      await renderQuiz();

      expect(
        screen.getByText('Questions will be tailored to your current proficiency level')
      ).toBeInTheDocument();
    });

    it('shows mastery indicator when adaptive mode is on', async () => {
      await renderQuiz();

      expect(screen.getByTestId('mastery-indicator')).toBeInTheDocument();
    });

    it('loads the student profile on mount', async () => {
      await renderQuiz();

      expect(callsTo(PROFILE)).toHaveLength(1);
    });
  });

  describe('Adaptive Mode Toggle', () => {
    it('toggles adaptive mode when clicked', async () => {
      await renderQuiz();

      fireEvent.click(getAdaptiveToggle());
      expect(screen.getByText('Questions will have mixed difficulty levels')).toBeInTheDocument();

      fireEvent.click(getAdaptiveToggle());
      expect(
        screen.getByText('Questions will be tailored to your current proficiency level')
      ).toBeInTheDocument();
    });

    it('changes button text based on adaptive mode', async () => {
      await renderQuiz();

      expect(screen.getByText('Start Adaptive Assessment')).toBeInTheDocument();

      fireEvent.click(getAdaptiveToggle());

      expect(screen.getByText('Generate Assessment')).toBeInTheDocument();
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
      // Quiz generation never resolves, so the loading screen stays up
      mockBackend({ [GENERATE_ADAPTIVE]: () => new Promise<MockResponse>(() => {}) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Crafting Your Personalized Quiz')).toBeInTheDocument();
      });
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
    });

    it('displays quiz after successful generation', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => jsonResponse(mockQuizResponse) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('What year did the American Revolution begin?')).toBeInTheDocument();
      });

      expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
      expect(screen.getByText('1775')).toBeInTheDocument();
    });

    it('handles generation error gracefully', async () => {
      const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
      mockBackend({
        [GENERATE_ADAPTIVE]: () => Promise.reject(new Error('Network error')),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(
          screen.getByText('Failed to generate quiz. Please ensure the backend is running.')
        ).toBeInTheDocument();
      });
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
      expect(consoleError).toHaveBeenCalledWith(
        'Failed to generate quiz',
        expect.objectContaining({ message: 'Network error' })
      );
      // The form is shown again so the user can retry
      expect(screen.getByText('Start Adaptive Assessment')).toBeInTheDocument();
    });

    it('shows an error when the backend responds with an HTTP error', async () => {
      const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
      mockBackend({
        [GENERATE_ADAPTIVE]: () => jsonResponse({ detail: 'LLM unavailable' }, 503),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(
          screen.getByText('Failed to generate quiz. Please ensure the backend is running.')
        ).toBeInTheDocument();
      });
      expect(consoleError).toHaveBeenCalledWith(
        'Failed to generate quiz',
        expect.objectContaining({ message: expect.stringContaining('(503)') })
      );
    });

    it('shows an error when the generated quiz has no questions', async () => {
      jest.spyOn(console, 'error').mockImplementation(() => {});
      mockBackend({
        [GENERATE_ADAPTIVE]: () => jsonResponse({ ...mockQuizResponse, questions: [] }),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(
          screen.getByText('Failed to generate quiz. Please ensure the backend is running.')
        ).toBeInTheDocument();
      });
    });

    it('requires a topic when the custom topic is empty', async () => {
      await renderQuiz();

      fireEvent.change(screen.getByRole('combobox'), { target: { value: '__custom__' } });
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(screen.getByText('Please enter a topic.')).toBeInTheDocument();
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(0);
    });

    it('uses the custom topic in the API request', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => jsonResponse(mockQuizResponse) });

      await renderQuiz();

      fireEvent.change(screen.getByRole('combobox'), { target: { value: '__custom__' } });
      fireEvent.change(screen.getByPlaceholderText(/Enter a topic/i), {
        target: { value: 'Manifest Destiny' },
      });
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
      });
      expect(callsTo(GENERATE_ADAPTIVE)[0][0]).toContain('topic=Manifest%20Destiny');
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
      mockBackend({ [GENERATE_ADAPTIVE]: () => jsonResponse(mockQuizResponse) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Test question 1?')).toBeInTheDocument();
      });
    });

    it('allows selecting an answer option', () => {
      const optionA = screen.getByText('Option A');
      fireEvent.click(optionA);

      // The button should show selected state (blue border in actual implementation)
      expect(optionA.closest('button')).toHaveClass('border-blue-600');
    });

    it('enables submit button when option is selected', () => {
      const submitButton = screen.getByText('Submit Answer');
      expect(submitButton).toBeDisabled();

      fireEvent.click(screen.getByText('Option A'));

      expect(submitButton).not.toBeDisabled();
    });

    it('shows correct feedback for correct answer', async () => {
      fireEvent.click(screen.getByText('Option A'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Correct!')).toBeInTheDocument();
        expect(screen.getByText('Option A is correct because...')).toBeInTheDocument();
      });
      await waitForMasterySync();
    });

    it('shows incorrect feedback for wrong answer', async () => {
      fireEvent.click(screen.getByText('Option B'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Concept Gap Identified')).toBeInTheDocument();
      });
      await waitForMasterySync();
    });

    it('syncs each answer to the mastery endpoint', async () => {
      fireEvent.click(screen.getByText('Option B'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitForMasterySync();

      expect(callsTo(MASTERY)).toHaveLength(1);
      expect(JSON.parse(String(callsTo(MASTERY)[0][1]?.body))).toEqual({
        concept: 'The American Revolution',
        correct: false,
      });
    });

    it('links to the tutor after a wrong answer', async () => {
      fireEvent.click(screen.getByText('Option B'));
      fireEvent.click(screen.getByText('Submit Answer'));
      await waitForMasterySync();

      fireEvent.click(screen.getByText('Ask the tutor about The American Revolution'));

      expect(mockPush).toHaveBeenCalledWith(
        '/chat?question=Explain%20The%20American%20Revolution'
      );
    });

    it('disables options after submission', async () => {
      fireEvent.click(screen.getByText('Option A'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Correct!')).toBeInTheDocument();
      });
      await waitForMasterySync();

      expect(screen.getByText('Option B').closest('button')).toBeDisabled();
    });

    it('navigates to next question', async () => {
      fireEvent.click(screen.getByText('Option A'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Next Question')).toBeInTheDocument();
      });
      await waitForMasterySync();

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

    /** Answer the single question correctly and open the results modal. */
    async function completeQuiz() {
      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Single question?')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Correct'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => {
        expect(screen.getByText('Finish Quiz')).toBeInTheDocument();
      });
      await waitForMasterySync();

      fireEvent.click(screen.getByText('Finish Quiz'));

      await waitFor(() => {
        expect(screen.getByText('Great Job!')).toBeInTheDocument();
      });
      // Let the recommendations request settle before interacting with the modal
      await waitFor(() => expect(callsTo(RECOMMENDATIONS)).toHaveLength(1));
    }

    beforeEach(() => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => jsonResponse(mockQuizResponse) });
    });

    it('shows results modal after completing quiz', async () => {
      await completeQuiz();

      expect(screen.getByText('Great Job!')).toBeInTheDocument();
      expect(screen.getByText(/100%/)).toBeInTheDocument();
      expect(screen.getByTestId('post-quiz-recommendations')).toBeInTheDocument();
    });

    it('requests recommendations for the answered questions', async () => {
      await completeQuiz();

      const body = JSON.parse(String(callsTo(RECOMMENDATIONS)[0][1]?.body));
      expect(body).toEqual({
        topic: 'The American Revolution',
        question_results: [
          { question_id: 'q1', related_concept: 'The American Revolution', correct: true },
        ],
        student_id: 'default',
        subject: 'us_history',
      });
    });

    it('shows the learning path for the quizzed topic', async () => {
      await completeQuiz();

      expect(screen.getByTestId('learning-path')).toHaveTextContent('The American Revolution');
    });

    it('navigates to learning path from results', async () => {
      await completeQuiz();

      fireEvent.click(screen.getByText('View Learning Path'));

      expect(mockPush).toHaveBeenCalledWith('/graph');
      expect(useAppStore.getState().highlightedConcepts).toEqual(['The American Revolution']);
    });

    it('allows retrying quiz from results', async () => {
      await completeQuiz();

      fireEvent.click(screen.getByText('Continue Learning (Next Level)'));

      await waitFor(() => {
        expect(screen.getByText('Start Assessment')).toBeInTheDocument();
      });
    });

    it('closes the results modal with the Escape key', async () => {
      await completeQuiz();

      fireEvent.keyDown(document, { key: 'Escape' });

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
      mockBackend({ [GENERATE_ADAPTIVE]: () => jsonResponse(mockQuizResponse) });

      await renderQuiz();

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
      await waitForMasterySync();

      fireEvent.click(screen.getByText('Next Question'));

      await waitFor(() => {
        expect(screen.getByText('Question 2?')).toBeInTheDocument();
      });

      // Answer Q2 incorrectly
      fireEvent.click(screen.getByText('Wrong'));
      fireEvent.click(screen.getByText('Submit Answer'));

      // Score should still be 1
      await waitFor(() => {
        expect(screen.getByText('Concept Gap Identified')).toBeInTheDocument();
      });
      expect(screen.getByText('Score: 1')).toBeInTheDocument();
      await waitForMasterySync();
      expect(callsTo(MASTERY)).toHaveLength(2);
    });
  });

  describe('Topic Selection', () => {
    it('changes topic when dropdown changes', async () => {
      await renderQuiz();

      const select = screen.getByRole('combobox');
      fireEvent.change(select, { target: { value: 'The Constitution' } });

      expect(select).toHaveValue('The Constitution');
    });

    it('uses correct topic in API request', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          jsonResponse({
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

      await renderQuiz();

      fireEvent.change(screen.getByRole('combobox'), { target: { value: 'The Constitution' } });
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('What is the Constitution?')).toBeInTheDocument();
      });
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('topic=The%20Constitution'),
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  describe('Profile Reset', () => {
    it('calls reset API and shows inline notice', async () => {
      mockBackend({
        [PROFILE]: () => profileResponse({ 'The American Revolution': 0.8 }),
        [RESET]: () => jsonResponse({ message: 'Reset successful' }),
      });

      await renderQuiz();
      await waitFor(() => {
        expect(screen.getByTestId('mastery-value')).toHaveTextContent('80%');
      });

      // Fake timers only from here on, so the notice's 3 s auto-dismiss can be fast-forwarded
      jest.useFakeTimers();
      fireEvent.click(screen.getByText('Reset Profile (Demo)'));

      await waitFor(() => {
        expect(screen.getByText('Profile reset to initial state')).toBeInTheDocument();
      });
      expect(callsTo(RESET)).toHaveLength(1);
      expect(useAppStore.getState().masteryMap).toEqual({});
      expect(useAppStore.getState().lastSyncError).toBeNull();
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('30%');

      // The notice dismisses itself after three seconds
      act(() => {
        jest.advanceTimersByTime(3000);
      });
      expect(screen.queryByText('Profile reset to initial state')).not.toBeInTheDocument();
    });
  });

  describe('Subject Switching Lifecycle', () => {
    it('resets quiz state when subject changes', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          jsonResponse({
            id: 'quiz-1',
            title: 'Test Quiz',
            questions: [
              {
                id: 'q1',
                text: 'Old subject question?',
                options: [
                  { id: 'a', text: 'A' },
                  { id: 'b', text: 'B' },
                ],
                correct_option_id: 'a',
                explanation: 'Explanation.',
                difficulty: 'easy',
              },
            ],
            student_mastery: 0.3,
            target_difficulty: 'easy',
            adapted: true,
          }),
      });

      await renderQuiz();

      // Generate a quiz
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Old subject question?')).toBeInTheDocument();
      });

      // Switch subject in store
      act(() => {
        useAppStore.setState({ currentSubject: 'economics' });
      });

      // Quiz should be cleared and we should see the start form again
      await waitFor(() => {
        expect(screen.getByText('Start Assessment')).toBeInTheDocument();
      });
      expect(screen.queryByText('Old subject question?')).not.toBeInTheDocument();
    });

    it('updates topic dropdown when subject changes', async () => {
      // Start with us_history
      useAppStore.setState({ currentSubject: 'us_history' });
      await renderQuiz();

      // Should show US History topics in the dropdown
      expect(screen.getByRole('combobox')).toHaveValue('The American Revolution');

      // Switch to economics
      act(() => {
        useAppStore.setState({ currentSubject: 'economics' });
      });

      // Dropdown now offers the economics topics
      expect(screen.getByRole('combobox')).toHaveValue('Supply and Demand');
      expect(screen.getByText('Market Equilibrium')).toBeInTheDocument();
      expect(screen.queryByText('The Civil War')).not.toBeInTheDocument();
    });

    it('includes subject in quiz generation API call', async () => {
      useAppStore.setState({ currentSubject: 'economics' });
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          jsonResponse({
            id: 'quiz-1',
            title: 'Economics Quiz',
            questions: [
              {
                id: 'q1',
                text: 'What is GDP?',
                options: [{ id: 'a', text: 'Answer' }],
                correct_option_id: 'a',
                explanation: 'GDP stands for...',
                difficulty: 'easy',
              },
            ],
            student_mastery: 0.3,
            target_difficulty: 'easy',
            adapted: true,
          }),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('What is GDP?')).toBeInTheDocument();
      });
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
      expect(callsTo(GENERATE_ADAPTIVE)[0][0]).toContain('subject=economics');
    });

    it('clears results when subject changes during quiz results', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          jsonResponse({
            id: 'quiz-1',
            title: 'Test Quiz',
            questions: [
              {
                id: 'q1',
                text: 'Single Q?',
                options: [
                  { id: 'a', text: 'Right' },
                  { id: 'b', text: 'Wrong' },
                ],
                correct_option_id: 'a',
                explanation: 'Right is correct.',
                difficulty: 'easy',
              },
            ],
            student_mastery: 0.3,
            target_difficulty: 'easy',
            adapted: true,
          }),
      });

      await renderQuiz();

      // Complete a quiz
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));
      await waitFor(() => expect(screen.getByText('Single Q?')).toBeInTheDocument());

      fireEvent.click(screen.getByText('Right'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitFor(() => expect(screen.getByText('Finish Quiz')).toBeInTheDocument());
      await waitForMasterySync();
      fireEvent.click(screen.getByText('Finish Quiz'));

      await waitFor(() => expect(screen.getByText('Great Job!')).toBeInTheDocument());
      await waitFor(() => expect(callsTo(RECOMMENDATIONS)).toHaveLength(1));

      // Switch subject — should reset everything
      act(() => {
        useAppStore.setState({ currentSubject: 'biology' });
      });

      await waitFor(() => {
        expect(screen.getByText('Start Assessment')).toBeInTheDocument();
      });
      expect(screen.queryByText('Great Job!')).not.toBeInTheDocument();
    });
  });

  describe('Non-Adaptive Mode', () => {
    it('sends standard quiz request when adaptive mode is off', async () => {
      mockBackend({
        [GENERATE]: () =>
          jsonResponse({
            id: 'quiz-1',
            title: 'Standard Quiz',
            average_difficulty: 0.5,
            questions: [
              {
                id: 'q1',
                text: 'Standard Q?',
                options: [
                  { id: 'a', text: 'A' },
                  { id: 'b', text: 'B' },
                  { id: 'c', text: 'C' },
                  { id: 'd', text: 'D' },
                ],
                correct_option_id: 'a',
                explanation: 'Standard explanation.',
                difficulty: 'medium',
              },
            ],
          }),
      });

      await renderQuiz();

      fireEvent.click(getAdaptiveToggle());

      // Should show non-adaptive button text
      expect(screen.getByText('Generate Assessment')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Generate Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Standard Q?')).toBeInTheDocument();
      });
      // Only the standard endpoint is used; the adaptive one would be an unexpected request
      expect(callsTo(GENERATE)).toHaveLength(1);
      expect(callsTo(GENERATE)[0][0]).toContain('topic=The%20American%20Revolution');
      // Standard quizzes do not show the adaptive mastery banner
      expect(screen.queryByTestId('mastery-indicator')).not.toBeInTheDocument();
    });

    it('hides mastery indicator when adaptive mode is off', async () => {
      await renderQuiz();

      fireEvent.click(getAdaptiveToggle());

      // After toggling off, text should change to mixed difficulty
      expect(screen.getByText('Questions will have mixed difficulty levels')).toBeInTheDocument();

      // Mastery indicator should not be shown
      expect(screen.queryByTestId('mastery-indicator')).not.toBeInTheDocument();
    });
  });

  describe('Difficulty Badge', () => {
    const mockQuizResponse = {
      id: 'quiz-1',
      title: 'Test Quiz',
      questions: [
        {
          id: 'q1',
          text: 'Hard question?',
          options: [
            { id: 'a', text: 'A' },
            { id: 'b', text: 'B' },
            { id: 'c', text: 'C' },
            { id: 'd', text: 'D' },
          ],
          correct_option_id: 'a',
          explanation: 'Explanation.',
          difficulty: 'hard',
          difficulty_score: 0.85,
        },
      ],
      student_mastery: 0.7,
      target_difficulty: 'hard',
      adapted: true,
    };

    it('shows difficulty badge on question', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => jsonResponse(mockQuizResponse) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => {
        expect(screen.getByText('Hard question?')).toBeInTheDocument();
        // Difficulty badge should be shown (capitalized label)
        expect(screen.getByText('Hard')).toBeInTheDocument();
      });
    });
  });
});
