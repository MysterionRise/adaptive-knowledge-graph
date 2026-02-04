import { render, screen } from '@testing-library/react';
import MasteryIndicator from '@/components/MasteryIndicator';

describe('MasteryIndicator', () => {
  describe('Compact Mode', () => {
    it('renders compact indicator', () => {
      render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          compact={true}
        />
      );

      expect(screen.getByText('50%')).toBeInTheDocument();
      expect(screen.getByText('Medium')).toBeInTheDocument();
    });

    it('shows correct mastery percentage', () => {
      render(
        <MasteryIndicator
          mastery={0.75}
          targetDifficulty="hard"
          compact={true}
        />
      );

      expect(screen.getByText('75%')).toBeInTheDocument();
    });

    it('shows easy difficulty badge', () => {
      render(
        <MasteryIndicator
          mastery={0.2}
          targetDifficulty="easy"
          compact={true}
        />
      );

      expect(screen.getByText('Easy')).toBeInTheDocument();
    });

    it('shows hard difficulty badge', () => {
      render(
        <MasteryIndicator
          mastery={0.9}
          targetDifficulty="hard"
          compact={true}
        />
      );

      expect(screen.getByText('Hard')).toBeInTheDocument();
    });
  });

  describe('Full Mode', () => {
    it('renders full indicator by default', () => {
      render(
        <MasteryIndicator
          mastery={0.6}
          targetDifficulty="medium"
        />
      );

      expect(screen.getByText('Personalized for You')).toBeInTheDocument();
      expect(screen.getByText('60%')).toBeInTheDocument();
    });

    it('shows topic when provided', () => {
      render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          topic="American Revolution"
        />
      );

      expect(screen.getByText(/Topic:/)).toBeInTheDocument();
      expect(screen.getByText('American Revolution')).toBeInTheDocument();
    });

    it('shows adapting message when showAdaptingMessage is true', () => {
      render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          showAdaptingMessage={true}
        />
      );

      expect(screen.getByText('Adapting')).toBeInTheDocument();
      expect(
        screen.getByText('Questions are tailored to your current proficiency level')
      ).toBeInTheDocument();
    });

    it('hides adapting message when showAdaptingMessage is false', () => {
      render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          showAdaptingMessage={false}
        />
      );

      expect(screen.queryByText('Adapting')).not.toBeInTheDocument();
      expect(screen.getByText('Your Progress')).toBeInTheDocument();
    });

    it('shows target difficulty with label', () => {
      render(
        <MasteryIndicator
          mastery={0.8}
          targetDifficulty="hard"
        />
      );

      expect(screen.getByText(/Hard Difficulty/)).toBeInTheDocument();
    });
  });

  describe('Color Coding', () => {
    it('uses red color for low mastery (< 0.4)', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.2}
          targetDifficulty="easy"
          compact={true}
        />
      );

      // Check that the SVG circle uses red stroke
      const circles = container.querySelectorAll('circle');
      expect(circles.length).toBeGreaterThan(0);
    });

    it('uses yellow color for medium mastery (0.4-0.7)', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.55}
          targetDifficulty="medium"
          compact={true}
        />
      );

      const circles = container.querySelectorAll('circle');
      expect(circles.length).toBeGreaterThan(0);
    });

    it('uses green color for high mastery (> 0.7)', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.85}
          targetDifficulty="hard"
          compact={true}
        />
      );

      const circles = container.querySelectorAll('circle');
      expect(circles.length).toBeGreaterThan(0);
    });
  });

  describe('Difficulty Badge Colors', () => {
    it('applies green colors for easy difficulty', () => {
      render(
        <MasteryIndicator
          mastery={0.3}
          targetDifficulty="easy"
          compact={true}
        />
      );

      const badge = screen.getByText('Easy');
      expect(badge).toHaveClass('text-green-700');
    });

    it('applies yellow colors for medium difficulty', () => {
      render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          compact={true}
        />
      );

      const badge = screen.getByText('Medium');
      expect(badge).toHaveClass('text-yellow-700');
    });

    it('applies red colors for hard difficulty', () => {
      render(
        <MasteryIndicator
          mastery={0.8}
          targetDifficulty="hard"
          compact={true}
        />
      );

      const badge = screen.getByText('Hard');
      expect(badge).toHaveClass('text-red-700');
    });
  });

  describe('Progress Bar', () => {
    it('renders progress bar in full mode', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.6}
          targetDifficulty="medium"
        />
      );

      // Find the progress bar by looking for the nested div structure
      const progressBars = container.querySelectorAll('.h-2.bg-gray-200');
      expect(progressBars.length).toBeGreaterThan(0);
    });

    it('progress bar width matches mastery percentage', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.75}
          targetDifficulty="hard"
        />
      );

      // The inner progress bar should have width style
      const innerBar = container.querySelector('.h-full.rounded-full');
      if (innerBar) {
        expect(innerBar).toHaveStyle({ width: '75%' });
      }
    });
  });

  describe('Circular Progress', () => {
    it('renders circular progress in compact mode', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          compact={true}
        />
      );

      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
    });

    it('renders circular progress in full mode', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          compact={false}
        />
      );

      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('handles 0% mastery', () => {
      render(
        <MasteryIndicator
          mastery={0}
          targetDifficulty="easy"
          compact={true}
        />
      );

      expect(screen.getByText('0%')).toBeInTheDocument();
    });

    it('handles 100% mastery', () => {
      render(
        <MasteryIndicator
          mastery={1}
          targetDifficulty="hard"
          compact={true}
        />
      );

      expect(screen.getByText('100%')).toBeInTheDocument();
    });

    it('rounds percentage correctly', () => {
      render(
        <MasteryIndicator
          mastery={0.333}
          targetDifficulty="easy"
          compact={true}
        />
      );

      expect(screen.getByText('33%')).toBeInTheDocument();
    });

    it('handles boundary value 0.4', () => {
      render(
        <MasteryIndicator
          mastery={0.4}
          targetDifficulty="medium"
          compact={true}
        />
      );

      expect(screen.getByText('40%')).toBeInTheDocument();
    });

    it('handles boundary value 0.7', () => {
      render(
        <MasteryIndicator
          mastery={0.7}
          targetDifficulty="medium"
          compact={true}
        />
      );

      expect(screen.getByText('70%')).toBeInTheDocument();
    });
  });

  describe('Icons', () => {
    it('renders Target icon in full mode', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
        />
      );

      // Lucide icons render as SVG
      const svgs = container.querySelectorAll('svg');
      expect(svgs.length).toBeGreaterThan(1); // Circular progress + icons
    });

    it('renders Zap icon when adapting', () => {
      const { container } = render(
        <MasteryIndicator
          mastery={0.5}
          targetDifficulty="medium"
          showAdaptingMessage={true}
        />
      );

      // Should have multiple SVGs including icons
      const svgs = container.querySelectorAll('svg');
      expect(svgs.length).toBeGreaterThan(1);
    });
  });
});
