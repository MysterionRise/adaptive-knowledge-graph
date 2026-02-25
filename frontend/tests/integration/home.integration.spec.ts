import { test, expect } from '@playwright/test';
import { DATA_TIMEOUT } from './helpers';

test.describe('Home Page — Integration', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should display real stats with values greater than zero', async ({ page }) => {
    // Wait for the API response to arrive
    await page.waitForResponse(
      (res) => res.url().includes('/graph/stats') && res.status() === 200,
      { timeout: DATA_TIMEOUT }
    );

    // Stat cards: "Exam Topics", "Study Modules", "Connections"
    const examTopics = page.locator('text=Exam Topics').locator('..').locator('h4');
    const studyModules = page.locator('text=Study Modules').locator('..').locator('h4');
    const connections = page.locator('text=Connections').locator('..').locator('h4');

    // Each stat value should be a number > 0
    await expect(examTopics).toBeVisible({ timeout: DATA_TIMEOUT });
    const topicsText = await examTopics.textContent();
    expect(Number(topicsText?.replace(/,/g, ''))).toBeGreaterThan(0);

    await expect(studyModules).toBeVisible();
    const modulesText = await studyModules.textContent();
    expect(Number(modulesText?.replace(/,/g, ''))).toBeGreaterThan(0);

    await expect(connections).toBeVisible();
    const connectionsText = await connections.textContent();
    expect(Number(connectionsText?.replace(/,/g, ''))).toBeGreaterThan(0);
  });

  test('should show learning journey CTA after profile reset', async ({ page }) => {
    // After globalSetup resets the profile, there should be no mastery data
    await expect(page.getByText('Start Your Learning Journey')).toBeVisible({
      timeout: DATA_TIMEOUT,
    });
  });

  test('should have correct OpenStax attribution link', async ({ page }) => {
    const openstaxLink = page.getByRole('link', { name: /OpenStax/i });
    await expect(openstaxLink).toBeVisible();
    await expect(openstaxLink).toHaveAttribute('href', 'https://openstax.org/');
  });
});
