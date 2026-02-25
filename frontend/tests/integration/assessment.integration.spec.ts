import { test, expect } from '@playwright/test';
import { isOllamaAvailable, LLM_TIMEOUT, DATA_TIMEOUT } from './helpers';

test.describe('Assessment — Integration', () => {
  test('should show US History topics in the dropdown', async ({ page }) => {
    await page.goto('/assessment');

    const dropdown = page.locator('select');
    await expect(dropdown).toBeVisible({ timeout: DATA_TIMEOUT });

    // Check for US History topics
    await expect(dropdown.locator('option', { hasText: 'The American Revolution' })).toBeAttached();
    await expect(dropdown.locator('option', { hasText: 'The Civil War' })).toBeAttached();
  });

  test('should update topics when switching subjects', async ({ page }) => {
    await page.goto('/assessment');

    // Verify initial US History topic
    const dropdown = page.locator('select');
    await expect(dropdown.locator('option', { hasText: 'The American Revolution' })).toBeAttached({
      timeout: DATA_TIMEOUT,
    });

    // Switch to Economics
    await page.locator('[aria-haspopup="listbox"]').click();
    await page.getByRole('option', { name: /Economics/i }).click();

    // Verify Economics topics appear
    await expect(dropdown.locator('option', { hasText: 'Supply and Demand' })).toBeAttached({
      timeout: DATA_TIMEOUT,
    });
    await expect(dropdown.locator('option', { hasText: 'Fiscal Policy' })).toBeAttached();

    // US History topics should no longer be in the dropdown
    await expect(
      dropdown.locator('option', { hasText: 'The American Revolution' })
    ).not.toBeAttached();
  });

  test('should complete a full quiz flow', async ({ page }) => {
    const ollama = await isOllamaAvailable();
    test.skip(!ollama, 'Ollama is not available — skipping LLM test');
    test.setTimeout(LLM_TIMEOUT);

    await page.goto('/assessment');

    // Select a topic and start the quiz
    const dropdown = page.locator('select');
    await expect(dropdown).toBeVisible({ timeout: DATA_TIMEOUT });
    await dropdown.selectOption('The American Revolution');

    await page.getByText('Start Adaptive Assessment').click();

    // Wait for quiz generation (loading indicator)
    await expect(
      page.getByRole('heading', { name: /Crafting Your Personalized Quiz/i })
    ).toBeVisible({ timeout: 15_000 });

    // Wait for first question to appear
    await expect(page.getByText('Question 1 of 3')).toBeVisible({ timeout: LLM_TIMEOUT });

    // Answer 3 questions
    for (let i = 0; i < 3; i++) {
      // Wait for the question text
      await expect(page.getByText(`Question ${i + 1} of 3`)).toBeVisible({
        timeout: LLM_TIMEOUT,
      });

      // Select the first option
      const options = page.locator('button.w-full.text-left.p-4.rounded-lg.border-2');
      await expect(options.first()).toBeVisible({ timeout: 10_000 });
      await options.first().click();

      // Submit the answer
      await page.getByText('Submit Answer').click();

      // Wait for feedback
      await expect(
        page.getByText(/Correct!|Concept Gap Identified/i)
      ).toBeVisible({ timeout: 10_000 });

      // Click Next or Finish
      if (i < 2) {
        await page.getByText('Next Question').click();
      } else {
        await page.getByText('Finish Quiz').click();
      }
    }

    // Results modal should show the score
    await expect(page.getByText(/out of/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/questions correctly/i)).toBeVisible();
  });

  test('should display adaptive mode and mastery indicator', async ({ page }) => {
    const ollama = await isOllamaAvailable();
    test.skip(!ollama, 'Ollama is not available — skipping LLM test');

    await page.goto('/assessment');

    // Adaptive Mode toggle section should be visible
    await expect(page.getByText('Adaptive Mode')).toBeVisible({ timeout: DATA_TIMEOUT });

    // Mastery indicator should be shown when adaptive mode is on
    await expect(
      page.getByText('Questions will be tailored to your current proficiency level')
    ).toBeVisible();
  });
});
