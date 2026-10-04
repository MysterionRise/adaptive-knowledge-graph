import { defineConfig, devices } from '@playwright/test';

// Port of the Next.js server under test (override with E2E_PORT if 3000 is taken).
const port = Number(process.env.E2E_PORT ?? 3000);
const baseURL = `http://localhost:${port}`;

export default defineConfig({
  // Only does work for the `integration` project (it checks the live backend); `npm run test:e2e`
  // selects the hermetic chromium project, whose API calls are stubbed in tests/e2e/fixtures.ts.
  globalSetup: './tests/integration/global-setup.ts',
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'integration',
      testDir: './tests/integration',
      use: {
        ...devices['Desktop Chrome'],
        video: 'retain-on-failure',
      },
      timeout: 60_000,
    },
  ],

  webServer: {
    // A production build serves pre-compiled pages, so first visits are not slowed down by
    // on-demand dev compilation. Locally, a server already listening on the port is reused.
    command: `npm run build && npm run start -- --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
