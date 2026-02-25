import { test, expect } from '@playwright/test';
import { DATA_TIMEOUT } from './helpers';

test.describe('Subject Switching — Integration', () => {
  test('should refresh stats when switching subjects', async ({ page }) => {
    await page.goto('/');

    // Wait for initial stats to load (us_history by default)
    const initialStatsResponse = await page.waitForResponse(
      (res) => res.url().includes('/graph/stats') && res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );
    const initialStats = await initialStatsResponse.json();

    // Set up response listener BEFORE clicking to avoid race condition
    const newStatsPromise = page.waitForResponse(
      (res) =>
        res.url().includes('/graph/stats') &&
        res.url().includes('economics') &&
        res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );

    // Open the subject picker and switch to Economics
    await page.locator('[aria-haspopup="listbox"]').click();
    await page.getByRole('option', { name: /Economics/i }).click();

    // Wait for new stats with economics subject
    const newStatsResponse = await newStatsPromise;
    const newStats = await newStatsResponse.json();

    // Stats should differ between subjects (at least one value should be different)
    const statsChanged =
      initialStats.concept_count !== newStats.concept_count ||
      initialStats.module_count !== newStats.module_count ||
      initialStats.relationship_count !== newStats.relationship_count;
    expect(statsChanged).toBe(true);
  });

  test('should update chat example questions when switching subjects', async ({ page }) => {
    await page.goto('/chat');

    // Verify US History examples are shown by default
    await expect(
      page.getByText('What caused the American Revolution?')
    ).toBeVisible({ timeout: DATA_TIMEOUT });

    // Switch to Economics
    await page.locator('[aria-haspopup="listbox"]').click();
    await page.getByRole('option', { name: /Economics/i }).click();

    // Verify Economics examples appear
    await expect(
      page.getByText('How do supply and demand determine prices?')
    ).toBeVisible({ timeout: DATA_TIMEOUT });

    // US History example should no longer be visible
    await expect(
      page.getByText('What caused the American Revolution?')
    ).not.toBeVisible();
  });
});
