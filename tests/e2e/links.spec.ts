// GraphDB visual-link shape specs (chat answer + evidence entities).
import { test, expect } from "@playwright/test";

import { CHAT_FIXTURE, VISUAL_LINK_RE } from "./fixtures";

async function openWithFixture(page: import("@playwright/test").Page) {
  await page.route("**/api/chat", (route) =>
    route.fulfill({ json: CHAT_FIXTURE })
  );
  await page.goto("/");
  await page.getByTestId("chat-input").fill("fixture question");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("evidence-headline")).toBeVisible();
}

test("answer visual link matches the GraphDB href shape", async ({ page }) => {
  await openWithFixture(page);

  const link = page
    .locator('[data-testid="assistant-answer"] [data-testid="visual-link"]')
    .first();
  await expect(link).toBeVisible();

  expect(await link.getAttribute("href")).toMatch(new RegExp(VISUAL_LINK_RE));
  await expect(link).toHaveAttribute("target", "_blank");
});

test("evidence entity visual link matches the GraphDB href shape", async ({
  page,
}) => {
  await openWithFixture(page);

  const link = page
    .locator("#evidence .ev-entities [data-testid='visual-link']")
    .first();
  await expect(link).toBeVisible();

  expect(await link.getAttribute("href")).toMatch(new RegExp(VISUAL_LINK_RE));
  await expect(link).toHaveAttribute("target", "_blank");
});
