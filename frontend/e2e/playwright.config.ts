import { defineConfig, devices } from "@playwright/test"

// Browser E2E for TEX (R-58). Runs against a live bench with demo data:
//   bench --site <site> execute kamra.tex.devtools.demo_seed.execute --kwargs "{'password': '…'}"
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e
const chromium = process.env.PW_CHROMIUM || (process.env.PLAYWRIGHT_BROWSERS_PATH ? "/opt/pw-browsers/chromium" : undefined)

export default defineConfig({
  testDir: ".",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "../../e2e-report" }]],
  outputDir: "../../e2e-results",
  use: {
    baseURL: process.env.TEX_E2E_BASE || "http://test.localhost:8000",
    // fail a stuck step quickly instead of waiting out the whole test timeout
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: chromium ? { executablePath: chromium } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /(mobile|booking)[^/]*\.spec\.ts$/ },
  ],
})
