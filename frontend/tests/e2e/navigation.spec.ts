import { test, expect } from './fixtures';

const pages = [
  { link: 'Graph', url: '/graph', heading: 'Knowledge Graph Visualization' },
  { link: 'AI Tutor', url: '/chat', heading: 'AI Tutor Chat' },
  { link: 'Compare', url: '/comparison', heading: 'KG-RAG vs Regular RAG Comparison' },
  { link: 'Assessment', url: '/assessment', heading: 'Adaptive Assessment Engine' },
  { link: 'Demo Status', url: '/demo-status', heading: 'Demo Status' },
  { link: 'About', url: '/about', heading: 'About' },
];

test.describe('Navigation', () => {
  test('reaches every page from the navigation bar', async ({ page }) => {
    await page.goto('/');
    const nav = page.getByRole('navigation', { name: 'Main' });

    for (const { link, url, heading } of pages) {
      await nav.getByRole('link', { name: link, exact: true }).click();

      await expect(page).toHaveURL(url);
      await expect(page.getByRole('heading', { level: 1, name: heading, exact: true })).toBeVisible();
      await expect(nav.getByRole('link', { name: link, exact: true })).toHaveAttribute(
        'aria-current',
        'page'
      );
    }

    await nav.getByRole('link', { name: 'Adaptive Knowledge Graph' }).click();
    await expect(page).toHaveURL('/');
  });

  test('offers a skip link to the main content', async ({ page }) => {
    await page.goto('/about');

    await page.keyboard.press('Tab');
    const skipLink = page.getByRole('link', { name: 'Skip to main content' });
    await expect(skipLink).toBeFocused();
    await expect(skipLink).toBeVisible();

    await page.keyboard.press('Enter');
    await expect(page).toHaveURL('/about#main-content');
  });

  test('shows a not-found page for unknown addresses', async ({ page }) => {
    const response = await page.goto('/no-such-page');

    expect(response?.status()).toBe(404);
    await expect(page).toHaveTitle('Page not found | Adaptive Knowledge Graph');
    await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();

    await page.getByRole('link', { name: 'Go to the home page' }).click();
    await expect(page).toHaveURL('/');
  });

  test('shows accurate project information on the About page', async ({ page }) => {
    await page.goto('/about');

    await expect(page).toHaveTitle('About | Adaptive Knowledge Graph');
    await expect(page.getByRole('main')).not.toContainText(/FERPA|GDPR|RTX|WebSocket/);
    await expect(page.getByText(/server-sent events for streamed answers/)).toBeVisible();
  });
});
