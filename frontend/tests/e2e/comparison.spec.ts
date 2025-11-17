import { test, expect } from '@playwright/test';

test.describe('Comparison Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/comparison');
  });

  test('should display comparison page heading', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: /KG-RAG vs Regular RAG Comparison/i })
    ).toBeVisible();
  });

  test('should show question input', async ({ page }) => {
    const input = page.getByPlaceholder(/e.g., What is photosynthesis?/i);
    await expect(input).toBeVisible();
  });

  test('should display example questions', async ({ page }) => {
    await expect(page.getByText('What is photosynthesis?')).toBeVisible();
    await expect(page.getByText('Explain cellular respiration')).toBeVisible();
  });

  test('should allow selecting example question', async ({ page }) => {
    const exampleQuestion = page.getByRole('button', { name: 'What is photosynthesis?' }).first();
    await exampleQuestion.click();

    const input = page.getByPlaceholder(/e.g., What is photosynthesis?/i);
    await expect(input).toHaveValue('What is photosynthesis?');
  });

  test('should show compare button', async ({ page }) => {
    const compareButton = page.getByRole('button', { name: /Compare Approaches/i });
    await expect(compareButton).toBeVisible();
    await expect(compareButton).toBeDisabled(); // Should be disabled when empty
  });

  test('should enable compare button when question is entered', async ({ page }) => {
    const input = page.getByPlaceholder(/e.g., What is photosynthesis?/i);
    const compareButton = page.getByRole('button', { name: /Compare Approaches/i });

    await input.fill('What is DNA?');
    await expect(compareButton).toBeEnabled();
  });

  test('should show explanation section', async ({ page }) => {
    await expect(page.getByText(/Why KG Expansion Matters/i)).toBeVisible();
  });

  test('should navigate back to home', async ({ page }) => {
    await page.getByLabel('Back to home').click();
    await expect(page).toHaveURL('/');
  });
});
