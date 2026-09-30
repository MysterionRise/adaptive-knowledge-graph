import { render, screen } from '@testing-library/react';
import MarkdownContent from '@/components/MarkdownContent';

// react-markdown is ESM-only, so the unit test checks the options passed to it; the Playwright
// suite checks the rendered Markdown.
var mockMarkdownProps: Record<string, any>;
jest.mock('react-markdown', () => function MockMarkdown(props: Record<string, any>) {
  mockMarkdownProps = props;
  return <div data-testid="markdown">{props.children}</div>;
});

describe('MarkdownContent', () => {
  it('renders the Markdown source', () => {
    render(<MarkdownContent className="extra">{'**Bold** answer'}</MarkdownContent>);

    expect(screen.getByTestId('markdown')).toHaveTextContent('**Bold** answer');
    expect(screen.getByTestId('markdown').parentElement).toHaveClass('extra');
  });

  it('does not render images from the answer', () => {
    render(<MarkdownContent>{'![tracker](https://example.com/pixel.png)'}</MarkdownContent>);

    expect(mockMarkdownProps.disallowedElements).toEqual(['img']);
    expect(mockMarkdownProps.unwrapDisallowed).toBe(true);
  });

  it('opens links in a new tab without giving the page access to the opener', () => {
    render(<MarkdownContent>{'[OpenStax](https://openstax.org)'}</MarkdownContent>);
    const Link = mockMarkdownProps.components.a;

    render(<Link href="https://openstax.org" node={{ type: 'element' }}>OpenStax</Link>);

    const link = screen.getByRole('link', { name: 'OpenStax' });
    expect(link).toHaveAttribute('href', 'https://openstax.org');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).not.toHaveAttribute('node');
  });
});
