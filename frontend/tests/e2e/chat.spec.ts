import { test, expect } from '@playwright/test';

test.describe('Chat Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
  });

  test('should display chat interface', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /AI Tutor Chat/i })).toBeVisible();
    await expect(page.getByPlaceholder(/Ask a question about Biology/i)).toBeVisible();
  });

  test('should show KG expansion toggle', async ({ page }) => {
    const toggle = page.locator('input[type="checkbox"]').first();
    await expect(toggle).toBeVisible();
    await expect(toggle).toBeChecked(); // Should be ON by default
  });

  test('should display example questions', async ({ page }) => {
    await expect(page.getByText('What is photosynthesis?')).toBeVisible();
    await expect(page.getByText('Explain cellular respiration')).toBeVisible();
  });

  test('should allow asking a question via input', async ({ page }) => {
    const input = page.getByPlaceholder(/Ask a question about Biology/i);
    const sendButton = page.getByRole('button', { name: /Send/i });

    await input.fill('What is DNA?');
    await sendButton.click();

    // Should show user message
    await expect(page.getByText('What is DNA?')).toBeVisible();

    // Should show loading state
    await expect(page.getByText(/Thinking/i)).toBeVisible();
  });

  test('should allow asking via example questions', async ({ page }) => {
    await page.getByText('What is photosynthesis?').first().click();

    // Should show the question as user message
    await expect(page.getByText('What is photosynthesis?')).toBeVisible();
  });

  test('should toggle KG expansion', async ({ page }) => {
    const toggle = page.locator('input[type="checkbox"]').first();

    // Initially checked
    await expect(toggle).toBeChecked();

    // Toggle off
    await toggle.click();
    await expect(toggle).not.toBeChecked();

    // Toggle on
    await toggle.click();
    await expect(toggle).toBeChecked();
  });

  test('should navigate back to home', async ({ page }) => {
    await page.getByLabel('Back to home').click();
    await expect(page).toHaveURL('/');
  });
});
