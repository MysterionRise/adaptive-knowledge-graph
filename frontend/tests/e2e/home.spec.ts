import { test, expect } from '@playwright/test';

test.describe('Home Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should display the main heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Adaptive Knowledge Graph' })).toBeVisible();
  });

  test('should show statistics dashboard', async ({ page }) => {
    // Wait for statistics to load
    await expect(page.getByText('Concepts')).toBeVisible();
    await expect(page.getByText('Modules')).toBeVisible();
    await expect(page.getByText('Relationships')).toBeVisible();
  });

  test('should navigate to graph page', async ({ page }) => {
    await page.getByRole('link', { name: 'Explore Graph' }).click();
    await expect(page).toHaveURL('/graph');
    await expect(page.getByRole('heading', { name: /Knowledge Graph Visualization/i })).toBeVisible();
  });

  test('should navigate to chat page', async ({ page }) => {
    await page.getByRole('link', { name: 'Ask Questions' }).click();
    await expect(page).toHaveURL('/chat');
    await expect(page.getByRole('heading', { name: /AI Tutor Chat/i })).toBeVisible();
  });

  test('should display feature cards', async ({ page }) => {
    await expect(page.getByText('Knowledge Graph')).toBeVisible();
    await expect(page.getByText('AI Tutor Chat')).toBeVisible();
    await expect(page.getByText('KG-Aware RAG')).toBeVisible();
    await expect(page.getByText('Local-First')).toBeVisible();
  });

  test('should show OpenStax attribution', async ({ page }) => {
    await expect(page.getByText(/OpenStax Biology 2e/i)).toBeVisible();
    await expect(page.getByText(/CC BY 4.0/i)).toBeVisible();
  });
});
