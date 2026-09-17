import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Run-unique artifacts so every browser run is deterministic and self-contained:
//  * a fresh sqlite DB (chat-history restore must never see stale rows), and
//  * an isolated DATA_DIR/KG_NT (the ingest specs write A999/T990; pointing them
//    at the tracked mock_crm_dataset/ would collide on the next run and dirty
//    the working tree).
const RUN_DIR = path.join(os.tmpdir(), `sales-e2e-${process.pid}`);
const DB_URL = `sqlite:///./test-e2e-${process.pid}.db`;
const E2E_DATA_DIR = path.join(RUN_DIR, "data");
const E2E_KG_NT = path.join(RUN_DIR, "kg.nt");

const SHARED_ENV = {
  DATABASE_URL: DB_URL,
  DATA_DIR: E2E_DATA_DIR,
  KG_NT: E2E_KG_NT,
  GRAPHDB_AUTO_PROVISION: "0",
  PATH: process.env.PATH,
};

export default defineConfig({
  testDir: "tests/e2e",
  outputDir: "test-results",
  globalSetup: "./tests/e2e/global-setup.ts",
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
  webServer: [
    {
      command:
        ".venv\\Scripts\\python.exe -m uvicorn app.backend.app:app --host 127.0.0.1 --port 8123",
      url: "http://127.0.0.1:8123/health",
      reuseExistingServer: !process.env.CI,
      env: { ...SHARED_ENV, ANSWERER: "stub" },
      timeout: 60_000,
    },
    // Async ingestion (M9) needs the queue worker polling the same SQLite DB so
    // enqueued jobs reach "done". No HTTP endpoint, so no url/reuse check; the
    // worker loops (surviving the pre-schema boot race) until Playwright exits.
    {
      command: ".venv\\Scripts\\python.exe -m app.queue.worker",
      env: SHARED_ENV,
      timeout: 60_000,
    },
  ],
});
