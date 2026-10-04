import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import Quiz from '@/components/Quiz';
import { useAppStore } from '@/lib/store';
import { json, mockApi, pending, type MockApiHandler } from './helpers/mockApi';

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

// The quiz and the store use the real API client, answered by the routed mock backend
// ("<METHOD> <path>"), so background requests (profile load on mount, per-answer mastery
// sync) can never consume a response meant for another request.
jest.mock('@/lib/api-client', () => {
  const actual = jest.requireActual('@/lib/api-client');
  return {
    ...actual,
    __esModule: true,
    apiClient: new actual.default('http://localhost:8000', {
      adapter: (config: unknown) => require('./helpers/mockApi').mockApi.adapter(config),
    }),
  };
});

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
  return function MockPostQuizRecommendations({ recommendations, isLoading, error, onRetry, onPractice }: any) {
    return (
      <div data-testid="post-quiz-recommendations">
        {isLoading && <span>Loading recommendations</span>}
        {error && <span data-testid="recommendations-error">{error}</span>}
        {error && onRetry && <button onClick={onRetry}>Retry recommendations</button>}
        {recommendations && <span>{recommendations.summary}</span>}
        <button onClick={() => onPractice('colonial america')}>Practice listed topic</button>
        <button onClick={() => onPractice('Stamp Act')}>Practice unlisted topic</button>
      </div>
    );
  };
});

// The learning path has its own tests
jest.mock('@/components/LearningPath', () => {
  return function MockLearningPath({ conceptName }: { conceptName: string }) {
    return <div data-testid="learning-path">{conceptName}</div>;
  };
});

const PROFILE = 'GET /api/v1/student/profile';
const MASTERY = 'POST /api/v1/student/mastery';
const RESET = 'POST /api/v1/student/reset';
const GENERATE_ADAPTIVE = 'POST /api/v1/quiz/generate-adaptive';
const GENERATE = 'POST /api/v1/quiz/generate';
const RECOMMENDATIONS = 'POST /api/v1/quiz/recommendations';

const profileReply = (masteryLevels: Record<string, number> = {}) =>
  json({
    student_id: 'default',
    overall_ability: 0.3,
    mastery_levels: masteryLevels,
    updated_at: '2026-01-01T00:00:00Z',
  });

const defaultRoutes: Record<string, MockApiHandler> = {
  [PROFILE]: () => profileReply(),
  [MASTERY]: ({ body }) => {
    const { concept, correct } = body as { concept: string; correct: boolean };
    return json({
      concept,
      previous_mastery: 0.3,
      new_mastery: correct ? 0.45 : 0.2,
      target_difficulty: correct ? 'medium' : 'easy',
      total_attempts: 1,
    });
  },
  [RECOMMENDATIONS]: () =>
    json({
      path_type: 'advancement',
      score_pct: 100,
      remediation: [],
      advancement: [],
      summary: 'Great work!',
    }),
};

/** Serve the default routes plus `routes`; any other request is recorded and rejected. */
function mockBackend(routes: Record<string, MockApiHandler> = {}) {
  mockApi.reset();
  for (const [route, handler] of Object.entries({ ...defaultRoutes, ...routes })) {
    mockApi.on(route, handler);
  }
}

const callsTo = (route: string) => mockApi.calls(route);

/** Render the quiz and let the profile request it fires on mount settle. */
async function renderQuiz(ui = <Quiz />) {
  const utils = render(ui);
  await waitFor(() => expect(callsTo(PROFILE)).toHaveLength(1));
  await waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));
  return utils;
}

/** Wait until the per-answer mastery sync has been applied to the store. */
const waitForMasterySync = () =>
  waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));

const getAdaptiveToggle = () => screen.getByRole('switch', { name: 'Adaptive Mode' });
const topicSelect = () => screen.getByRole('combobox', { name: 'Topic' });

