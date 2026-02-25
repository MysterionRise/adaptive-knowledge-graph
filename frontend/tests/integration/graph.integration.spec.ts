import { test, expect } from '@playwright/test';
import { DATA_TIMEOUT } from './helpers';

test.describe('Graph Page — Integration', () => {
  test('should display real nodes and edges from Neo4j', async ({ page }) => {
    await page.goto('/graph');

    // Wait for graph data to load
    await page.waitForResponse(
      (res) => res.url().includes('/graph/data') && res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );

    // Sidebar should show nodes and edges counts
    const nodesLabel = page.locator('text=Nodes:');
    await expect(nodesLabel).toBeVisible({ timeout: DATA_TIMEOUT });

    // Get the node count value (sibling span)
    const nodesValue = nodesLabel.locator('..').locator('.font-medium');
    const nodesText = await nodesValue.textContent();
    expect(Number(nodesText)).toBeGreaterThan(0);

    const edgesLabel = page.locator('text=Edges:');
    await expect(edgesLabel).toBeVisible();
    const edgesValue = edgesLabel.locator('..').locator('.font-medium');
    const edgesText = await edgesValue.textContent();
    expect(Number(edgesText)).toBeGreaterThan(0);
  });

  test('should render a canvas element in the cytoscape container', async ({ page }) => {
    await page.goto('/graph');

    // Wait for graph data to finish loading
    await page.waitForResponse(
      (res) => res.url().includes('/graph/data') && res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );

    // The cytoscape container should have a canvas child
    const canvas = page.locator('.cytoscape-container canvas');
    await expect(canvas.first()).toBeVisible({ timeout: DATA_TIMEOUT });
  });

  test('should update graph when switching subjects', async ({ page }) => {
    await page.goto('/graph');

    // Wait for initial graph data
    const initialResponse = await page.waitForResponse(
      (res) => res.url().includes('/graph/data') && res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );
    const initialData = await initialResponse.json();
    const initialNodeNames = initialData.nodes.map((n: any) => n.data.label).sort().join(',');

    // Set up response listener BEFORE clicking to avoid race condition
    const responsePromise = page.waitForResponse(
      (res) =>
        res.url().includes('/graph/data') &&
        res.url().includes('economics') &&
        res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );

    // Switch to Economics
    await page.locator('[aria-haspopup="listbox"]').click();
    await page.getByRole('option', { name: /Economics/i }).click();

    // Wait for new graph data
    const newResponse = await responsePromise;
    const newData = await newResponse.json();
    const newNodeNames = newData.nodes.map((n: any) => n.data.label).sort().join(',');

    // Graph content should differ between subjects (different node IDs)
    expect(newData.nodes.length).toBeGreaterThan(0);
    expect(newNodeNames).not.toBe(initialNodeNames);
  });

  test('should handle Fit button click without errors', async ({ page }) => {
    await page.goto('/graph');

    // Wait for graph to load
    await page.waitForResponse(
      (res) => res.url().includes('/graph/data') && res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );

    // Click the "Fit to view" button
    await page.getByRole('button', { name: 'Fit to view' }).click();

    // No error banner should appear
    const errorBanner = page.locator('.bg-yellow-50.border.border-yellow-200');
    // If present, it means an error happened — we expect it NOT to be visible
    // (or to not exist at all after a successful fit)
    await expect(errorBanner).not.toBeVisible({ timeout: 3_000 });
  });
});
