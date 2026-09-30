import { test, expect, quiz } from './fixtures';
import type { Page } from '@playwright/test';

const topicSelect = (page: Page) => page.getByRole('combobox', { name: 'Topic' });

/** Answer the single question correctly and open the results. */
async function completeQuiz(page: Page) {
  await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();
  await page.getByRole('button', { name: /^The Stamp Act/ }).click();
  await page.getByRole('button', { name: 'Submit Answer' }).click();
  await page.getByRole('button', { name: 'Finish Quiz' }).click();
  return page.getByRole('dialog', { name: 'Great Job!' });
}

test.describe('Assessment Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/assessment');
  });

  test('shows the assessment form for the default subject', async ({ page }) => {
    await expect(page).toHaveTitle('Adaptive Assessment | Adaptive Knowledge Graph');
    await expect(page.getByRole('heading', { name: 'Adaptive Assessment Engine' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Start Assessment' })).toBeVisible();
    await expect(topicSelect(page)).toHaveValue('The American Revolution');
    await expect(page.getByRole('switch', { name: 'Adaptive Mode' })).toHaveAttribute(
      'aria-checked',
      'true'
    );
    await expect(page.getByRole('button', { name: 'Start Adaptive Assessment' })).toBeEnabled();
  });

  test('switches off adaptive mode', async ({ page, api }) => {
    await page.getByRole('switch', { name: 'Adaptive Mode' }).click();

    await expect(page.getByRole('switch', { name: 'Adaptive Mode' })).toHaveAttribute(
      'aria-checked',
      'false'
    );
    await page.getByRole('button', { name: 'Generate Assessment' }).click();

    await expect(page.getByRole('heading', { name: quiz.questions[0].text })).toBeVisible();
    expect(api.calls('POST /quiz/generate')).toHaveLength(1);
  });

  test('runs an adaptive quiz and shows the results', async ({ page, api }) => {
    const [question] = quiz.questions;

    await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();

    await expect(page.getByRole('heading', { name: question.text })).toBeVisible();
    await expect(page.getByText('Question 1 of 1')).toBeVisible();
    const generate = new URL(api.calls('POST /quiz/generate-adaptive')[0].url());
    expect(generate.searchParams.get('topic')).toBe('The American Revolution');
    expect(generate.searchParams.get('subject')).toBe('us_history');

    const stampAct = page.getByRole('button', { name: /^The Stamp Act/ });
    await stampAct.click();
    await expect(stampAct).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Submit Answer' }).click();

    await expect(page.getByRole('heading', { name: 'Correct!' })).toBeFocused();
    await expect(page.getByText(question.explanation)).toBeVisible();
    await expect(stampAct).toHaveAccessibleName('The Stamp Act Correct answer');
    await expect.poll(() => api.calls('POST /student/mastery').length).toBe(1);
    expect(api.calls('POST /student/mastery')[0].postDataJSON()).toEqual({
      concept: 'The American Revolution',
      correct: true,
    });

    await page.getByRole('button', { name: 'Finish Quiz' }).click();

    const results = page.getByRole('dialog', { name: 'Great Job!' });
    await expect(results).toBeVisible();
    await expect(results.getByRole('button', { name: 'Close results' })).toBeFocused();
    await expect(results.getByRole('heading', { name: 'Learning Path' })).toBeVisible();
    // Prerequisites first, then the target concept
    await expect(
      results.getByRole('list', { name: 'Learning path to The American Revolution' }).getByRole('heading')
    ).toHaveText(['Colonial America', 'The American Revolution']);
    await expect(results.getByText('Target', { exact: true })).toBeVisible();
    await expect.poll(() => api.calls('POST /quiz/recommendations').length).toBe(1);

    await page.keyboard.press('Escape');
    await expect(results).toBeHidden();
    await expect(page.getByRole('heading', { name: 'Start Assessment' })).toBeFocused();
  });

  test('closes the results with the close button', async ({ page }) => {
    const results = await completeQuiz(page);

    await results.getByRole('button', { name: 'Close results' }).click();

    await expect(page.getByRole('heading', { name: 'Start Assessment' })).toBeVisible();
  });

  test('practises a prerequisite from the learning path', async ({ page }) => {
    const results = await completeQuiz(page);

    await results.getByRole('button', { name: 'Practice Colonial America' }).click();

    await expect(page).toHaveURL('/assessment?topic=Colonial%20America');
    await expect(results).toBeHidden();
    await expect(topicSelect(page)).toHaveValue('Colonial America');
  });

  test('shows the reason when the quiz cannot be generated', async ({ page, api }) => {
    api.on('POST /quiz/generate-adaptive', { status: 503, json: { detail: 'LLM unavailable' } });

    await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();

    await expect(page.getByRole('main').getByRole('alert')).toHaveText('Failed to generate quiz: LLM unavailable.');
  });

  test('reports a failed profile reset', async ({ page, api }) => {
    api.on('POST /student/reset', { status: 500, json: { detail: 'An internal error occurred' } });

    await page.getByRole('button', { name: 'Reset Profile (Demo)' }).click();

    await expect(page.getByRole('main').getByRole('alert')).toHaveText(
      'Could not reset your profile: An internal error occurred'
    );
    await expect(page.getByText('Profile reset to initial state')).toBeHidden();
  });

  test('confirms a profile reset', async ({ page, api }) => {
    await page.getByRole('button', { name: 'Reset Profile (Demo)' }).click();

    await expect(page.getByText('Profile reset to initial state')).toBeVisible();
    expect(api.calls('POST /student/reset')).toHaveLength(1);
  });
});

test.describe('Assessment Page with a topic in the URL', () => {
  test('preselects a listed topic', async ({ page }) => {
    await page.goto('/assessment?topic=The%20Civil%20War');

    await expect(topicSelect(page)).toHaveValue('The Civil War');
  });

  test('uses another topic as a custom topic', async ({ page, api }) => {
    await page.goto('/assessment?topic=Stamp%20Act');

    await expect(topicSelect(page)).toHaveValue('__custom__');
    await expect(page.getByRole('textbox', { name: 'Custom topic' })).toHaveValue('Stamp Act');

    await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();
    await expect(page.getByRole('heading', { name: quiz.questions[0].text })).toBeVisible();
    expect(
      new URL(api.calls('POST /quiz/generate-adaptive')[0].url()).searchParams.get('topic')
    ).toBe('Stamp Act');
  });
});
