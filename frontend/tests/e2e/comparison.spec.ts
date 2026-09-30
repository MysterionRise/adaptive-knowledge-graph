import { test, expect, plainRagAnswer, tutorAnswer } from './fixtures';
import type { Page } from '@playwright/test';

const questionInput = (page: Page) =>
  page.getByLabel('Ask a question to compare both approaches:');
const compareButton = (page: Page) => page.getByRole('button', { name: 'Compare Approaches' });
const kgPanel = (page: Page) => page.getByRole('region', { name: 'With KG Expansion' });
const plainPanel = (page: Page) => page.getByRole('region', { name: 'Regular RAG' });

test.describe('Comparison Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/comparison');
  });

  test('shows the comparison form', async ({ page }) => {
    await expect(page).toHaveTitle('KG-RAG vs Regular RAG | Adaptive Knowledge Graph');
    await expect(
      page.getByRole('heading', { name: 'KG-RAG vs Regular RAG Comparison' })
    ).toBeVisible();
    await expect(questionInput(page)).toHaveAttribute(
      'placeholder',
      'e.g., What caused the American Revolution?'
    );
    // Compare is disabled until a question is entered
    await expect(compareButton(page)).toBeDisabled();
  });

  test('offers US History example questions', async ({ page }) => {
    for (const question of [
      'What caused the American Revolution?',
      'Explain the significance of the Constitution',
      'How did the Civil War affect society?',
    ]) {
      await expect(page.getByRole('button', { name: question })).toBeVisible();
    }
  });

  test('fills the question from an example', async ({ page }) => {
    await page.getByRole('button', { name: 'What caused the American Revolution?' }).click();

    await expect(questionInput(page)).toHaveValue('What caused the American Revolution?');
    await expect(compareButton(page)).toBeEnabled();
  });

  test('enables the compare button when a question is typed', async ({ page }) => {
    await questionInput(page).fill('Why did the colonists boycott British goods?');

    await expect(compareButton(page)).toBeEnabled();
  });

  test('compares answers with and without KG expansion', async ({ page, api }) => {
    await questionInput(page).fill('What caused the American Revolution?');
    await compareButton(page).click();

    await expect(page.getByRole('heading', { name: 'With KG Expansion', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Regular RAG', exact: true })).toBeVisible();
    // Answers are rendered as Markdown
    await expect(kgPanel(page).locator('strong')).toHaveText('With prerequisite context:');
    await expect(kgPanel(page).getByRole('listitem')).toHaveText(tutorAnswer.expanded_concepts);
    await expect(plainPanel(page).getByText(plainRagAnswer)).toBeVisible();
    await expect(kgPanel(page).getByText('Expanded Concepts (2):')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Why KG Expansion Matters' })).toBeVisible();

    const payloads = api.calls('POST /ask').map((request) => request.postDataJSON());
    expect(payloads).toHaveLength(2);
    expect(payloads).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ use_kg_expansion: true, subject: 'us_history' }),
        expect.objectContaining({ use_kg_expansion: false, subject: 'us_history' }),
      ])
    );
  });

  test('shows the backend error in both columns when the comparison fails', async ({
    page,
    api,
  }) => {
    api.on('POST /ask', { status: 500, json: { detail: 'An internal error occurred' } });

    await questionInput(page).fill('What caused the American Revolution?');
    await compareButton(page).click();

    for (const panel of [kgPanel(page), plainPanel(page)]) {
      await expect(panel.getByRole('alert')).toContainText('Unable to get this answer.');
      await expect(panel.getByRole('alert')).toContainText('An internal error occurred');
    }
    await expect(page.getByRole('heading', { name: 'Why KG Expansion Matters' })).toBeHidden();
  });

  test('keeps one answer when the other fails and retries the failed one', async ({ page, api }) => {
    let plainAttempts = 0;
    api.on('POST /ask', (request) => {
      const { question, use_kg_expansion: useKg } = request.postDataJSON();
      if (!useKg && ++plainAttempts === 1) {
        return { status: 503, json: { detail: 'LLM service temporarily unavailable' } };
      }
      return {
        json: {
          question,
          answer: useKg ? 'Answer with KG expansion.' : plainRagAnswer,
          sources: [],
          expanded_concepts: useKg ? tutorAnswer.expanded_concepts : null,
          retrieved_count: 5,
          model: tutorAnswer.model,
          attribution: tutorAnswer.attribution,
        },
      };
    });

    await questionInput(page).fill('What caused the American Revolution?');
    await compareButton(page).click();

    await expect(kgPanel(page).getByText('Answer with KG expansion.')).toBeVisible();
    await expect(plainPanel(page).getByRole('alert')).toContainText(
      'LLM service temporarily unavailable'
    );

    await plainPanel(page).getByRole('button', { name: 'Retry' }).click();

    await expect(plainPanel(page).getByText(plainRagAnswer)).toBeVisible();
    expect(api.calls('POST /ask')).toHaveLength(3);
  });
});
