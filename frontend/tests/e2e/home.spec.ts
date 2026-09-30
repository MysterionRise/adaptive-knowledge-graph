import { test, expect, graphStats, topConcepts } from './fixtures';
import type { Page } from '@playwright/test';

const statsSection = (page: Page) =>
  page.getByRole('region', { name: 'Knowledge Graph Statistics' });

/** Value shown on the statistics card with the given title. */
const statValue = (page: Page, title: string) =>
  statsSection(page).getByText(title, { exact: true }).locator('..').getByRole('heading');

async function expectStats(page: Page, stats: (typeof graphStats)[string]) {
  await expect(statValue(page, 'Concepts')).toHaveText(String(stats.concept_count));
  await expect(statValue(page, 'Study Modules')).toHaveText(String(stats.module_count));
  await expect(statValue(page, 'Connections')).toHaveText(String(stats.relationship_count));
}

const subjectButton = (page: Page) => page.getByRole('button', { name: /^Subject:/ });

test.describe('Home Page', () => {
  test('shows the heading, the title and the default subject', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle('Adaptive Knowledge Graph');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Adaptive Knowledge Graph' })
    ).toBeVisible();
    await expect(subjectButton(page)).toHaveText('Subject: US History');
  });

  test('shows knowledge graph statistics for the current subject', async ({ page, api }) => {
    await page.goto('/');

    await expectStats(page, graphStats.us_history);
    expect(new URL(api.calls('GET /graph/stats')[0].url()).searchParams.get('subject')).toBe(
      'us_history'
    );
  });

  test('reloads the statistics when the subject changes', async ({ page }) => {
    await page.goto('/');
    await expectStats(page, graphStats.us_history);

    await subjectButton(page).click();
    await page.getByRole('option', { name: /Economics/ }).click();

    await expect(subjectButton(page)).toHaveText('Subject: Economics');
    await expectStats(page, graphStats.economics);
  });

  test('remembers the subject after a reload', async ({ page, api }) => {
    await page.goto('/');
    await subjectButton(page).click();
    await page.getByRole('option', { name: /Economics/ }).click();
    await expectStats(page, graphStats.economics);

    await page.reload();

    await expect(subjectButton(page)).toHaveText('Subject: Economics');
    await expectStats(page, graphStats.economics);
    const lastStats = api.calls('GET /graph/stats').at(-1);
    expect(new URL(lastStats!.url()).searchParams.get('subject')).toBe('economics');
  });

  test('shows subjects without data as "coming soon"', async ({ page }) => {
    await page.goto('/');

    await subjectButton(page).click();
    const listbox = page.getByRole('listbox', { name: 'Subjects' });
    const biology = listbox.getByRole('option', { name: /Biology/ });
    await expect(biology).toHaveAttribute('aria-disabled', 'true');
    await expect(biology).toContainText('Coming soon');
    await expect(listbox.getByRole('option', { name: /Economics/ })).not.toHaveAttribute(
      'aria-disabled'
    );

    // Playwright does not click disabled elements unless forced
    await biology.click({ force: true });

    await expect(listbox).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(subjectButton(page)).toHaveText('Subject: US History');
  });

  test('changes the subject with the keyboard', async ({ page }) => {
    await page.goto('/');

    await subjectButton(page).focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');

    await expect(subjectButton(page)).toHaveText('Subject: Economics');
    await expect(subjectButton(page)).toBeFocused();
  });

  test('shows the statistics error with a retry action', async ({ page, api }) => {
    api.on('GET /graph/stats', { status: 503, json: { detail: 'Neo4j unavailable' } });

    await page.goto('/');

    const alert = statsSection(page).getByRole('alert');
    await expect(alert).toContainText('Unable to load statistics.');
    await expect(alert).toContainText('Neo4j unavailable');

    api.on('GET /graph/stats', (request) => ({
      json: graphStats[new URL(request.url()).searchParams.get('subject') ?? 'us_history'],
    }));
    await statsSection(page).getByRole('button', { name: 'Retry' }).click();

    await expectStats(page, graphStats.us_history);
  });

  test('shows the suggested concepts error with a retry action', async ({ page, api }) => {
    api.on('GET /concepts/top', { status: 500, json: { detail: 'An internal error occurred' } });

    await page.goto('/');

    const section = page.getByRole('region', { name: 'Start Learning' });
    await expect(section.getByRole('alert')).toContainText('An internal error occurred');

    api.on('GET /concepts/top', { json: topConcepts });
    await section.getByRole('button', { name: 'Retry' }).click();

    await expect(section.getByRole('button', { name: /American Revolution/ })).toBeVisible();
  });

  test('invites a new student to start learning', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Start Your Learning Journey' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Take Assessment' })).toHaveAttribute(
      'href',
      '/assessment'
    );
    await expect(page.getByRole('link', { name: 'Ask AI Tutor' })).toHaveAttribute('href', '/chat');
  });

  test('opens the tutor from a suggested concept', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Start Learning' })).toBeVisible();
    await page.getByRole('button', { name: /American Revolution/ }).click();

    await expect(page).toHaveURL(/\/chat\?question=Explain(%20|\+)American(%20|\+)Revolution$/);
    await expect(page.getByText('Explain American Revolution', { exact: true })).toBeVisible();
  });

  test('navigates to the graph page', async ({ page }) => {
    await page.goto('/');

    await page.getByRole('link', { name: 'Explore Graph', exact: true }).click();

    await expect(page).toHaveURL('/graph');
    await expect(
      page.getByRole('heading', { name: 'Knowledge Graph Visualization' })
    ).toBeVisible();
  });

  test('navigates to the chat page', async ({ page }) => {
    await page.goto('/');

    await page.getByRole('link', { name: 'Ask Questions', exact: true }).click();

    await expect(page).toHaveURL('/chat');
    await expect(page.getByRole('heading', { name: 'AI Tutor Chat' })).toBeVisible();
  });

  test('lists the key features', async ({ page }) => {
    await page.goto('/');

    for (const feature of ['Knowledge Map', 'AI Tutor Chat', 'KG-Aware RAG', 'Local-First', 'Assessment']) {
      await expect(page.getByRole('heading', { level: 4, name: feature, exact: true })).toBeVisible();
    }
  });

  test('attributes the content of the available subjects', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('link', { name: 'OpenStax', exact: true })).toHaveAttribute(
      'href',
      'https://openstax.org/'
    );
    await expect(page.getByText(/open textbooks \(US History, Economics\)$/)).toBeVisible();
    await expect(page.getByRole('link', { name: 'CC BY 4.0' })).toHaveAttribute(
      'href',
      'https://creativecommons.org/licenses/by/4.0/'
    );
  });
});
