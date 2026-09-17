import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  outputDir: "test-results",
  reporter: [
    ["html", { open: "never" }],
    ["list"],
  ],
  // Retry once locally (transient cold starts) and twice on CI. Traces are
  // captured on the first retry so a flaky failure is replayable step by step
  // via `npm run test:e2e:trace-open` or `npm run test:e2e:report`.
  retries: process.env.CI ? 2 : 1,
  use: {
    baseURL: "http://127.0.0.1:8123",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command:
      ".venv\\Scripts\\python.exe -m uvicorn app.backend.app:app --host 127.0.0.1 --port 8123",
    url: "http://127.0.0.1:8123/health",
    reuseExistingServer: !process.env.CI,
    env: {
      ANSWERER: "stub",
      DATABASE_URL: "sqlite:///./test-e2e.db",
      PATH: process.env.PATH,
    },
    timeout: 60_000,
  },
});
