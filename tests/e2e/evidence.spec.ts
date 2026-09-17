// Deterministic evidence-pane specs: POST /api/chat is served by CHAT_FIXTURE.
import { test, expect } from "@playwright/test";

import { loginAs } from "./auth";
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

test.beforeEach(async ({ page }) => {
  await loginAs(page, "evidence-spec@example.com", "password123");
});

test("headline reports the fixture engine and step count", async ({ page }) => {
  await openWithFixture(page);

  const headline = page.getByTestId("evidence-headline");
  await expect(headline).toContainText("fixture");
  await expect(headline).toContainText("2 steps");
});

test("checked line summarizes the KG query", async ({ page }) => {
  await openWithFixture(page);

  const checked = page.getByTestId("evidence-checked");
  await expect(checked).toContainText("How I checked:");
  await expect(checked).toContainText("KG query");
});

test("KG section summary reports one row", async ({ page }) => {
  await openWithFixture(page);

  const kgSection = page
    .getByTestId("evidence-section")
    .filter({ hasText: "KG query" });
  await expect(kgSection.locator("summary")).toContainText("KG query");
  await expect(kgSection.locator("summary")).toContainText("1 row");
});

test("entity visual link matches the GraphDB href shape", async ({ page }) => {
  await openWithFixture(page);

  const entityLink = page
    .locator("#evidence .ev-entities [data-testid='visual-link']")
    .first();
  await expect(entityLink).toBeVisible();

  const href = await entityLink.getAttribute("href");
  expect(href).toMatch(new RegExp(VISUAL_LINK_RE));
  await expect(entityLink).toHaveAttribute("target", "_blank");
});
