import { test, expect, tutorAnswer, tutorStream } from './fixtures';
import type { Page } from '@playwright/test';

const answerText = tutorAnswer.tokens.join('').trim();

const questionInput = (page: Page) => page.getByRole('textbox', { name: 'Your question' });
const kgToggle = (page: Page) => page.getByRole('checkbox', { name: 'KG Expansion' });

test.describe('Chat Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
  });

  test('shows the chat interface', async ({ page }) => {
    await expect(page).toHaveTitle('AI Tutor | Adaptive Knowledge Graph');
    await expect(page.getByRole('heading', { name: 'AI Tutor Chat' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Welcome to the AI Tutor!' })).toBeVisible();
    await expect(questionInput(page)).toHaveAttribute('placeholder', 'Ask a question...');
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
    await expect(page.getByRole('log', { name: 'Conversation' })).toHaveAttribute(
      'aria-live',
      'polite'
    );
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
    await expect(page.getByRole('log')).toHaveAttribute('aria-busy', 'false');

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
    await expect(page.getByRole('log')).toHaveAttribute('aria-busy', 'true');

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
    await expect(kgToggle(page)).toBeChecked();
    // The label (with its text) wraps the visually hidden checkbox
    await page.getByText('KG Expansion', { exact: true }).click();
    await expect(kgToggle(page)).not.toBeChecked();

    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText(answerText)).toBeVisible();
    expect(api.calls('POST /ask/stream')[0].postDataJSON().use_kg_expansion).toBe(false);

    await page.getByText('KG Expansion', { exact: true }).click();
    await expect(kgToggle(page)).toBeChecked();
  });

  test('shows the error of an unavailable tutor and retries', async ({ page, api }) => {
    api.on('POST /ask/stream', {
      status: 503,
      json: { detail: 'LLM service temporarily unavailable' },
    });

    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.getByRole('main').getByRole('alert')).toContainText(
      'Sorry, I encountered an error: LLM service temporarily unavailable.'
    );

    api.on('POST /ask/stream', () => ({ body: tutorStream(), contentType: 'text/event-stream' }));
    await page.getByRole('button', { name: 'Retry' }).click();

    await expect(page.getByText(answerText)).toBeVisible();
    await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
    expect(api.calls('POST /ask/stream')).toHaveLength(2);
  });

  test('shows an error reported while streaming', async ({ page, api }) => {
    const body = [
      `data: ${JSON.stringify({ type: 'metadata', sources: [], expanded_concepts: null })}\n\n`,
      `data: ${JSON.stringify({ type: 'error', content: 'The model returned an empty answer' })}\n\n`,
      'data: [DONE]\n\n',
    ].join('');
    api.on('POST /ask/stream', { body, contentType: 'text/event-stream' });

    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.getByRole('main').getByRole('alert')).toContainText(
      'Sorry, I encountered an error: The model returned an empty answer.'
    );
  });

  test('highlights the expanded concepts on the graph', async ({ page }) => {
    await questionInput(page).fill('What caused the American Revolution?');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText(answerText)).toBeVisible();

    await page.getByRole('button', { name: 'View on Graph' }).click();

    await expect(page).toHaveURL('/graph');
    await expect(page.getByText(/Highlighting 2 concepts/)).toBeVisible();
  });
});

test.describe('Chat Page with a question in the URL', () => {
  test('asks the question on load', async ({ page, api }) => {
    await page.goto('/chat?question=Explain%20the%20Constitution');

    await expect(page.getByText('Explain the Constitution', { exact: true })).toBeVisible();
    await expect(page.getByText(answerText)).toBeVisible();
    expect(api.calls('POST /ask/stream')).toHaveLength(1);
    expect(api.calls('POST /ask/stream')[0].postDataJSON().question).toBe(
      'Explain the Constitution'
    );
  });
});
