import { test, expect, quiz } from './fixtures';

test.describe('Assessment Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/assessment');
  });

  test('shows the assessment form for the default subject', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Adaptive Assessment Engine' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Start Assessment' })).toBeVisible();
    await expect(page.getByRole('combobox')).toHaveValue('The American Revolution');
    await expect(page.getByRole('button', { name: 'Start Adaptive Assessment' })).toBeEnabled();
  });

  test('runs an adaptive quiz and shows the results', async ({ page, api }) => {
    const [question] = quiz.questions;

    await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();

    await expect(page.getByRole('heading', { name: question.text })).toBeVisible();
    await expect(page.getByText('Question 1 of 1')).toBeVisible();
    const generate = new URL(api.calls('POST /quiz/generate-adaptive')[0].url());
    expect(generate.searchParams.get('topic')).toBe('The American Revolution');
    expect(generate.searchParams.get('subject')).toBe('us_history');

    await page.getByRole('button', { name: 'The Stamp Act' }).click();
    await page.getByRole('button', { name: 'Submit Answer' }).click();

    await expect(page.getByRole('heading', { name: 'Correct!' })).toBeVisible();
    await expect(page.getByText(question.explanation)).toBeVisible();
    await expect.poll(() => api.calls('POST /student/mastery').length).toBe(1);
    expect(api.calls('POST /student/mastery')[0].postDataJSON()).toEqual({
      concept: 'The American Revolution',
      correct: true,
    });

    await page.getByRole('button', { name: 'Finish Quiz' }).click();

    await expect(page.getByRole('heading', { name: 'Great Job!' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Learning Path' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Colonial America' })).toBeVisible();
    await expect.poll(() => api.calls('POST /quiz/recommendations').length).toBe(1);

    await page.getByRole('button', { name: 'Close results' }).click();
    await expect(page.getByRole('heading', { name: 'Start Assessment' })).toBeVisible();
  });

  test('shows an error when the quiz cannot be generated', async ({ page, api }) => {
    api.on('POST /quiz/generate-adaptive', { status: 503, json: { detail: 'LLM unavailable' } });

    await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();

    await expect(
      page.getByText('Failed to generate quiz. Please ensure the backend is running.')
    ).toBeVisible();
  });
});
