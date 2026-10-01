import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react';
import LearningPath from '@/components/LearningPath';
import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';
import type { LearningPathResponse } from '@/lib/types';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
  }),
}));

jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getLearningPath: jest.fn(),
  },
}));

// Reset store between tests
const initialStoreState = useAppStore.getState();
const mockGetLearningPath = apiClient.getLearningPath as jest.Mock;

// The payload of GET /learning-path/{concept}: prerequisites only, `depth` = steps to the target
const mockLearningPath: LearningPathResponse = {
  target_concept: 'Advanced Topic',
  prerequisites: [
    { id: 'c2', name: 'Intermediate Concept', importance: 0.7, chapter: 'Ch 2', depth: 1 },
    { id: 'c1', name: 'Basic Concept', importance: 0.6, chapter: null, depth: 2 },
  ],
  total_concepts: 3,
};

/** Names of the steps, in the order shown. */
const stepNames = () =>
  within(screen.getByRole('list', { name: /Learning path to/ }))
    .getAllByRole('heading', { level: 4 })
    .map((heading) => heading.textContent?.replace('Target', ''));

describe('LearningPath Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    mockGetLearningPath.mockReset();
    mockGetLearningPath.mockResolvedValue(mockLearningPath);
  });

  describe('Loading State', () => {
    it('shows loading spinner while fetching', () => {
      mockGetLearningPath.mockImplementation(() => new Promise(() => {}));

      render(<LearningPath conceptName="Test Concept" />);

      expect(screen.getByRole('status')).toHaveTextContent('Loading learning path...');
    });

    it('does not load or spin forever without a concept', () => {
      render(<LearningPath conceptName="   " />);

      expect(screen.getByText('Choose a concept to see its learning path.')).toBeInTheDocument();
      expect(screen.queryByText('Loading learning path...')).not.toBeInTheDocument();
      expect(mockGetLearningPath).not.toHaveBeenCalled();
    });
  });

  describe('Error State', () => {
    it('shows the error with a retry action', async () => {
      mockGetLearningPath
        .mockRejectedValueOnce(new ApiError('http', 'Database connection failed', { status: 503 }))
        .mockResolvedValueOnce(mockLearningPath);

      render(<LearningPath conceptName="Advanced Topic" />);

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('Unable to load learning path.');
      expect(alert).toHaveTextContent('Database connection failed');

      fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

      expect(await screen.findByText('Basic Concept')).toBeInTheDocument();
      expect(mockGetLearningPath).toHaveBeenCalledTimes(2);
    });
  });

  describe('Empty State', () => {
    it('shows empty message when the concept has no prerequisites', async () => {
      mockGetLearningPath.mockResolvedValueOnce({
        target_concept: 'Test Concept',
        prerequisites: [],
        total_concepts: 1,
      });

      render(<LearningPath conceptName="Test Concept" />);

      expect(
        await screen.findByText('No prerequisite path found for this concept.')
      ).toBeInTheDocument();
    });
  });

  describe('Successful Render', () => {
    it('renders learning path header', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      expect(await screen.findByRole('heading', { name: 'Learning Path' })).toBeInTheDocument();
      expect(screen.getByText(/Master these concepts in order to understand/)).toHaveTextContent(
        'Advanced Topic'
      );
    });

    it('lists the prerequisites in learning order and ends with the target', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      expect(stepNames()).toEqual(['Basic Concept', 'Intermediate Concept', 'Advanced Topic']);
    });

    it('does not list the target twice when the backend includes it', async () => {
      mockGetLearningPath.mockResolvedValueOnce({
        ...mockLearningPath,
        prerequisites: [
          ...mockLearningPath.prerequisites,
          { id: 'c3', name: 'advanced topic', importance: 0.9, depth: 0 },
        ],
      });

      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      expect(stepNames()).toEqual(['Basic Concept', 'Intermediate Concept', 'Advanced Topic']);
    });

    it('marks the target concept', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      expect(await screen.findByText('Target')).toBeInTheDocument();
      expect(screen.getByText('Target concept')).toBeInTheDocument();
    });

    it('describes how far each prerequisite is from the target', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      expect(await screen.findByText('Direct prerequisite')).toBeInTheDocument();
      expect(screen.getByText('2 steps before the target')).toBeInTheDocument();
    });

    it('requests the path of the concept for the current subject', async () => {
      useAppStore.setState({ currentSubject: 'economics' });

      render(<LearningPath conceptName=" Advanced Topic " />);
      await screen.findByText('Basic Concept');

      expect(mockGetLearningPath).toHaveBeenCalledWith('Advanced Topic', 5, 'economics', {
        signal: expect.any(AbortSignal),
      });
    });
  });

  describe('Mastery Display', () => {
    it('shows the initial mastery for untracked concepts', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      expect(screen.getAllByText('30%')).toHaveLength(3);
    });

    it('uses mastery from store when available', async () => {
      useAppStore.setState({
        masteryMap: {
          'Basic Concept': {
            conceptName: 'Basic Concept',
            masteryLevel: 0.85,
            attempts: 5,
            lastAssessed: '2024-01-01',
          },
        },
      });

      render(<LearningPath conceptName="Advanced Topic" />);

      expect(await screen.findByText('85%')).toBeInTheDocument();
    });

    it('updates when the mastery changes', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      act(() => {
        useAppStore.setState({
          masteryMap: {
            'Intermediate Concept': {
              conceptName: 'Intermediate Concept',
              masteryLevel: 0.75,
              attempts: 1,
              lastAssessed: null,
            },
          },
        });
      });

      expect(screen.getByText('75%')).toBeInTheDocument();
    });

    it('counts mastered, in-progress and new concepts', async () => {
      useAppStore.setState({
        masteryMap: {
          'Basic Concept': { conceptName: 'Basic Concept', masteryLevel: 0.9, attempts: 3, lastAssessed: null },
          'Intermediate Concept': { conceptName: 'Intermediate Concept', masteryLevel: 0.1, attempts: 3, lastAssessed: null },
        },
      });

      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      expect(screen.getByText('Mastered').nextSibling).toHaveTextContent('1');
      expect(screen.getByText('In Progress').nextSibling).toHaveTextContent('1');
      expect(screen.getByText('To Learn').nextSibling).toHaveTextContent('1');
    });
  });

  describe('Actions', () => {
    it('renders Ask Tutor and Practice buttons for each concept', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      expect(screen.getAllByText('Ask Tutor')).toHaveLength(3);
      expect(screen.getAllByText('Practice')).toHaveLength(3);
    });

    it('navigates to chat when Ask Tutor is clicked', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      fireEvent.click(await screen.findByRole('button', { name: 'Ask Tutor about Basic Concept' }));

      expect(mockPush).toHaveBeenCalledWith('/chat?question=Explain%20Basic%20Concept');
    });

    it('opens the assessment for the concept when Practice is clicked', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      fireEvent.click(await screen.findByRole('button', { name: 'Practice Basic Concept' }));

      expect(mockPush).toHaveBeenCalledWith('/assessment?topic=Basic%20Concept');
    });
  });

  describe('Callbacks', () => {
    it('calls onConceptClick from a keyboard-reachable concept button', async () => {
      const onConceptClick = jest.fn();

      render(<LearningPath conceptName="Advanced Topic" onConceptClick={onConceptClick} />);

      const conceptButton = await screen.findByRole('button', { name: 'Basic Concept' });
      conceptButton.focus();
      expect(conceptButton).toHaveFocus();
      fireEvent.click(conceptButton);

      expect(onConceptClick).toHaveBeenCalledWith('Basic Concept');
      // The card actions do not trigger the card callback
      fireEvent.click(screen.getByRole('button', { name: 'Ask Tutor about Basic Concept' }));
      expect(onConceptClick).toHaveBeenCalledTimes(1);
    });

    it('shows plain concept names without a callback', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);
      await screen.findByText('Basic Concept');

      expect(screen.queryByRole('button', { name: 'Basic Concept' })).not.toBeInTheDocument();
    });
  });

  describe('API Call', () => {
    it('refetches when conceptName changes', async () => {
      const { rerender } = render(<LearningPath conceptName="Concept A" />);
      await waitFor(() => expect(mockGetLearningPath).toHaveBeenCalledTimes(1));

      rerender(<LearningPath conceptName="Concept B" />);

      await waitFor(() => expect(mockGetLearningPath).toHaveBeenCalledTimes(2));
      expect(mockGetLearningPath).toHaveBeenLastCalledWith('Concept B', 5, 'us_history', expect.anything());
    });

    it('cancels the request when the concept changes or the path is unmounted', async () => {
      mockGetLearningPath.mockImplementation(() => new Promise(() => {}));
      const { rerender, unmount } = render(<LearningPath conceptName="Concept A" />);
      const firstSignal: AbortSignal = mockGetLearningPath.mock.calls[0][3].signal;

      rerender(<LearningPath conceptName="Concept B" />);
      expect(firstSignal.aborted).toBe(true);

      const secondSignal: AbortSignal = mockGetLearningPath.mock.calls[1][3].signal;
      unmount();
      expect(secondSignal.aborted).toBe(true);
    });
  });

  describe('Custom ClassName', () => {
    it('applies custom className', async () => {
      const { container } = render(
        <LearningPath conceptName="Test" className="custom-class" />
      );

      await screen.findByText('Basic Concept');
      expect(container.firstChild).toHaveClass('custom-class');
    });
  });

  describe('Progress Bars', () => {
    it('renders progress bars for each concept', async () => {
      const { container } = render(
        <LearningPath conceptName="Advanced Topic" />
      );

      await screen.findByText('Basic Concept');
      expect(container.querySelectorAll('.h-2.bg-gray-200')).toHaveLength(3);
    });
  });
});
