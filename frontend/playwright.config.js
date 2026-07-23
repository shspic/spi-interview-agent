import { defineConfig, devices } from "@playwright/test";

const externalServer = globalThis.process?.env.PLAYWRIGHT_EXTERNAL_SERVER === "1";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: globalThis.process?.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:4180",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: globalThis.process?.env.PLAYWRIGHT_DISABLE_VIDEO ? "off" : "retain-on-failure",
    ...devices["Desktop Chrome"],
    channel: globalThis.process?.env.PLAYWRIGHT_CHANNEL || undefined,
  },
  webServer: externalServer ? undefined : {
    command: "npm run dev -- --host 127.0.0.1 --port 4180",
    url: "http://127.0.0.1:4180",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      VITE_DISABLE_AUTH_VIDEO: "true",
    },
  },
});
