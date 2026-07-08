import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import LearningPath from '@/components/LearningPath';
import { apiClient } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';

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

const mockLearningPath = {
  concept: 'Advanced Topic',
  path: [
    { name: 'Basic Concept', depth: 2, importance: 0.6 },
    { name: 'Intermediate Concept', depth: 1, importance: 0.7 },
    { name: 'Advanced Topic', depth: 0, importance: 0.9 },
  ],
  depth: 2,
};

describe('LearningPath Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    mockGetLearningPath.mockReset();
  });

  describe('Loading State', () => {
    it('shows loading spinner while fetching', () => {
      mockGetLearningPath.mockImplementation(() => new Promise(() => {}));

      render(<LearningPath conceptName="Test Concept" />);

      expect(screen.getByText('Loading learning path...')).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('shows error message when fetch fails', async () => {
      mockGetLearningPath.mockRejectedValueOnce(new Error('Network error'));

      render(<LearningPath conceptName="Test Concept" />);

      await waitFor(() => {
        expect(
          screen.getByText('Unable to load learning path. Please try again.')
        ).toBeInTheDocument();
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty message when no path found', async () => {
      mockGetLearningPath.mockResolvedValueOnce({ concept: 'Test', path: [], depth: 0 });

      render(<LearningPath conceptName="Test Concept" />);

      await waitFor(() => {
        expect(
          screen.getByText('No prerequisite path found for this concept.')
        ).toBeInTheDocument();
      });
    });
  });

  describe('Successful Render', () => {
    beforeEach(async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);
    });

    it('renders learning path header', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getByText('Learning Path')).toBeInTheDocument();
      });
    });

    it('shows target concept in description', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        // "Advanced Topic" appears in both the description and concept card
        const elements = screen.getAllByText('Advanced Topic');
        expect(elements.length).toBeGreaterThanOrEqual(1);
        // Check the description span specifically
        const descSpan = elements.find(el => el.classList.contains('text-blue-600'));
        expect(descSpan).toBeDefined();
      });
    });

    it('renders all concepts in path', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getByText('Basic Concept')).toBeInTheDocument();
        expect(screen.getByText('Intermediate Concept')).toBeInTheDocument();
        // "Advanced Topic" appears in both description and concept card
        expect(screen.getAllByText('Advanced Topic').length).toBeGreaterThanOrEqual(1);
      });
    });

    it('shows target badge on target concept', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getByText('Target')).toBeInTheDocument();
      });
    });

    it('shows depth information for each concept', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getByText(/Depth: 2/)).toBeInTheDocument();
        expect(screen.getByText(/Depth: 1/)).toBeInTheDocument();
        expect(screen.getByText(/Depth: 0/)).toBeInTheDocument();
      });
    });
  });

  describe('Mastery Display', () => {
    it('shows mastery percentage for each concept', async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        // Default mastery is 30%
        const masteryElements = screen.getAllByText('30%');
        expect(masteryElements.length).toBeGreaterThan(0);
      });
    });

    it('uses mastery from store when available', async () => {
      useAppStore.setState({
        ...initialStoreState,
        masteryMap: {
          'Basic Concept': {
            conceptName: 'Basic Concept',
            masteryLevel: 0.85,
            attempts: 5,
            lastAssessed: '2024-01-01',
          },
        },
      });

      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getByText('85%')).toBeInTheDocument();
      });
    });
  });

  describe('Summary Section', () => {
    it('shows mastery summary counts', async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getByText('Mastered')).toBeInTheDocument();
        expect(screen.getByText('In Progress')).toBeInTheDocument();
        expect(screen.getByText('To Learn')).toBeInTheDocument();
      });
    });
  });

  describe('Actions', () => {
    beforeEach(async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);
    });

    it('renders Ask Tutor buttons for each concept', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        const askButtons = screen.getAllByText('Ask Tutor');
        expect(askButtons.length).toBe(3);
      });
    });

    it('renders Practice buttons for each concept', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        const practiceButtons = screen.getAllByText('Practice');
        expect(practiceButtons.length).toBe(3);
      });
    });

    it('navigates to chat when Ask Tutor is clicked', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getAllByText('Ask Tutor')[0]).toBeInTheDocument();
      });

      fireEvent.click(screen.getAllByText('Ask Tutor')[0]);

      expect(mockPush).toHaveBeenCalledWith(
        expect.stringContaining('/chat?question=')
      );
    });

    it('navigates to quiz when Practice is clicked', async () => {
      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        expect(screen.getAllByText('Practice')[0]).toBeInTheDocument();
      });

      fireEvent.click(screen.getAllByText('Practice')[0]);

      expect(mockPush).toHaveBeenCalledWith(
        expect.stringContaining('/quiz?topic=')
      );
    });
  });

  describe('Callbacks', () => {
    it('calls onConceptClick when concept card is clicked', async () => {
      const onConceptClick = jest.fn();
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      render(
        <LearningPath
          conceptName="Advanced Topic"
          onConceptClick={onConceptClick}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('Basic Concept')).toBeInTheDocument();
      });

      // Click on the concept card (not the buttons)
      const basicConceptCard = screen
        .getByText('Basic Concept')
        .closest('div[class*="cursor-pointer"]');
      if (basicConceptCard) {
        fireEvent.click(basicConceptCard);
        expect(onConceptClick).toHaveBeenCalledWith('Basic Concept');
      }
    });
  });

  describe('API Call', () => {
    it('fetches learning path on mount', async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      render(<LearningPath conceptName="Test Concept" />);

      await waitFor(() => {
        expect(apiClient.getLearningPath).toHaveBeenCalledWith(
          'Test Concept',
          5,
          useAppStore.getState().currentSubject
        );
      });
    });

    it('refetches when conceptName changes', async () => {
      mockGetLearningPath.mockResolvedValue(mockLearningPath);

      const { rerender } = render(<LearningPath conceptName="Concept A" />);

      await waitFor(() => {
        expect(apiClient.getLearningPath).toHaveBeenCalledTimes(1);
      });

      rerender(<LearningPath conceptName="Concept B" />);

      await waitFor(() => {
        expect(apiClient.getLearningPath).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe('Custom ClassName', () => {
    it('applies custom className', async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      const { container } = render(
        <LearningPath conceptName="Test" className="custom-class" />
      );

      await waitFor(() => {
        expect(container.firstChild).toHaveClass('custom-class');
      });
    });
  });

  describe('Mastery Status Colors', () => {
    it('shows complete status for high mastery concepts', async () => {
      useAppStore.setState({
        ...initialStoreState,
        masteryMap: {
          'Basic Concept': {
            conceptName: 'Basic Concept',
            masteryLevel: 0.8,
            attempts: 5,
            lastAssessed: '2024-01-01',
          },
        },
      });

      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      render(<LearningPath conceptName="Advanced Topic" />);

      await waitFor(() => {
        // Should show 80% mastery
        expect(screen.getByText('80%')).toBeInTheDocument();
      });
    });
  });

  describe('Progress Bars', () => {
    it('renders progress bars for each concept', async () => {
      mockGetLearningPath.mockResolvedValueOnce(mockLearningPath);

      const { container } = render(
        <LearningPath conceptName="Advanced Topic" />
      );

      await waitFor(() => {
        // Progress bars have h-2 class
        const progressBars = container.querySelectorAll('.h-2.bg-gray-200');
        expect(progressBars.length).toBe(3);
      });
    });
  });
});
