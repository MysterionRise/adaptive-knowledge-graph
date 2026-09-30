import { fireEvent, render, screen, within } from '@testing-library/react';
import PostQuizRecommendations from '@/components/PostQuizRecommendations';
import type { RecommendationResponse } from '@/lib/types';

const longText = `${'The Stamp Act taxed printed materials in the colonies. '.repeat(5)}End of passage.`;

const remediation: RecommendationResponse = {
  path_type: 'remediation',
  score_pct: 33,
  summary: 'Review the prerequisites of the American Revolution.',
  remediation: [
    {
      concept: 'The American Revolution',
      prerequisites: [
        { name: 'Stamp Act', mastery: 0.2, relationship_type: 'PREREQ' },
        { name: 'Boston Tea Party', mastery: null, relationship_type: 'RELATED' },
      ],
      reading_materials: [
        { text: longText, module_title: 'The Road to Revolution', section: 'Colonial Resistance' },
        { text: 'A short passage.' },
      ],
    },
    { concept: 'Loyalists', prerequisites: [], reading_materials: [] },
  ],
  advancement: [],
};

const advancement: RecommendationResponse = {
  path_type: 'advancement',
  score_pct: 100,
  summary: 'Great work! You are ready for the next topic.',
  remediation: [],
  advancement: [
    {
      concept: 'The Constitution',
      advanced_topics: [
        { name: 'Bill of Rights', mastery: 0.55 },
        { name: 'Federalism' },
      ],
      deep_dive_content: 'The Constitution replaced the Articles of Confederation.\nIt took effect in 1789.',
    },
    { concept: 'Civil War', advanced_topics: [], deep_dive_content: null },
  ],
};

function renderRecommendations(
  props: Partial<React.ComponentProps<typeof PostQuizRecommendations>> = {}
) {
  const handlers = { onPractice: jest.fn(), onAskTutor: jest.fn(), onRetry: jest.fn() };
  render(
    <PostQuizRecommendations
      recommendations={null}
      isLoading={false}
      error={null}
      {...handlers}
      {...props}
    />
  );
  return handlers;
}

describe('PostQuizRecommendations', () => {
  it('shows a placeholder while loading', () => {
    renderRecommendations({ isLoading: true, recommendations: remediation });

    expect(screen.getByRole('status')).toHaveTextContent('Loading recommendations');
    expect(screen.queryByText(remediation.summary)).not.toBeInTheDocument();
  });

  it('renders nothing without recommendations', () => {
    const { container } = render(
      <PostQuizRecommendations
        recommendations={null}
        isLoading={false}
        error={null}
        onPractice={jest.fn()}
        onAskTutor={jest.fn()}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  describe('errors', () => {
    it('shows the error with a retry action', () => {
      const { onRetry } = renderRecommendations({ error: 'Unable to load recommendations: timeout.' });

      expect(screen.getByRole('alert')).toHaveTextContent('Unable to load recommendations: timeout.');
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
      expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it('shows the error without a retry action when none is given', () => {
      render(
        <PostQuizRecommendations
          recommendations={null}
          isLoading={false}
          error="Unable to load recommendations."
          onPractice={jest.fn()}
          onAskTutor={jest.fn()}
        />
      );

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    });
  });

  describe('remediation', () => {
    it('shows the summary and the concepts to strengthen', () => {
      renderRecommendations({ recommendations: remediation });

      expect(screen.getByText(remediation.summary)).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Areas to Strengthen' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'The American Revolution' })).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Ready to Advance' })).not.toBeInTheDocument();
    });

    it('shows each prerequisite with its relationship and mastery', () => {
      renderRecommendations({ recommendations: remediation });

      const stampAct = screen.getByText('Stamp Act').closest('div.p-3') as HTMLElement;
      expect(within(stampAct).getByText('Prerequisite')).toBeInTheDocument();
      expect(within(stampAct).getByText('20%')).toBeInTheDocument();

      const teaParty = screen.getByText('Boston Tea Party').closest('div.p-3') as HTMLElement;
      expect(within(teaParty).getByText('Related')).toBeInTheDocument();
      // Unknown mastery is shown as the initial mastery
      expect(within(teaParty).getByText('30%')).toBeInTheDocument();
    });

    it('lets the learner practise a prerequisite or ask the tutor about it', () => {
      const { onPractice, onAskTutor } = renderRecommendations({ recommendations: remediation });

      fireEvent.click(screen.getByRole('button', { name: 'Practice This: Stamp Act' }));
      fireEvent.click(screen.getByRole('button', { name: 'Ask Tutor about Boston Tea Party' }));

      expect(onPractice).toHaveBeenCalledWith('Stamp Act');
      expect(onAskTutor).toHaveBeenCalledWith('Boston Tea Party');
    });

    it('shows a preview of long reading material that can be expanded', () => {
      renderRecommendations({ recommendations: remediation });

      expect(screen.getByText('The Road to Revolution')).toBeInTheDocument();
      expect(screen.getByText(/Colonial Resistance/)).toBeInTheDocument();
      expect(screen.queryByText(/End of passage/)).not.toBeInTheDocument();

      const readMore = screen.getByRole('button', { name: 'Read more' });
      expect(readMore).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(readMore);

      expect(screen.getByText(/End of passage/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Show less' }));
      expect(screen.queryByText(/End of passage/)).not.toBeInTheDocument();
    });

    it('shows short reading material in full', () => {
      renderRecommendations({ recommendations: remediation });

      expect(screen.getByText(/A short passage\./)).toBeInTheDocument();
      expect(screen.getAllByRole('button', { name: 'Read more' })).toHaveLength(1);
    });

    it('suggests the tutor when a concept has no prerequisites or reading', () => {
      renderRecommendations({ recommendations: remediation });

      expect(
        screen.getByText('No prerequisite path found. Try asking the tutor for guidance on this topic.')
      ).toBeInTheDocument();
    });
  });

  describe('advancement', () => {
    it('suggests topics to explore next', () => {
      const { onPractice } = renderRecommendations({ recommendations: advancement });

      expect(screen.getByRole('heading', { name: 'Ready to Advance' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Bill of Rights (55%)' })).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Federalism' }));
      expect(onPractice).toHaveBeenCalledWith('Federalism');
    });

    it('shows the deep dive content', () => {
      renderRecommendations({ recommendations: advancement });

      expect(screen.getByText('Deep Dive')).toBeInTheDocument();
      expect(screen.getByText(/replaced the Articles of Confederation/)).toBeInTheDocument();
    });

    it('congratulates the learner at the frontier of the graph', () => {
      renderRecommendations({ recommendations: advancement });

      expect(
        screen.getByText("You've reached the frontier! Keep exploring related topics.")
      ).toBeInTheDocument();
    });
  });
});
