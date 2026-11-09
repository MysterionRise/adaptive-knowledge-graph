import { render, screen, within } from '@testing-library/react';
import PageHeader from '@/components/PageHeader';

describe('PageHeader', () => {
  it('renders the title as the level-1 heading of the page banner', () => {
    render(<PageHeader title="Knowledge Graph Visualization" />);

    const banner = screen.getByRole('banner');
    expect(
      within(banner).getByRole('heading', { level: 1, name: 'Knowledge Graph Visualization' })
    ).toBeInTheDocument();
    expect(within(banner).queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders the actions in the banner', () => {
    render(
      <PageHeader title="Demo Status" actions={<button type="button">Refresh</button>} />
    );

    expect(screen.getByRole('banner')).toContainElement(
      screen.getByRole('button', { name: 'Refresh' })
    );
  });

  it('sizes the band like the page content', () => {
    const { container } = render(
      <PageHeader title="About" maxWidthClassName="max-w-4xl" className="shrink-0" />
    );

    expect(container.querySelector('header')).toHaveClass('shrink-0');
    expect(container.querySelector('.max-w-4xl')).toBeInTheDocument();
    expect(container.querySelector('.max-w-7xl')).not.toBeInTheDocument();
  });
});
