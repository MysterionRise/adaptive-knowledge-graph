import { render, screen } from '@testing-library/react';
import AssessmentPage from '@/app/assessment/page';

// Mock the Quiz component
jest.mock('@/components/Quiz', () => {
  return function MockQuiz() {
    return <div data-testid="quiz-component">Quiz Component Mock</div>;
  };
});

describe('AssessmentPage', () => {
  describe('Page Structure', () => {
    it('renders the page container with correct styling', () => {
      const { container } = render(<AssessmentPage />);

      const mainContainer = container.firstChild as HTMLElement;
      expect(mainContainer).toHaveClass('min-h-screen', 'bg-gray-50', 'py-12');
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

    it('centers the header text', () => {
      const { container } = render(<AssessmentPage />);

      const headerContainer = container.querySelector('.text-center');
      expect(headerContainer).toBeInTheDocument();
    });
  });

  describe('Quiz Component Integration', () => {
    it('renders the Quiz component', () => {
      render(<AssessmentPage />);

      expect(screen.getByTestId('quiz-component')).toBeInTheDocument();
    });

    it('Quiz component is rendered below the header', () => {
      const { container } = render(<AssessmentPage />);

      const headerSection = container.querySelector('.text-center.mb-10');
      const quizComponent = screen.getByTestId('quiz-component');

      expect(headerSection).toBeInTheDocument();
      expect(quizComponent).toBeInTheDocument();

      // Quiz should come after header in the DOM
      const allElements = container.querySelectorAll('.text-center, [data-testid="quiz-component"]');
      expect(allElements[0]).toHaveClass('text-center');
      expect(allElements[1]).toHaveAttribute('data-testid', 'quiz-component');
    });
  });

  describe('Layout and Spacing', () => {
    it('has proper vertical padding', () => {
      const { container } = render(<AssessmentPage />);

      const mainContainer = container.firstChild as HTMLElement;
      expect(mainContainer).toHaveClass('py-12');
    });

    it('has proper header margin', () => {
      const { container } = render(<AssessmentPage />);

      const headerSection = container.querySelector('.mb-10');
      expect(headerSection).toBeInTheDocument();
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

      // The subtitle provides context about the page
      expect(
        screen.getByText(/dynamically from trusted knowledge sources/i)
      ).toBeInTheDocument();
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

      // Has nested structure for content
      expect(container.querySelector('.max-w-7xl')).toBeInTheDocument();
    });
  });
});

describe('AssessmentPage Integration', () => {
  // These tests verify the page works correctly with the actual Quiz component
  // In a real scenario, you'd use the actual component for integration tests

  it('renders without crashing', () => {
    expect(() => render(<AssessmentPage />)).not.toThrow();
  });

  it('has a consistent layout structure', () => {
    const { container } = render(<AssessmentPage />);

    // Background should be gray
    expect(container.firstChild).toHaveClass('bg-gray-50');

    // Should have centered content
    expect(container.querySelector('.mx-auto')).toBeInTheDocument();

    // Should have text-center for header
    expect(container.querySelector('.text-center')).toBeInTheDocument();
  });
});
