// Real-backend ingest specs. These are the one place the browser suite writes
// to the live dev DATA_DIR (mock_crm_dataset/). Ids A999 and T990 are reserved
// for this spec; M9 will move ingestion behind an isolated job/staging dir.
//
// The accounts.csv payload must repeat the existing table header: merge_csv_files
// rejects an upload missing any column already present in the on-disk table.
import { test, expect } from "@playwright/test";
import { loginAs } from "./auth";

test.setTimeout(180_000);

const ACCOUNTS_CSV =
  "account_id,account_name,industry,country,employee_count," +
  "annual_revenue_eur,account_tier,created_at\n" +
  "A999,TestCo,Software,USA,10,1000000,Enterprise,2026-01-01\n";

const TRANSCRIPT_CSV =
  "T990,D007,A007,C007,2026-01-02,Sales Call,hello world test transcript\n";

test.beforeEach(async ({ page }) => {
  await loginAs(page, "ingest-spec@example.com", "password123");
});

test("CRM CSV upload reaches /api/ingest and is staged", async ({ page }) => {
  await page.goto("/ingest.html");

  await page.locator("#files").setInputFiles({
    name: "accounts.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(ACCOUNTS_CSV),
  });
  await page.locator("#submit").click();

  const result = page.getByTestId("result");
  await expect(result).toBeVisible({ timeout: 120_000 });
  await expect(result).toContainText("Status: ok");
  await expect(result).toContainText("accounts.csv");
});

test("transcript CSV upload reaches /api/ingest/transcript", async ({
  page,
}) => {
  await page.goto("/ingest.html");

  await page.locator("#t_file").setInputFiles({
    name: "transcripts.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(TRANSCRIPT_CSV),
  });
  await page.locator("#submit-transcript").click();

  const result = page.getByTestId("result");
  await expect(result).toBeVisible({ timeout: 120_000 });
  await expect(result).toContainText("T990");
});

test("non-CSV upload surfaces the 400 error", async ({ page }) => {
  await page.goto("/ingest.html");

  await page.locator("#files").setInputFiles({
    name: "evil.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("not a csv"),
  });
  await page.locator("#submit").click();

  const result = page.getByTestId("result");
  await expect(result).toBeVisible({ timeout: 120_000 });
  await expect(result).toContainText("Status: 400");
  await expect(page.getByTestId("upload-error")).toBeVisible();
});
