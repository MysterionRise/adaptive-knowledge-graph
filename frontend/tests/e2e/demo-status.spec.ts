import { test, expect, demoStatus } from './fixtures';

test.describe('Demo Status Page', () => {
  test('shows the readiness report', async ({ page }) => {
    await page.goto('/demo-status');

    await expect(page.getByRole('heading', { name: 'Client Demo Status' })).toBeVisible();
    await expect(page.getByText('Demo ready')).toBeVisible();
    await expect(page.getByRole('heading', { name: demoStatus.positioning })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'OpenStax Subject Data' })).toBeVisible();
    await expect(page.getByText('US History', { exact: true })).toBeVisible();
  });

  test('explains how to recover when the API is unreachable', async ({ page, api }) => {
    api.on('GET /demo/status', { status: 502, json: { detail: 'Bad gateway' } });

    await page.goto('/demo-status');

    await expect(page.getByText(/Unable to load demo readiness/)).toBeVisible();
  });
});
