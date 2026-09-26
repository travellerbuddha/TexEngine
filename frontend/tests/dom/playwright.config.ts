import { defineConfig } from "@playwright/test"

// Browser checks of the design-system overlays and grid keys against a harness page served by
// vite (no bench): `npm run test:dom`. Chromium: PW_CHROMIUM, else Playwright's own install.
const port = Number(process.env.TEX_DOM_PORT) || 5391
const chromium = process.env.PW_CHROMIUM || (process.env.PLAYWRIGHT_BROWSERS_PATH ? "/opt/pw-browsers/chromium" : undefined)

export default defineConfig({
  testDir: ".",
  testMatch: /\.spec\.ts$/,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "../../test-results/dom",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // short enough that a tall panel overflows and has to scroll
    viewport: { width: 1000, height: 400 },
    actionTimeout: 5_000,
    trace: "retain-on-failure",
    launchOptions: chromium ? { executablePath: chromium } : {},
  },
  webServer: {
    command: "npx vite --config tests/dom/vite.config.ts",
    cwd: "../..",
    env: { TEX_DOM_PORT: String(port) },
    url: `http://127.0.0.1:${port}/tests/dom/overlays.html`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
