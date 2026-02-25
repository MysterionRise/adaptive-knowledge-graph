import { test, expect } from '@playwright/test';
import { isOllamaAvailable, LLM_TIMEOUT, DATA_TIMEOUT } from './helpers';

test.describe('Chat — Integration', () => {
  test('should show subject-aware example questions', async ({ page }) => {
    await page.goto('/chat');

    // Default subject (us_history) should show relevant examples
    await expect(
      page.getByText('What caused the American Revolution?')
    ).toBeVisible({ timeout: DATA_TIMEOUT });
    await expect(
      page.getByText('Explain the significance of the Constitution')
    ).toBeVisible();
  });

  test('should stream a full answer from the LLM', async ({ page }) => {
    const ollama = await isOllamaAvailable();
    test.skip(!ollama, 'Ollama is not available — skipping LLM test');
    test.setTimeout(LLM_TIMEOUT);

    await page.goto('/chat');

    // Type a question and send
    await page.getByPlaceholder('Ask a question...').fill('What caused the American Revolution?');
    await page.getByRole('button', { name: /Send/i }).click();

    // "Thinking..." indicator should appear
    await expect(page.getByText('Thinking...')).toBeVisible({ timeout: 10_000 });

    // Wait for the full response by looking for "Show Sources" which only appears
    // after streaming is complete and the response object is rendered
    const sourcesBtn = page.getByText(/Show Sources/i);
    await expect(sourcesBtn).toBeVisible({ timeout: LLM_TIMEOUT });

    // Now verify the assistant message has substantial content
    const assistantMsg = page.locator('.bg-white.border.border-gray-200.shadow-sm').last();
    const text = await assistantMsg.textContent();
    expect(text!.length).toBeGreaterThan(50);

    // Click to expand sources
    await sourcesBtn.click();

    // At least one source card should appear
    const sourceCards = page.locator('.bg-gray-50.border.border-gray-200.rounded-lg.text-sm');
    await expect(sourceCards.first()).toBeVisible({ timeout: 5_000 });
  });

  test('should display KG expansion concepts when toggle is on', async ({ page }) => {
    const ollama = await isOllamaAvailable();
    test.skip(!ollama, 'Ollama is not available — skipping LLM test');
    test.setTimeout(LLM_TIMEOUT);

    await page.goto('/chat');

    // KG Expansion toggle should be on by default — verify label is visible
    await expect(page.getByText('KG Expansion')).toBeVisible();

    // Ask a question
    await page.getByPlaceholder('Ask a question...').fill('What caused the American Revolution?');
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for the full response to complete (Show Sources appears post-stream)
    await expect(page.getByText(/Show Sources/i)).toBeVisible({ timeout: LLM_TIMEOUT });

    // KG Expansion section should show concept chips
    const kgSection = page.locator('.bg-blue-50.border.border-blue-200');
    await expect(kgSection).toBeVisible({ timeout: 10_000 });

    // Should have at least one concept chip
    const conceptChips = page.locator('.bg-blue-100.text-blue-800');
    const chipCount = await conceptChips.count();
    expect(chipCount).toBeGreaterThan(0);
  });

  test('should handle clicking an example question', async ({ page }) => {
    const ollama = await isOllamaAvailable();
    test.skip(!ollama, 'Ollama is not available — skipping LLM test');
    test.setTimeout(LLM_TIMEOUT);

    await page.goto('/chat');

    // Click the first example question button
    const exampleBtn = page.locator('button', {
      hasText: 'What caused the American Revolution?',
    });
    await exampleBtn.click();

    // Wait for the full response (Show Sources appears after streaming completes)
    await expect(page.getByText(/Show Sources/i)).toBeVisible({ timeout: LLM_TIMEOUT });

    // An assistant message should be present with substantial content
    const assistantMsg = page.locator('.bg-white.border.border-gray-200.shadow-sm').last();
    const text = await assistantMsg.textContent();
    expect(text!.length).toBeGreaterThan(50);
  });
});
