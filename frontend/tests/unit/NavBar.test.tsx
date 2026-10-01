import { render, screen, within } from '@testing-library/react';
import NavBar from '@/components/NavBar';

var mockPathname: string | null;
jest.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

const nav = () => screen.getByRole('navigation', { name: 'Main' });

describe('NavBar', () => {
  beforeEach(() => {
    mockPathname = '/';
  });

  it('links to every page', () => {
    render(<NavBar />);

    const links = within(nav()).getAllByRole('link');
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Adaptive Knowledge Graph', '/'],
      ['Graph', '/graph'],
      ['AI Tutor', '/chat'],
      ['Compare', '/comparison'],
      ['Assessment', '/assessment'],
      ['Demo Status', '/demo-status'],
      ['About', '/about'],
    ]);
  });

  it('marks the home link on the home page', () => {
    render(<NavBar />);

    expect(within(nav()).getByRole('link', { name: 'Adaptive Knowledge Graph' })).toHaveAttribute(
      'aria-current',
      'page'
    );
    expect(within(nav()).getByRole('link', { name: 'Graph' })).not.toHaveAttribute('aria-current');
  });

  it('marks the current page', () => {
    mockPathname = '/comparison';

    render(<NavBar />);

    expect(within(nav()).getByRole('link', { name: 'Compare' })).toHaveAttribute('aria-current', 'page');
    expect(
      within(nav()).getByRole('link', { name: 'Adaptive Knowledge Graph' })
    ).not.toHaveAttribute('aria-current');
  });

  it('marks the section of a nested page', () => {
    mockPathname = '/graph/details';

    render(<NavBar />);

    expect(within(nav()).getByRole('link', { name: 'Graph' })).toHaveAttribute('aria-current', 'page');
  });

  it('marks nothing when the path is unknown', () => {
    mockPathname = null;

    render(<NavBar />);

    expect(within(nav()).queryAllByRole('link').filter((link) => link.hasAttribute('aria-current'))).toEqual([]);
  });
});