const singleQuestionQuiz = {
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

/** Start the quiz, answer the single question correctly and open the results. */
async function completeQuiz(ui = <Quiz />) {
  await renderQuiz(ui);

  fireEvent.click(screen.getByText('Start Adaptive Assessment'));
  await screen.findByText('Single question?');

  fireEvent.click(screen.getByText('Correct'));
  fireEvent.click(screen.getByText('Submit Answer'));
  await screen.findByText('Finish Quiz');
  await waitForMasterySync();

  fireEvent.click(screen.getByText('Finish Quiz'));
  await screen.findByText('Great Job!');
  // Let the recommendations request settle before interacting with the dialog
  await waitFor(() => expect(callsTo(RECOMMENDATIONS)).toHaveLength(1));
}

// Reset store between tests
const initialStoreState = useAppStore.getState();

describe('Quiz Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    mockBackend();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
    expect(mockApi.unexpected).toEqual([]);
  });

  describe('Initial State', () => {
    it('renders the start assessment form', async () => {
      await renderQuiz();

      expect(screen.getByRole('heading', { name: 'Start Assessment' })).toBeInTheDocument();
      expect(getAdaptiveToggle()).toBeInTheDocument();
      expect(topicSelect()).toBeInTheDocument();
    });

    it('shows topic dropdown with options', async () => {
      await renderQuiz();

      expect(topicSelect()).toHaveValue('The American Revolution');
      expect(screen.getByText('The Constitution')).toBeInTheDocument();
      expect(screen.getByText('The Civil War')).toBeInTheDocument();
    });

    it('has adaptive mode enabled by default', async () => {
      await renderQuiz();

      expect(getAdaptiveToggle()).toHaveAttribute('aria-checked', 'true');
      expect(getAdaptiveToggle()).toHaveAccessibleDescription(
        'Questions will be tailored to your current proficiency level'
      );
    });

    it('shows mastery indicator when adaptive mode is on', async () => {
      await renderQuiz();

      expect(screen.getByTestId('mastery-indicator')).toBeInTheDocument();
    });

    it('loads the student profile on mount', async () => {
      await renderQuiz();

      expect(callsTo(PROFILE)).toHaveLength(1);
    });

    it('shows when the progress cannot be synced with the server', async () => {
      mockBackend({ [PROFILE]: () => json({ detail: 'Missing or invalid API key' }, 401) });

      await renderQuiz();

      expect(
        screen.getByText('Your progress could not be synced with the server: Missing or invalid API key')
      ).toBeInTheDocument();
    });
  });

  describe('Adaptive Mode Toggle', () => {
    it('toggles adaptive mode when clicked', async () => {
      await renderQuiz();

      fireEvent.click(getAdaptiveToggle());
      expect(getAdaptiveToggle()).toHaveAttribute('aria-checked', 'false');
      expect(screen.getByText('Questions will have mixed difficulty levels')).toBeInTheDocument();

      fireEvent.click(getAdaptiveToggle());
      expect(getAdaptiveToggle()).toHaveAttribute('aria-checked', 'true');
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

  describe('Mastery Display', () => {
    it('shows the mastery of the selected topic', async () => {
      mockBackend({ [PROFILE]: () => profileReply({ 'The Constitution': 0.8 }) });
      await renderQuiz();

      expect(screen.getByTestId('topic-value')).toHaveTextContent('The American Revolution');
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('30%');

      fireEvent.change(topicSelect(), { target: { value: 'The Constitution' } });

      expect(screen.getByTestId('topic-value')).toHaveTextContent('The Constitution');
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('80%');
      expect(screen.getByTestId('difficulty-value')).toHaveTextContent('hard');
    });

    it('shows the mastery of a custom topic', async () => {
      mockBackend({ [PROFILE]: () => profileReply({ 'Manifest Destiny': 0.5 }) });
      await renderQuiz();

      fireEvent.change(topicSelect(), { target: { value: '__custom__' } });
      fireEvent.change(screen.getByRole('textbox', { name: 'Custom topic' }), {
        target: { value: 'Manifest Destiny' },
      });

      expect(screen.getByTestId('topic-value')).toHaveTextContent('Manifest Destiny');
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('50%');
      expect(screen.getByTestId('difficulty-value')).toHaveTextContent('medium');
    });

    it('shows the selected topic after a quiz on another topic', async () => {
      mockBackend({
        [PROFILE]: () => profileReply({ 'The Civil War': 0.9 }),
        [GENERATE_ADAPTIVE]: () => json(singleQuestionQuiz),
      });
      await completeQuiz();
      fireEvent.click(screen.getByRole('button', { name: 'Close results' }));

      fireEvent.change(topicSelect(), { target: { value: 'The Civil War' } });

      expect(screen.getByTestId('topic-value')).toHaveTextContent('The Civil War');
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('90%');
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
      mockBackend({ [GENERATE_ADAPTIVE]: () => pending() });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(await screen.findByText('Crafting Your Personalized Quiz')).toBeInTheDocument();
      expect(screen.getByText('Generating easy-level questions...')).toBeInTheDocument();
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
    });

    it('asks for three questions on the selected topic and subject', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(mockQuizResponse) });
      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));
      await screen.findByText('What year did the American Revolution begin?');

      expect(Object.fromEntries(callsTo(GENERATE_ADAPTIVE)[0].params)).toEqual({
        topic: 'The American Revolution',
        num_questions: '3',
        subject: 'us_history',
      });
    });

    it('displays quiz after successful generation', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(mockQuizResponse) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      const question = await screen.findByRole('heading', {
        name: 'What year did the American Revolution begin?',
      });
      expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
      expect(screen.getByText('1775')).toBeInTheDocument();
      // Focus moves to the question
      expect(question).toHaveFocus();
    });

    it('shows the reason when the backend is unreachable', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () => Promise.reject(new Error('socket hang up')),
      });

      await renderQuiz();
      // The unexpected-request guard is not the point of this test
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Failed to generate quiz: Could not reach the API at http://localhost:8000. Check that the backend is running.'
      );
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
      // The form is shown again so the user can retry
      expect(screen.getByText('Start Adaptive Assessment')).toBeInTheDocument();
    });

    it('shows the backend detail of an HTTP error', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () => json({ detail: 'Quiz generation service temporarily unavailable' }, 503),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Failed to generate quiz: Quiz generation service temporarily unavailable.'
      );
    });

    it('shows an error when the generated quiz has no questions', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () => json({ ...mockQuizResponse, questions: [] }),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(
        await screen.findByText('The generated quiz has no questions. Try a different topic.')
      ).toBeInTheDocument();
    });

    it('requires a topic when the custom topic is empty', async () => {
      await renderQuiz();

      fireEvent.change(topicSelect(), { target: { value: '__custom__' } });
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(screen.getByText('Please enter a topic.')).toBeInTheDocument();
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(0);
    });

    it('uses the custom topic in the API request', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(mockQuizResponse) });

      await renderQuiz();

      fireEvent.change(topicSelect(), { target: { value: '__custom__' } });
      const customTopic = screen.getByPlaceholderText(/Enter a topic/i);
      expect(customTopic).toHaveAccessibleName('Custom topic');
      expect(customTopic).toHaveAttribute('maxLength', '200');
      fireEvent.change(customTopic, { target: { value: '  Manifest Destiny ' } });
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await waitFor(() => expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1));
      expect(callsTo(GENERATE_ADAPTIVE)[0].params.get('topic')).toBe('Manifest Destiny');
    });

    it('cancels quiz generation when the session ends', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => pending() });
      const { unmount } = await renderQuiz();
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));
      await waitFor(() => expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1));

      unmount();

      expect(callsTo(GENERATE_ADAPTIVE)[0].config.signal?.aborted).toBe(true);
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

    const optionButton = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) });

    beforeEach(async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(mockQuizResponse) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await screen.findByText('Test question 1?');
    });

    it('marks the selected answer option without relying on colour alone', () => {
      expect(optionButton('Option A')).toHaveAttribute('aria-pressed', 'false');

      fireEvent.click(screen.getByText('Option A'));

      expect(optionButton('Option A')).toHaveClass('border-blue-600');
      expect(optionButton('Option A')).toHaveAttribute('aria-pressed', 'true');
      expect(optionButton('Option B')).toHaveAttribute('aria-pressed', 'false');
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

      const feedback = await screen.findByRole('heading', { name: 'Correct!' });
      expect(screen.getByText('Option A is correct because...')).toBeInTheDocument();
      // Focus moves to the feedback
      expect(feedback).toHaveFocus();
      expect(optionButton('Option A')).toHaveAccessibleName('Option A Correct answer');
      await waitForMasterySync();
    });

    it('labels the correct answer and the learner answer after a wrong answer', async () => {
      fireEvent.click(screen.getByText('Option B'));
      fireEvent.click(screen.getByText('Submit Answer'));

      expect(await screen.findByText('Concept Gap Identified')).toBeInTheDocument();
      expect(optionButton('Option A')).toHaveAccessibleName('Option A Correct answer');
      expect(optionButton('Option B')).toHaveAccessibleName('Option B Your answer');
      expect(optionButton('Option C')).toHaveAccessibleName('Option C');
      await waitForMasterySync();
    });

    it('syncs each answer to the mastery endpoint', async () => {
      fireEvent.click(screen.getByText('Option B'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await waitForMasterySync();

      expect(callsTo(MASTERY)).toHaveLength(1);
      expect(callsTo(MASTERY)[0].body).toEqual({
        concept: 'The American Revolution',
        correct: false,
      });
      // The backend estimate is shown
      expect(screen.getAllByTestId('mastery-value')[0]).toHaveTextContent('20%');
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

      await screen.findByText('Correct!');
      await waitForMasterySync();

      expect(screen.getByText('Option B').closest('button')).toBeDisabled();
    });

    it('navigates to next question', async () => {
      fireEvent.click(screen.getByText('Option A'));
      fireEvent.click(screen.getByText('Submit Answer'));

      await screen.findByText('Next Question');
      await waitForMasterySync();

      fireEvent.click(screen.getByText('Next Question'));

      expect(await screen.findByRole('heading', { name: 'Test question 2?' })).toHaveFocus();
      expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
    });
  });

  describe('Quiz Results', () => {
    beforeEach(() => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(singleQuestionQuiz) });
    });

    it('shows the results in a modal dialog', async () => {
      await completeQuiz();

      const dialog = screen.getByRole('dialog', { name: 'Great Job!' });
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(within(dialog).getByText('100%')).toBeInTheDocument();
      expect(within(dialog).getByTestId('post-quiz-recommendations')).toHaveTextContent('Great work!');
    });

    it('moves focus into the dialog and keeps it there', async () => {
      await completeQuiz();
      const dialog = screen.getByRole('dialog');
      const closeButton = within(dialog).getByRole('button', { name: 'Close results' });
      const buttons = within(dialog).getAllByRole('button');
      const lastButton = buttons[buttons.length - 1];

      expect(closeButton).toHaveFocus();

      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
      expect(lastButton).toHaveFocus();

      fireEvent.keyDown(document, { key: 'Tab' });
      expect(closeButton).toHaveFocus();
    });

    it('requests recommendations for the answered questions', async () => {
      await completeQuiz();

      expect(callsTo(RECOMMENDATIONS)[0].body).toEqual({
        topic: 'The American Revolution',
        question_results: [
          { question_id: 'q1', related_concept: 'The American Revolution', correct: true },
        ],
        student_id: 'default',
        subject: 'us_history',
      });
    });

    it('shows a recommendations error with a retry action', async () => {
      let attempts = 0;
      mockBackend({
        [GENERATE_ADAPTIVE]: () => json(singleQuestionQuiz),
        [RECOMMENDATIONS]: () =>
          ++attempts === 1
            ? json({ detail: 'Rate limit exceeded: 10 per 1 minute' }, 429)
            : json({ path_type: 'advancement', score_pct: 100, remediation: [], advancement: [], summary: 'Second try' }),
      });
      await completeQuiz();

      expect(await screen.findByTestId('recommendations-error')).toHaveTextContent(
        'Unable to load recommendations: Rate limit exceeded: 10 per 1 minute. Your score and results are still available above.'
      );

      fireEvent.click(screen.getByRole('button', { name: 'Retry recommendations' }));

      expect(await screen.findByText('Second try')).toBeInTheDocument();
      expect(callsTo(RECOMMENDATIONS)).toHaveLength(2);
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

      expect(await screen.findByRole('heading', { name: 'Start Assessment' })).toHaveFocus();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('closes the results modal with the Escape key and returns focus to the form', async () => {
      await completeQuiz();

      fireEvent.keyDown(document, { key: 'Escape' });

      expect(await screen.findByRole('heading', { name: 'Start Assessment' })).toHaveFocus();
    });

    it('closes the results modal with a click outside the dialog', async () => {
      await completeQuiz();

      fireEvent.click(screen.getByRole('dialog').parentElement as HTMLElement);

      expect(await screen.findByRole('heading', { name: 'Start Assessment' })).toBeInTheDocument();
    });

    it('keeps the dialog open for clicks inside it', async () => {
      await completeQuiz();

      fireEvent.click(screen.getByText('Great Job!'));

      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });

  describe('Practice From Recommendations', () => {
    beforeEach(() => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(singleQuestionQuiz) });
    });

    it('selects a listed topic', async () => {
      await completeQuiz();

      fireEvent.click(screen.getByRole('button', { name: 'Practice listed topic' }));

      expect(await screen.findByRole('heading', { name: 'Start Assessment' })).toBeInTheDocument();
      expect(topicSelect()).toHaveValue('Colonial America');
      expect(screen.queryByRole('textbox', { name: 'Custom topic' })).not.toBeInTheDocument();
    });

    it('selects an unlisted concept as a custom topic', async () => {
      await completeQuiz();

      fireEvent.click(screen.getByRole('button', { name: 'Practice unlisted topic' }));

      expect(await screen.findByRole('heading', { name: 'Start Assessment' })).toBeInTheDocument();
      expect(topicSelect()).toHaveValue('__custom__');
      expect(screen.getByRole('textbox', { name: 'Custom topic' })).toHaveValue('Stamp Act');
      expect(screen.getByTestId('topic-value')).toHaveTextContent('Stamp Act');
    });
  });

  describe('Topic From The URL', () => {
    it('preselects a listed topic, ignoring case', async () => {
      await renderQuiz(<Quiz initialTopic="the civil war" />);

      expect(topicSelect()).toHaveValue('The Civil War');
    });

    it('uses an unlisted topic as a custom topic', async () => {
      await renderQuiz(<Quiz initialTopic="Manifest Destiny" />);

      expect(topicSelect()).toHaveValue('__custom__');
      expect(screen.getByRole('textbox', { name: 'Custom topic' })).toHaveValue('Manifest Destiny');
    });

    it('starts a new session when the requested topic changes', async () => {
      const { rerender } = await renderQuiz(<Quiz initialTopic="The Civil War" />);

      rerender(<Quiz initialTopic="Cold War" />);

      expect(topicSelect()).toHaveValue('Cold War');
      // The new session loads the profile again
      await waitFor(() => expect(callsTo(PROFILE)).toHaveLength(2));
      await waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));
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
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(mockQuizResponse) });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));
      await screen.findByText('Question 1?');

      // Answer Q1 correctly
      fireEvent.click(screen.getByText('Correct'));
      fireEvent.click(screen.getByText('Submit Answer'));

      expect(await screen.findByText('Score: 1')).toBeInTheDocument();
      await waitForMasterySync();

      fireEvent.click(screen.getByText('Next Question'));
      await screen.findByText('Question 2?');

      // Answer Q2 incorrectly
      fireEvent.click(screen.getByText('Wrong'));
      fireEvent.click(screen.getByText('Submit Answer'));

      // Score should still be 1
      expect(await screen.findByText('Concept Gap Identified')).toBeInTheDocument();
      expect(screen.getByText('Score: 1')).toBeInTheDocument();
      await waitForMasterySync();
      expect(callsTo(MASTERY)).toHaveLength(2);
    });
  });

  describe('Topic Selection', () => {
    it('changes topic when dropdown changes', async () => {
      await renderQuiz();

      fireEvent.change(topicSelect(), { target: { value: 'The Constitution' } });

      expect(topicSelect()).toHaveValue('The Constitution');
    });

    it('uses correct topic in API request', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          json({
            ...singleQuestionQuiz,
            questions: [{ ...singleQuestionQuiz.questions[0], text: 'What is the Constitution?' }],
          }),
      });

      await renderQuiz();

      fireEvent.change(topicSelect(), { target: { value: 'The Constitution' } });
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await screen.findByText('What is the Constitution?');
      expect(callsTo(GENERATE_ADAPTIVE)[0].params.get('topic')).toBe('The Constitution');
      expect(screen.getAllByTestId('topic-value')[0]).toHaveTextContent('The Constitution');
    });
  });

  describe('Profile Reset', () => {
    it('calls reset API and shows inline notice', async () => {
      mockBackend({
        [PROFILE]: () => profileReply({ 'The American Revolution': 0.8 }),
        [RESET]: () => profileReply(),
      });

      await renderQuiz();
      await waitFor(() => {
        expect(screen.getByTestId('mastery-value')).toHaveTextContent('80%');
      });

      fireEvent.click(screen.getByText('Reset Profile (Demo)'));

      expect(await screen.findByRole('status')).toHaveTextContent('Profile reset to initial state');
      expect(callsTo(RESET)).toHaveLength(1);
      expect(useAppStore.getState().masteryMap).toEqual({});
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('30%');
    });

    it('dismisses the notice after three seconds', async () => {
      mockBackend({ [RESET]: () => profileReply() });
      await renderQuiz();

      // Fake timers only from here on, so the notice's 3 s auto-dismiss can be fast-forwarded
      jest.useFakeTimers();
      fireEvent.click(screen.getByText('Reset Profile (Demo)'));
      await screen.findByText('Profile reset to initial state');
      act(() => {
        jest.advanceTimersByTime(2999);
      });
      expect(screen.getByText('Profile reset to initial state')).toBeInTheDocument();
      act(() => {
        jest.advanceTimersByTime(1);
      });
      expect(screen.queryByText('Profile reset to initial state')).not.toBeInTheDocument();
    });

    it('clears the notice timer when the quiz is closed', async () => {
      mockBackend({ [RESET]: () => profileReply() });
      const { unmount } = await renderQuiz();
      jest.useFakeTimers();
      fireEvent.click(screen.getByText('Reset Profile (Demo)'));
      await screen.findByText('Profile reset to initial state');
      expect(jest.getTimerCount()).toBe(1);

      unmount();

      expect(jest.getTimerCount()).toBe(0);
    });

    it('reports a failed reset instead of claiming success', async () => {
      mockBackend({
        [PROFILE]: () => profileReply({ 'The American Revolution': 0.8 }),
        [RESET]: () => json({ detail: 'An internal error occurred' }, 500),
      });
      await renderQuiz();
      await waitFor(() => expect(screen.getByTestId('mastery-value')).toHaveTextContent('80%'));

      fireEvent.click(screen.getByText('Reset Profile (Demo)'));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Could not reset your profile: An internal error occurred'
      );
      expect(screen.queryByText('Profile reset to initial state')).not.toBeInTheDocument();
      expect(screen.getByTestId('mastery-value')).toHaveTextContent('80%');
      expect(screen.getByRole('button', { name: /Reset Profile/ })).toBeEnabled();
    });
  });

  describe('Subject Switching Lifecycle', () => {
    it('resets quiz state when subject changes', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          json({
            ...singleQuestionQuiz,
            questions: [{ ...singleQuestionQuiz.questions[0], text: 'Old subject question?' }],
          }),
      });

      await renderQuiz();

      // Generate a quiz
      fireEvent.click(screen.getByText('Start Adaptive Assessment'));
      await screen.findByText('Old subject question?');

      // Switch subject in store
      act(() => {
        useAppStore.setState({ currentSubject: 'economics' });
      });

      // Quiz should be cleared and we should see the start form again
      expect(await screen.findByText('Start Assessment')).toBeInTheDocument();
      expect(screen.queryByText('Old subject question?')).not.toBeInTheDocument();
      await waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));
    });

    it('updates topic dropdown when subject changes', async () => {
      // Start with us_history
      useAppStore.setState({ currentSubject: 'us_history' });
      await renderQuiz();

      // Should show US History topics in the dropdown
      expect(topicSelect()).toHaveValue('The American Revolution');

      // Switch to economics
      act(() => {
        useAppStore.setState({ currentSubject: 'economics' });
      });

      // Dropdown now offers the economics topics
      expect(topicSelect()).toHaveValue('Supply and Demand');
      expect(screen.getByText('Market Equilibrium')).toBeInTheDocument();
      expect(screen.queryByText('The Civil War')).not.toBeInTheDocument();
      await waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));
    });

    it('includes subject in quiz generation API call', async () => {
      useAppStore.setState({ currentSubject: 'economics' });
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          json({
            ...singleQuestionQuiz,
            questions: [{ ...singleQuestionQuiz.questions[0], text: 'What is GDP?' }],
          }),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      await screen.findByText('What is GDP?');
      expect(callsTo(GENERATE_ADAPTIVE)).toHaveLength(1);
      expect(callsTo(GENERATE_ADAPTIVE)[0].params.get('subject')).toBe('economics');
    });

    it('clears results when subject changes during quiz results', async () => {
      mockBackend({ [GENERATE_ADAPTIVE]: () => json(singleQuestionQuiz) });

      await completeQuiz();

      // Switch subject — should reset everything
      act(() => {
        useAppStore.setState({ currentSubject: 'biology' });
      });

      expect(await screen.findByText('Start Assessment')).toBeInTheDocument();
      expect(screen.queryByText('Great Job!')).not.toBeInTheDocument();
      await waitFor(() => expect(useAppStore.getState().isSyncing).toBe(false));
    });
  });

  describe('Non-Adaptive Mode', () => {
    it('sends standard quiz request when adaptive mode is off', async () => {
      mockBackend({
        [GENERATE]: () =>
          json({
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

      await screen.findByText('Standard Q?');
      // Only the standard endpoint is used; the adaptive one would be an unexpected request
      expect(callsTo(GENERATE)).toHaveLength(1);
      expect(callsTo(GENERATE)[0].params.get('topic')).toBe('The American Revolution');
      // Standard quizzes do not show the adaptive mastery banner
      expect(screen.queryByTestId('mastery-indicator')).not.toBeInTheDocument();

      // Finish the quiz: the results show the quiz difficulty
      fireEvent.click(screen.getByText('A'));
      fireEvent.click(screen.getByText('Submit Answer'));
      await waitForMasterySync();
      fireEvent.click(await screen.findByText('Finish Quiz'));

      expect(await screen.findByText('Quiz Difficulty:')).toBeInTheDocument();
      expect(screen.getByText('(50%)')).toBeInTheDocument();
      expect(screen.getByText('Try Another Assessment')).toBeInTheDocument();
      await waitFor(() => expect(callsTo(RECOMMENDATIONS)).toHaveLength(1));
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
    it('shows difficulty badge on question', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () =>
          json({
            ...singleQuestionQuiz,
            questions: [
              { ...singleQuestionQuiz.questions[0], text: 'Hard question?', difficulty: 'hard', difficulty_score: 0.85 },
            ],
            student_mastery: 0.7,
            target_difficulty: 'hard',
          }),
      });

      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(await screen.findByText('Hard question?')).toBeInTheDocument();
      // Difficulty badge should be shown (capitalized label)
      expect(screen.getByText('Hard')).toBeInTheDocument();
    });
  });

  describe('Invalid Quiz Data', () => {
    it('offers to start again when a question cannot be shown', async () => {
      mockBackend({
        [GENERATE_ADAPTIVE]: () => json({ ...singleQuestionQuiz, questions: [null] }),
      });
      await renderQuiz();

      fireEvent.click(screen.getByText('Start Adaptive Assessment'));

      expect(await screen.findByText('Quiz Error')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Try Again' }));
      expect(await screen.findByRole('heading', { name: 'Start Assessment' })).toBeInTheDocument();
    });
  });
});
