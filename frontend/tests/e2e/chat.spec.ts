import { test, expect, tutorAnswer, tutorStream } from './fixtures';
import type { Page } from '@playwright/test';

const answerText = tutorAnswer.tokens.join('').trim();

const questionInput = (page: Page) => page.getByPlaceholder('Ask a question...');
const kgToggle = (page: Page) => page.getByRole('checkbox');

test.describe('Chat Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
  });

  test('shows the chat interface', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'AI Tutor Chat' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Welcome to the AI Tutor!' })).toBeVisible();
    await expect(questionInput(page)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  test('shows US History example questions', async ({ page }) => {
    for (const question of [
      'What caused the American Revolution?',
      'Explain the significance of the Constitution',
      'How did the Civil War affect American society?',
      'What was the impact of Industrialization?',
    ]) {
      await expect(page.getByRole('button', { name: question })).toBeVisible();
    }
  });

  test('streams an answer with KG expansion details and sources', async ({ page, api }) => {
    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.getByText('What caused the American Revolution?', { exact: true })).toBeVisible();
    await expect(page.getByText(answerText)).toBeVisible();
    await expect(page.getByText('KG Expansion: 2 related concepts')).toBeVisible();
    for (const concept of tutorAnswer.expanded_concepts) {
      await expect(page.getByText(concept, { exact: true })).toBeVisible();
    }
    await expect(page.getByText(tutorAnswer.attribution)).toBeVisible();
    await expect(page.getByText(`Model: ${tutorAnswer.model}`)).toBeVisible();

    await page.getByRole('button', { name: 'Show Sources (2)' }).click();
    await expect(page.getByText(tutorAnswer.sources[0].text)).toBeVisible();

    const [request] = api.calls('POST /ask/stream');
    expect(request.postDataJSON()).toEqual({
      question: 'What caused the American Revolution?',
      use_kg_expansion: true,
      top_k: 5,
      subject: 'us_history',
    });
  });

  test('shows the thinking indicator until the answer starts', async ({ page, api }) => {
    let release!: () => void;
    const answerReady = new Promise<void>((resolve) => {
      release = resolve;
    });
    api.on('POST /ask/stream', async () => {
      await answerReady;
      return { body: tutorStream(), contentType: 'text/event-stream' };
    });

    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.getByText('Thinking...')).toBeVisible();
    await expect(questionInput(page)).toBeDisabled();

    release();

    await expect(page.getByText(answerText)).toBeVisible();
    await expect(page.getByText('Thinking...')).toBeHidden();
    await expect(questionInput(page)).toBeEnabled();
  });

  test('asks an example question', async ({ page, api }) => {
    await page.getByRole('button', { name: 'Explain the significance of the Constitution' }).click();

    await expect(
      page.getByText('Explain the significance of the Constitution', { exact: true })
    ).toBeVisible();
    await expect(page.getByText(answerText)).toBeVisible();
    expect(api.calls('POST /ask/stream')[0].postDataJSON().question).toBe(
      'Explain the significance of the Constitution'
    );
  });

  test('toggles KG expansion and sends the setting with the question', async ({ page, api }) => {
    // The visible switch is the label around a visually hidden checkbox
    const toggleSwitch = page.locator('label').filter({ has: kgToggle(page) });

    await expect(kgToggle(page)).toBeChecked();
    await toggleSwitch.click();
    await expect(kgToggle(page)).not.toBeChecked();

    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText(answerText)).toBeVisible();
    expect(api.calls('POST /ask/stream')[0].postDataJSON().use_kg_expansion).toBe(false);

    await toggleSwitch.click();
    await expect(kgToggle(page)).toBeChecked();
  });

  test('shows an error message when the tutor is unavailable', async ({ page, api }) => {
    api.on('POST /ask/stream', { status: 503, body: 'LLM service temporarily unavailable' });

    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(
      page.getByText(
        'Sorry, I encountered an error: LLM service temporarily unavailable. Please try again.'
      )
    ).toBeVisible();
  });

  test('highlights the expanded concepts on the graph', async ({ page }) => {
    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText(answerText)).toBeVisible();

    await page.getByRole('button', { name: 'View on Graph' }).click();

    await expect(page).toHaveURL('/graph');
    await expect(page.getByText(/Highlighting 2 concepts/)).toBeVisible();
  });

  test('navigates back to home', async ({ page }) => {
    await page.getByRole('button', { name: 'Back to home' }).click();

    await expect(page).toHaveURL('/');
  });
});

test.describe('Chat Page with a question in the URL', () => {
  test('asks the question on load', async ({ page, api }) => {
    await page.goto('/chat?question=Explain%20the%20Constitution');

    await expect(page.getByText('Explain the Constitution', { exact: true })).toBeVisible();
    await expect(page.getByText(answerText)).toBeVisible();
    expect(api.calls('POST /ask/stream')[0].postDataJSON().question).toBe(
      'Explain the Constitution'
    );
  });
});
