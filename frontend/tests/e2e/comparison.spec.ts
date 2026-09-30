import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

const questionInput = (page: Page) =>
  page.getByLabel('Ask a question to compare both approaches:');
const compareButton = (page: Page) => page.getByRole('button', { name: 'Compare Approaches' });

test.describe('Comparison Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/comparison');
  });

  test('shows the comparison form', async ({ page }) => {
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
    await expect(
      page.getByText('With prerequisite context: colonial taxation disputes escalated into revolution.')
    ).toBeVisible();
    await expect(page.getByText('Colonists opposed British taxes.')).toBeVisible();
    await expect(page.getByText('Expanded Concepts (2):')).toBeVisible();
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

  test('shows an error when the comparison fails', async ({ page, api }) => {
    api.on('POST /ask', { status: 500, json: { detail: 'An internal error occurred' } });

    await questionInput(page).fill('What caused the American Revolution?');
    await compareButton(page).click();

    await expect(
      page.getByText('Failed to get responses. Please ensure the backend is running.')
    ).toBeVisible();
  });

  test('navigates back to home', async ({ page }) => {
    await page.getByRole('button', { name: 'Back to home' }).click();

    await expect(page).toHaveURL('/');
  });
});
