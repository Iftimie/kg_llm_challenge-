// Clear-chat specs: the header "Clear chat" button empties the pane and deletes
// the persisted history so a refresh does not restore the conversation.
import { test, expect } from "@playwright/test";
import { loginAs } from "./auth";

test("clear chat empties the pane and persists across refresh", async ({
  page,
}) => {
  await loginAs(page, "clear-spec@example.com", "password123");
  await page.goto("/");

  const marker = "clear-marker-" + Date.now();
  await page.getByTestId("chat-input").fill(marker);
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("assistant-answer")).toContainText(
    "stub answer to:",
    { timeout: 15000 }
  );
  await expect(page.locator("#chat .row")).not.toHaveCount(0);

  await page.locator("#clear-chat").click();

  // Pane is empty immediately.
  await expect(page.locator("#chat .row")).toHaveCount(0);

  // And stays empty after a reload (persisted history was deleted server-side).
  await page.reload();
  await expect(page.getByTestId("chat-history")).toBeVisible();
  await expect(page.locator("#chat .row")).toHaveCount(0);
});
