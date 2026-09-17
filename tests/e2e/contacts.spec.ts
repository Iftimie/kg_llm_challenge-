// Contacts meta specs: chat + transcript lookups are served by fixtures so the
// modal's Contacts item (data-testid="contact-ids") is deterministic. T001's
// contact_ids arrive as an array and render joined as "C001, C002".
import { test, expect } from "@playwright/test";

import { loginAs } from "./auth";

const CHAT_FIXTURE = {
  answer:
    "Fixture answer: Deal_D001 is on track. " +
    "See [the deal record](https://example.org/sales-kg/resource/Deal_D001) for details.",
  sources: [
    {
      name: "sales-kg_semantic_search",
      input: { query: "deal d001", top_k: 3 },
      hits: [
        { id: "T001", distance: 0.1, snippet: "pricing across three factories" },
      ],
      total: 1,
    },
  ],
  meta: {
    engine: "fixture",
    model: "fixture",
    steps: 1,
    graphdb_url: "http://graphdb:7200",
    graphdb_repo: "sales-kg",
    iris: ["https://example.org/sales-kg/resource/Deal_D001"],
  },
};

const TRANSCRIPT_FIXTURE = {
  transcript_id: "T001",
  deal_id: "D001",
  account_id: "A001",
  contact_ids: ["C001", "C002"],
  activity_date: "2026-09-10",
  channel: "Sales Call",
  transcript: "pricing across three factories",
};

async function openWithFixture(page: import("@playwright/test").Page) {
  await page.route("**/api/chat", (route) =>
    route.fulfill({ json: CHAT_FIXTURE })
  );
  await page.route("**/api/transcripts/T001", (route) =>
    route.fulfill({ json: TRANSCRIPT_FIXTURE })
  );
  await page.goto("/");
  await page.getByTestId("chat-input").fill("fixture question");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("evidence-headline")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await loginAs(page, "contacts-spec@example.com", "password123");
});

test("transcript modal shows Contacts joined from contact_ids", async ({
  page,
}) => {
  await openWithFixture(page);

  await page.locator('.ev-preview[data-transcript-id="T001"]').click();
  await expect(page.getByTestId("transcript-modal")).toBeVisible();

  const contacts = page.getByTestId("contact-ids");
  await expect(contacts).toBeVisible();
  await expect(contacts).toHaveText("C001, C002");
});
