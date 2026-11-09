import { render, screen } from '@testing-library/react';
import AssessmentPage from '@/app/assessment/page';

// Mock next/navigation
const mockSearchParams = new URLSearchParams();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
  }),
  useSearchParams: () => mockSearchParams,
}));

// Mock the Quiz component
jest.mock('@/components/Quiz', () => {
  return function MockQuiz({ initialTopic }: { initialTopic?: string }) {
    return (
      <div data-testid="quiz-component">
        Quiz Component Mock
        {initialTopic && <span data-testid="initial-topic">{initialTopic}</span>}
      </div>
    );
  };
});

describe('AssessmentPage', () => {
  beforeEach(() => {
    mockSearchParams.delete('topic');
  });

  describe('Page Structure', () => {
    it('renders the content wrapper with max-width', () => {
      const { container } = render(<AssessmentPage />);

      const wrapper = container.querySelector('.max-w-7xl');
      expect(wrapper).toBeInTheDocument();
      expect(wrapper).toHaveClass('mx-auto', 'px-4', 'sm:px-6', 'lg:px-8');
    });

    it('uses semantic HTML structure', () => {
      const { container } = render(<AssessmentPage />);

      expect(container.querySelector('header')).toBeInTheDocument();
      expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content');
      expect(screen.getByRole('main')).toHaveClass('py-12');
    });
  });

  describe('Header', () => {
    it('renders the main heading', () => {
      render(<AssessmentPage />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent('Adaptive Assessment Engine');
    });
  });

  describe('Quiz Component Integration', () => {
    it('renders the Quiz component in the main section', () => {
      render(<AssessmentPage />);

      expect(screen.getByRole('main')).toContainElement(screen.getByTestId('quiz-component'));
      expect(screen.queryByTestId('initial-topic')).not.toBeInTheDocument();
    });

    it('passes the topic from the URL to the quiz', () => {
      mockSearchParams.set('topic', '  Colonial America ');

      render(<AssessmentPage />);

      expect(screen.getByTestId('initial-topic')).toHaveTextContent('Colonial America');
    });

    it('ignores an empty topic parameter', () => {
      mockSearchParams.set('topic', '   ');

      render(<AssessmentPage />);

      expect(screen.queryByTestId('initial-topic')).not.toBeInTheDocument();
    });
  });
});
