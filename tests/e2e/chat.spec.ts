// Real stub answerer (ANSWERER=stub, no route interception).
// Cold-start first requests can be slow, so answer-dependent assertions use a
// 15s expectation timeout instead of Playwright's 5s default. The transient
// "Thinking…" placeholder no longer matches data-testid="assistant-answer"
// (it is "assistant-pending"), so these expectations wait for the real answer.
import { test, expect } from "@playwright/test";
import { loginAs } from "./auth";

async function ask(page: import("@playwright/test").Page, message: string) {
  await page.getByTestId("chat-input").fill(message);
  await page.getByTestId("send-button").click();
}

test.beforeEach(async ({ page }) => {
  await loginAs(page, "chat-spec@example.com", "password123");
});

test("renders user and assistant rows", async ({ page }) => {
  await page.goto("/");
  await ask(page, "ping");

  await expect(page.getByTestId("message-row")).toContainText("ping");
  await expect(page.getByTestId("assistant-answer")).toContainText(
    "stub answer to: ping",
    { timeout: 15000 }
  );
});

test("shows the stub engine label", async ({ page }) => {
  await page.goto("/");
  await ask(page, "ping");

  await expect(page.locator("#engine")).toContainText("stub", {
    timeout: 15000,
  });
});

test("linkifies Deal_D007 to a GraphDB visual link", async ({ page }) => {
  await page.goto("/");
  await ask(page, "about Deal_D007");

  const link = page
    .locator('[data-testid="assistant-answer"] [data-testid="visual-link"]')
    .first();
  await expect(link).toBeVisible({ timeout: 15000 });

  const expected =
    "/graphs-visualizations?uri=" +
    encodeURIComponent(
      "https://example.org/sales-kg/resource/Deal_D007"
    );
  expect(await link.getAttribute("href")).toContain(expected);
  await expect(link).toHaveAttribute("target", "_blank");
});

test("shows the selected-answer evidence hint", async ({ page }) => {
  await page.goto("/");
  await ask(page, "ping");

  await expect(page.locator("#evidence-hint")).toContainText(
    "Selected answer 1 of 1",
    { timeout: 15000 }
  );
});
