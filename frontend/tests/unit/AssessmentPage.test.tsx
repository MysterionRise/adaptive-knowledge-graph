import { render, screen } from '@testing-library/react';
import AssessmentPage from '@/app/assessment/page';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
  }),
}));

// Mock the Quiz component
jest.mock('@/components/Quiz', () => {
  return function MockQuiz() {
    return <div data-testid="quiz-component">Quiz Component Mock</div>;
  };
});

// Mock the SubjectPicker component
jest.mock('@/components/SubjectPicker', () => {
  return function MockSubjectPicker() {
    return <div data-testid="subject-picker">Subject Picker Mock</div>;
  };
});

describe('AssessmentPage', () => {
  beforeEach(() => {
    mockPush.mockClear();
  });

  describe('Page Structure', () => {
    it('renders the page container with correct styling', () => {
      const { container } = render(<AssessmentPage />);

      const mainContainer = container.firstChild as HTMLElement;
      expect(mainContainer).toHaveClass('min-h-screen', 'bg-gray-50');
    });

    it('renders the content wrapper with max-width', () => {
      const { container } = render(<AssessmentPage />);

      const wrapper = container.querySelector('.max-w-7xl');
      expect(wrapper).toBeInTheDocument();
      expect(wrapper).toHaveClass('mx-auto', 'px-4');
    });
  });

  describe('Header', () => {
    it('renders the main heading', () => {
      render(<AssessmentPage />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent('Adaptive Assessment Engine');
    });

    it('applies correct heading styles', () => {
      render(<AssessmentPage />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveClass('text-3xl', 'font-extrabold', 'text-gray-900');
    });

    it('renders the subtitle', () => {
      render(<AssessmentPage />);

      expect(
        screen.getByText('Generated dynamically from trusted knowledge sources')
      ).toBeInTheDocument();
    });

    it('applies correct subtitle styles', () => {
      render(<AssessmentPage />);

      const subtitle = screen.getByText('Generated dynamically from trusted knowledge sources');
      expect(subtitle).toHaveClass('text-gray-600');
    });

    it('renders a back button', () => {
      render(<AssessmentPage />);

      const backButton = screen.getByRole('button', { name: /back to home/i });
      expect(backButton).toBeInTheDocument();
    });

    it('renders the SubjectPicker', () => {
      render(<AssessmentPage />);

      expect(screen.getByTestId('subject-picker')).toBeInTheDocument();
    });
  });

  describe('Quiz Component Integration', () => {
    it('renders the Quiz component', () => {
      render(<AssessmentPage />);

      expect(screen.getByTestId('quiz-component')).toBeInTheDocument();
    });

    it('Quiz component is rendered in the main section', () => {
      const { container } = render(<AssessmentPage />);

      const mainSection = container.querySelector('main');
      const quizComponent = screen.getByTestId('quiz-component');

      expect(mainSection).toBeInTheDocument();
      expect(quizComponent).toBeInTheDocument();
      expect(mainSection).toContainElement(quizComponent);
    });
  });

  describe('Layout and Spacing', () => {
    it('has proper main section padding', () => {
      const { container } = render(<AssessmentPage />);

      const mainSection = container.querySelector('main');
      expect(mainSection).toHaveClass('py-12');
    });

    it('uses responsive horizontal padding', () => {
      const { container } = render(<AssessmentPage />);

      const wrapper = container.querySelector('.max-w-7xl');
      expect(wrapper).toHaveClass('px-4', 'sm:px-6', 'lg:px-8');
    });
  });

  describe('Accessibility', () => {
    it('has proper heading hierarchy', () => {
      render(<AssessmentPage />);

      const h1 = screen.getByRole('heading', { level: 1 });
      expect(h1).toBeInTheDocument();
      expect(h1).toHaveTextContent('Adaptive Assessment Engine');
    });

    it('renders meaningful content description', () => {
      render(<AssessmentPage />);

      expect(
        screen.getByText(/dynamically from trusted knowledge sources/i)
      ).toBeInTheDocument();
    });

    it('back button has aria-label', () => {
      render(<AssessmentPage />);

      const backButton = screen.getByRole('button', { name: /back to home/i });
      expect(backButton).toHaveAttribute('aria-label', 'Back to home');
    });
  });

  describe('Responsive Design', () => {
    it('has responsive padding classes', () => {
      const { container } = render(<AssessmentPage />);

      const wrapper = container.querySelector('.max-w-7xl');
      expect(wrapper).toHaveClass('sm:px-6');
      expect(wrapper).toHaveClass('lg:px-8');
    });
  });

  describe('Semantic Structure', () => {
    it('uses semantic HTML structure', () => {
      const { container } = render(<AssessmentPage />);

      // Page has a containing div
      expect(container.firstChild).toBeInstanceOf(HTMLDivElement);

      // Has header and main sections
      expect(container.querySelector('header')).toBeInTheDocument();
      expect(container.querySelector('main')).toBeInTheDocument();

      // Has nested structure for content
      expect(container.querySelector('.max-w-7xl')).toBeInTheDocument();
    });
  });
});

describe('AssessmentPage Integration', () => {
  it('renders without crashing', () => {
    expect(() => render(<AssessmentPage />)).not.toThrow();
  });

  it('has a consistent layout structure', () => {
    const { container } = render(<AssessmentPage />);

    // Background should be gray
    expect(container.firstChild).toHaveClass('bg-gray-50');

    // Should have centered content
    expect(container.querySelector('.mx-auto')).toBeInTheDocument();

    // Should have header and main semantic elements
    expect(container.querySelector('header')).toBeInTheDocument();
    expect(container.querySelector('main')).toBeInTheDocument();
  });
});
