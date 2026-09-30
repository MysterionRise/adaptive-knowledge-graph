import { test, expect, graphStats } from './fixtures';
import type { Page } from '@playwright/test';

/** Value shown on the statistics card with the given title. */
const statValue = (page: Page, title: string) =>
  page.getByText(title, { exact: true }).locator('..').getByRole('heading');

async function expectStats(page: Page, stats: (typeof graphStats)[string]) {
  await expect(statValue(page, 'Exam Topics')).toHaveText(String(stats.concept_count));
  await expect(statValue(page, 'Study Modules')).toHaveText(String(stats.module_count));
  await expect(statValue(page, 'Connections')).toHaveText(String(stats.relationship_count));
}

test.describe('Home Page', () => {
  test('shows the heading and the default subject', async ({ page }) => {
    await page.goto('/');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Adaptive Knowledge Graph' })
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'US History' })).toBeVisible();
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

    await page.getByRole('button', { name: 'US History' }).click();
    await page.getByRole('option', { name: /Economics/ }).click();

    await expect(page.getByRole('button', { name: 'Economics' })).toBeVisible();
    await expectStats(page, graphStats.economics);
  });

  test('shows a notice when the statistics cannot be loaded', async ({ page, api }) => {
    api.on('GET /graph/stats', { status: 503, json: { detail: 'Neo4j unavailable' } });

    await page.goto('/');

    await expect(
      page.getByText('Unable to load statistics. Please ensure the backend is running.')
    ).toBeVisible();
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

  test('shows the OpenStax attribution', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('link', { name: 'OpenStax', exact: true })).toHaveAttribute(
      'href',
      'https://openstax.org/'
    );
    await expect(
      page.getByText(/open textbooks \(US History, Economics, Biology, World History\)/)
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'CC BY 4.0' })).toHaveAttribute(
      'href',
      'https://creativecommons.org/licenses/by/4.0/'
    );
  });
});
