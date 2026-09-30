import { test, expect, graphData } from './fixtures';

test.describe('Graph Visualization Page', () => {
  test('shows the page heading', async ({ page }) => {
    await page.goto('/graph');

    await expect(
      page.getByRole('heading', { name: 'Knowledge Graph Visualization' })
    ).toBeVisible();
    await expect(page.getByText('Explore concepts and their relationships')).toBeVisible();
  });

  test('renders the graph returned by the API', async ({ page, api }) => {
    await page.goto('/graph');

    await expect(page.locator('.cytoscape-container canvas').first()).toBeVisible();
    await expect(page.getByText('Nodes:').locator('..')).toContainText(
      String(graphData.nodes.length)
    );
    await expect(page.getByText('Edges:').locator('..')).toContainText(
      String(graphData.edges.length)
    );

    const url = new URL(api.calls('GET /graph/data')[0].url());
    expect(url.searchParams.get('subject')).toBe('us_history');
    expect(url.searchParams.get('limit')).toBe('100');
  });

  test('shows usage instructions', async ({ page }) => {
    await page.goto('/graph');

    await expect(page.getByRole('heading', { name: 'How to Use' })).toBeVisible();
    await expect(page.getByText('Click nodes to see details and relationships')).toBeVisible();
    await expect(page.getByText('Drag to pan, scroll to zoom')).toBeVisible();
  });

  test('shows the legend', async ({ page }) => {
    await page.goto('/graph');

    await expect(page.getByRole('heading', { name: 'Legend' })).toBeVisible();
    for (const entry of ['Prerequisite', 'Covers', 'Related', 'Highlighted']) {
      await expect(page.getByText(entry, { exact: true })).toBeVisible();
    }
  });

  test('offers zoom and view controls', async ({ page }) => {
    await page.goto('/graph');

    for (const control of ['Zoom in', 'Zoom out', 'Fit to view', 'Reset view']) {
      const button = page.getByRole('button', { name: control });
      await expect(button).toBeVisible();
      await button.click();
    }
  });

  test('shows an error when graph data cannot be loaded', async ({ page, api }) => {
    api.on('GET /graph/data', { status: 503, json: { detail: 'Neo4j unavailable' } });

    await page.goto('/graph');

    await expect(
      page.getByText('Failed to load graph data. Please ensure the backend is running.')
    ).toBeVisible();
    await expect(page.getByText('No graph data available')).toBeVisible();
  });

  test('navigates back to home', async ({ page }) => {
    await page.goto('/graph');

    await page.getByRole('button', { name: 'Back to home' }).click();

    await expect(page).toHaveURL('/');
  });
});
