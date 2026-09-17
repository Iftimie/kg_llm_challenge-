// Shared Playwright login helper for the browser e2e specs.
//
// Register (ignoring the 409 for an existing account) then log in through the
// real UI form on "/" so the auth token lands in localStorage, exactly as a
// user would. Subsequent navigations in the same context keep the token.
import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

export async function loginAs(page: Page, email: string, password: string) {
  try {
    await page.request.post("/api/auth/register", {
      data: { email, password },
    });
  } catch {
    // 409 (already registered) is fine; ignore any failure.
  }
  await page.goto("/");
  await page.getByTestId("login-email").fill(email);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-form")).toBeHidden({ timeout: 15000 });
}

export async function loginAsAdmin(page: Page) {
  await loginAs(page, "admin@example.com", "password123");
}
