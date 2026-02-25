import { test, expect } from '@playwright/test';
import { isOllamaAvailable, LLM_TIMEOUT, DATA_TIMEOUT } from './helpers';

test.describe('Comparison Page — Integration', () => {
  test('should show subject-aware example questions', async ({ page }) => {
    await page.goto('/comparison');

    // Default subject (us_history) should show relevant examples
    await expect(
      page.getByText('What caused the American Revolution?')
    ).toBeVisible({ timeout: DATA_TIMEOUT });
    await expect(
      page.getByText('Explain the significance of the Constitution')
    ).toBeVisible();
  });

  test('should fill input when clicking an example question', async ({ page }) => {
    await page.goto('/comparison');

    // Click an example question button
    const exampleBtn = page.locator('button', {
      hasText: 'What caused the American Revolution?',
    });
    await exampleBtn.click();

    // Input should be populated
    const input = page.locator('#question');
    await expect(input).toHaveValue('What caused the American Revolution?');

    // Compare button should be enabled
    const compareBtn = page.getByRole('button', { name: /Compare Approaches/i });
    await expect(compareBtn).toBeEnabled();
  });

  test('should update examples when switching subjects', async ({ page }) => {
    await page.goto('/comparison');

    // Verify US History examples
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

  test('should run a full KG vs RAG comparison', async ({ page }) => {
    const ollama = await isOllamaAvailable();
    test.skip(!ollama, 'Ollama is not available — skipping LLM test');
    test.setTimeout(LLM_TIMEOUT);

    await page.goto('/comparison');

    // Enter a question
    const input = page.locator('#question');
    await input.fill('What caused the American Revolution?');

    // Click Compare
    await page.getByRole('button', { name: /Compare Approaches/i }).click();

    // Loading indicator should appear
    await expect(page.getByText('Comparing...')).toBeVisible({ timeout: 10_000 });

    // Wait for both panels to appear (use border-2 to distinguish panels from input)
    const kgPanel = page.locator('.border-2.border-green-300');
    const ragPanel = page.locator('.border-2.border-gray-300');

    await expect(kgPanel).toBeVisible({ timeout: LLM_TIMEOUT });
    await expect(ragPanel).toBeVisible({ timeout: LLM_TIMEOUT });

    // Both panels should have "Answer:" text
    await expect(kgPanel.getByText('Answer:')).toBeVisible({ timeout: 10_000 });
    await expect(ragPanel.getByText('Answer:')).toBeVisible({ timeout: 10_000 });

    // Both panels should have "Retrieved Chunks" stats
    await expect(kgPanel.getByText('Retrieved Chunks')).toBeVisible();
    await expect(ragPanel.getByText('Retrieved Chunks')).toBeVisible();

    // KG panel should show expanded concepts
    const conceptChips = kgPanel.locator('.bg-green-100.text-green-800');
    const chipCount = await conceptChips.count();
    expect(chipCount).toBeGreaterThan(0);
  });
});
