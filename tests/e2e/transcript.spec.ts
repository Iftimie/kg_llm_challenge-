// Transcript modal specs: chat + transcript lookups are served by fixtures.
import { test, expect } from "@playwright/test";

import { loginAs } from "./auth";
import { CHAT_FIXTURE, TRANSCRIPT_FIXTURE } from "./fixtures";

async function openWithFixture(page: import("@playwright/test").Page) {
  await page.route("**/api/chat", (route) =>
    route.fulfill({ json: CHAT_FIXTURE })
  );
  await page.route("**/api/transcripts/T007", (route) =>
    route.fulfill({ json: TRANSCRIPT_FIXTURE })
  );
  await page.goto("/");
  await page.getByTestId("chat-input").fill("fixture question");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("evidence-headline")).toBeVisible();
}

async function openModal(page: import("@playwright/test").Page) {
  await page.locator('.ev-preview[data-transcript-id="T007"]').click();
  await expect(page.getByTestId("transcript-modal")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await loginAs(page, "transcript-spec@example.com", "password123");
});

test("preview opens the modal with the transcript contents", async ({ page }) => {
  await openWithFixture(page);
  await openModal(page);

  await expect(page.locator("#transcript-modal-title")).toHaveText(
    "Transcript T007"
  );
  await expect(page.locator("#transcript-modal-meta")).toContainText("D007");
  await expect(page.locator("#transcript-modal-body")).toContainText(
    "governance resolved"
  );
});

test("Close button hides the modal", async ({ page }) => {
  await openWithFixture(page);
  await openModal(page);

  await page.locator("#transcript-modal-close").click();
  await expect(page.getByTestId("transcript-modal")).toBeHidden();
});

test("Escape hides the modal", async ({ page }) => {
  await openWithFixture(page);
  await openModal(page);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("transcript-modal")).toBeHidden();
});
