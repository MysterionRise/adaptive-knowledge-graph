/*
 * Capture the demo screenshots and the walkthrough recording against a live stack
 * (docs/demo/DEMO_ASSET_CAPTURE.md).
 *
 *   node scripts/capture_demo_assets.cjs <frontend-dir> <base-url> <out-dir> [--video]
 *
 * <frontend-dir> provides @playwright/test and its Chromium (npx playwright install chromium).
 * Screenshots are 1440x900 at 2x; with --video the same walkthrough is recorded at 1x with
 * pauses to talk over, as WebM in <out-dir>/video.
 */
const path = require('path');
const fs = require('fs');

const [frontendDir, base, outDir, flag] = process.argv.slice(2);
if (!frontendDir || !base || !outDir) {
  console.error('usage: node scripts/capture_demo_assets.cjs <frontend-dir> <base-url> <out-dir> [--video]');
  process.exit(2);
}
const { chromium } = require(path.resolve(frontendDir, 'node_modules/@playwright/test'));
const video = flag === '--video';
const QUESTION = 'What was the Stamp Act and how did it lead to colonial resistance?';
const LLM_TIMEOUT = 180_000;

// Pauses only in the recording, long enough to talk over
const pause = (page, ms) => (video ? page.waitForTimeout(ms * 2) : Promise.resolve());

async function shot(page, name, locator) {
  if (video) return;
  const file = path.join(outDir, name);
  await page.mouse.move(0, 0); // no hover highlight in the shot
  await page.waitForTimeout(600); // let CSS transitions finish
  if (locator) await locator.screenshot({ path: file });
  else await page.screenshot({ path: file });
  console.log('wrote', file);
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: video ? 1 : 2,
    ...(video ? { recordVideo: { dir: path.join(outDir, 'video'), size: { width: 1440, height: 900 } } } : {}),
  });
  const page = await context.newPage();

  // 1. Home
  await page.goto(`${base}/`);
  await page.getByRole('heading', { level: 1, name: 'Adaptive Knowledge Graph' }).waitFor();
  await page.waitForLoadState('networkidle');
  await pause(page, 4000);
  await shot(page, '01-home.png');

  // 2. Demo status, and its evaluation card on its own
  await page.goto(`${base}/demo-status`);
  await page.getByRole('heading', { name: 'Script Readiness' }).waitFor();
  await page.waitForLoadState('networkidle');
  await pause(page, 6000);
  await shot(page, '02-demo-status.png');
  const evalCard = page.locator('div.rounded-lg', { has: page.getByRole('heading', { name: 'Latest Evaluation' }) }).last();
  await shot(page, '06-eval-report.png', evalCard);
  if (video) {
    await evalCard.scrollIntoViewIfNeeded();
    await pause(page, 7000);
  }

  // 3. Chat with citations; taller for the screenshot so the question, answer and sources fit
  if (!video) await page.setViewportSize({ width: 1440, height: 1120 });
  await page.goto(`${base}/chat`);
  const input = page.getByLabel('Your question');
  await input.waitFor();
  await input.fill(QUESTION);
  await pause(page, 1500);
  await input.press('Enter');
  await page.getByRole('log').and(page.locator('[aria-busy="false"]')).getByText(/^Model: /).waitFor({ timeout: LLM_TIMEOUT });
  await pause(page, 4000);
  await page.getByRole('button', { name: /^Source 1/ }).click();
  await pause(page, 4000);
  await shot(page, '03-chat-citations.png');
  if (!video) await page.setViewportSize({ width: 1440, height: 900 });

  // 4. Graph with a selected concept
  await page.goto(`${base}/graph`);
  const search = page.getByRole('combobox', { name: 'Find a concept' });
  await search.waitFor();
  await page.waitForTimeout(2500); // layout animation
  await pause(page, 3000);
  await search.fill('Stamp Act');
  await search.press('Enter');
  await page.getByRole('heading', { name: 'Selected Concept' }).waitFor();
  await page.waitForTimeout(800);
  await pause(page, 5000);
  await shot(page, '04-graph-us-history.png');

  // 5. Adaptive assessment: the feedback on the first answer, then the results dialog.
  // The recording answers questions 1 and 3 correctly and 2 wrongly, from the quiz the page received.
  let quiz = null;
  page.on('response', async (response) => {
    if (response.url().includes('/quiz/generate-adaptive') && response.ok()) {
      quiz = await response.json().catch(() => null);
    }
  });
  await page.goto(`${base}/assessment`);
  await page.getByRole('button', { name: 'Start Adaptive Assessment' }).click();
  await page.getByText(/^Question 1 of \d+$/).waitFor({ timeout: LLM_TIMEOUT });
  for (let i = 0; i < 10; i += 1) {
    await pause(page, 2500);
    const q = quiz?.questions?.[i];
    const pick = video && q ? q.options.find((o) => (i === 1) !== (o.id === q.correct_option_id)) : null;
    const option = pick
      ? page.locator('button[aria-pressed]', { has: page.getByText(pick.text, { exact: true }) })
      : page.locator('button[aria-pressed]');
    await option.first().click();
    await page.getByRole('button', { name: 'Submit Answer' }).click();
    await page.getByRole('heading', { name: /^(Correct|Concept Gap)/ }).waitFor();
    await pause(page, 3000);
    if (i === 0) await shot(page, '05-assessment-mastery.png');
    const finish = page.getByRole('button', { name: 'Finish Quiz' });
    if (await finish.isVisible()) {
      await finish.click();
      break;
    }
    await page.getByRole('button', { name: /^Next/ }).click();
  }
  await page.getByRole('dialog').waitFor();
  await page.waitForTimeout(1500);
  await pause(page, 6000);
  await shot(page, '05b-assessment-results.png');

  await context.close();
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
