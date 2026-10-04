/**
 * Root layout metadata, per-route titles, the error and not-found pages, the About page and the
 * providers shared by every page.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Metadata } from 'next';
import { metadata as rootMetadata } from '@/app/layout';
import GraphLayout, { metadata as graphMetadata } from '@/app/graph/layout';
import ChatLayout, { metadata as chatMetadata } from '@/app/chat/layout';
import ComparisonLayout, { metadata as comparisonMetadata } from '@/app/comparison/layout';
import AssessmentLayout, { metadata as assessmentMetadata } from '@/app/assessment/layout';
import DemoStatusLayout, { metadata as demoStatusMetadata } from '@/app/demo-status/layout';
import AboutPage, { metadata as aboutMetadata } from '@/app/about/page';
import ErrorPage from '@/app/error';
import NotFound, { metadata as notFoundMetadata } from '@/app/not-found';
import { Providers } from '@/components/Providers';
import { useAppStore } from '@/lib/store';

describe('page titles', () => {
  it('uses the project name as the default title and template', () => {
    expect(rootMetadata.title).toEqual({
      default: 'Adaptive Knowledge Graph',
      template: '%s | Adaptive Knowledge Graph',
    });
    expect(rootMetadata.description).toMatch(/local-first adaptive learning/);
    expect(JSON.stringify(rootMetadata)).not.toMatch(/Professional Certifications|test prep/i);
  });

  it.each<[string, Metadata, string]>([
    ['graph', graphMetadata, 'Knowledge Graph'],
    ['chat', chatMetadata, 'AI Tutor'],
    ['comparison', comparisonMetadata, 'KG-RAG vs Regular RAG'],
    ['assessment', assessmentMetadata, 'Adaptive Assessment'],
    ['demo status', demoStatusMetadata, 'Demo Status'],
    ['about', aboutMetadata, 'About'],
    ['not found', notFoundMetadata, 'Page not found'],
  ])('gives the %s page its own title', (_page, metadata, title) => {
    expect(metadata.title).toBe(title);
  });

  it.each([
    ['graph', GraphLayout],
    ['chat', ChatLayout],
    ['comparison', ComparisonLayout],
    ['assessment', AssessmentLayout],
    ['demo status', DemoStatusLayout],
  ])('renders the %s page inside its layout', (_page, Layout) => {
    render(<Layout><p>Page content</p></Layout>);

    expect(screen.getByText('Page content')).toBeInTheDocument();
  });
});

describe('error page', () => {
  it('offers to try again and to go home', () => {
    const retry = jest.fn();

    render(<ErrorPage error={new Error('Render failed')} retry={retry} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('link', { name: 'Go to the home page' })).toHaveAttribute('href', '/');
    // Error details are only shown in development
    expect(screen.queryByText('Render failed')).not.toBeInTheDocument();
  });
});

describe('not-found page', () => {
  it('explains the missing page and links home', () => {
    render(<NotFound />);

    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to the home page' })).toHaveAttribute('href', '/');
  });
});

describe('about page', () => {
  it('describes the project without compliance or hardware claims', () => {
    const { container } = render(<AboutPage />);

    expect(screen.getByRole('heading', { level: 1, name: 'About' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Local-First' })).toBeInTheDocument();
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/FERPA|GDPR|compliant|RTX|WebSocket/);
    expect(text).toMatch(/server-sent events/);
    expect(text).toMatch(/A remote LLM provider is only used if you configure one/);
  });
});

describe('Providers', () => {
  const initialStoreState = useAppStore.getState();
  let loadSubjectTheme: jest.Mock;

  beforeEach(() => {
    loadSubjectTheme = jest.fn().mockResolvedValue(undefined);
    useAppStore.setState({ ...initialStoreState, loadSubjectTheme });
  });

  afterEach(() => {
    // Unmount first: restoring the real loader must not trigger a theme request
    cleanup();
    useAppStore.setState(initialStoreState);
  });

  it('renders the page and loads the theme of the current subject', () => {
    render(<Providers><p>Page content</p></Providers>);

    expect(screen.getByText('Page content')).toBeInTheDocument();
    expect(loadSubjectTheme).toHaveBeenCalledWith('us_history');
  });

  it('loads the theme again when the subject changes', () => {
    render(<Providers><p>Page content</p></Providers>);

    act(() => useAppStore.getState().setCurrentSubject('economics'));

    expect(loadSubjectTheme).toHaveBeenLastCalledWith('economics');
    expect(loadSubjectTheme).toHaveBeenCalledTimes(2);
  });
});
