import { test, expect } from '@playwright/test';

test.describe('Graph Visualization Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/graph');
  });

  test('should display graph page heading', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: /Knowledge Graph Visualization/i })
    ).toBeVisible();
  });

  test('should show graph visualization container', async ({ page }) => {
    // Wait for graph to load
    const graphContainer = page.locator('.cytoscape-container');
    await expect(graphContainer).toBeVisible();
  });

  test('should display instructions sidebar', async ({ page }) => {
    await expect(page.getByText('How to Use')).toBeVisible();
    await expect(page.getByText(/Click nodes to see details/i)).toBeVisible();
  });

  test('should show graph stats', async ({ page }) => {
    await expect(page.getByText('Graph Stats')).toBeVisible();
    await expect(page.getByText(/Nodes:/i)).toBeVisible();
    await expect(page.getByText(/Edges:/i)).toBeVisible();
  });

  test('should display legend', async ({ page }) => {
    await expect(page.getByText('Legend')).toBeVisible();
    await expect(page.getByText('Prerequisite')).toBeVisible();
    await expect(page.getByText('Covers')).toBeVisible();
    await expect(page.getByText('Related')).toBeVisible();
  });

  test('should show control buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Fit to View/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Center/i })).toBeVisible();
  });

  test('should navigate back to home', async ({ page }) => {
    await page.getByLabel('Back to home').click();
    await expect(page).toHaveURL('/');
  });
});
