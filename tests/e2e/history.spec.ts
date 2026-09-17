// Chat history persistence (M13 deferred → added with chat-history hook).
// The backend persists every exchange and exposes GET /api/chats; this spec
// verifies the UI restores that conversation after a full page refresh.
//
// Uses a unique marker message so re-runs against the shared sqlite test-e2e.db
// never collide with history left by earlier runs.
import { test, expect } from "@playwright/test";
import { loginAs } from "./auth";

test("chat history is restored after a page refresh", async ({ page }) => {
  await loginAs(page, "history-spec@example.com", "password123");
  await page.goto("/");

  const marker = "history-marker-" + Date.now();
  await page.getByTestId("chat-input").fill(marker);
  await page.getByTestId("send-button").click();

  await expect(page.getByTestId("assistant-answer")).toContainText(
    "stub answer to:",
    { timeout: 15000 }
  );

  // Full reload: the token persists in localStorage, so loadHistory() fetches
  // /api/chats and re-renders the prior turns.
  await page.reload();

  await expect(page.getByTestId("chat-history")).toBeVisible();
  await expect(page.locator("#chat")).toContainText(marker, { timeout: 15000 });
  await expect(page.locator("#chat")).toContainText("stub answer to: " + marker);
});
