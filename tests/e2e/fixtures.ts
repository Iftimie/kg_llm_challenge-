// Shared Playwright fixtures for the M0e browser specs.
//
// CHAT_FIXTURE is served for POST /api/chat via page.route() so evidence/modal
// specs are deterministic and offline. TRANSCRIPT_FIXTURE is served for
// GET /api/transcripts/T007. VISUAL_LINK_RE is the href shape every GraphDB
// visual link must follow: <host>:7200/graphs-visualizations?uri=<encoded>&role=subject.

export const CHAT_FIXTURE = {
  answer:
    "Fixture answer: Deal_D007 is on track. " +
    "See [the deal record](https://example.org/sales-kg/resource/Deal_D007) for details.",
  sources: [
    {
      name: "sales-kg_query_kg",
      input: { sparql: "SELECT * WHERE { ?s ?p ?o } LIMIT 5" },
      hits: [
        {
          s: {
            type: "uri",
            value: "https://example.org/sales-kg/resource/Deal_D007",
          },
        },
      ],
      total: 1,
    },
    {
      name: "sales-kg_semantic_search",
      input: { query: "sso", top_k: 3 },
      hits: [{ id: "T007", distance: 0.12, snippet: "governance resolved" }],
      total: 1,
    },
  ],
  meta: {
    engine: "fixture",
    model: "fixture",
    steps: 2,
    graphdb_url: "http://graphdb:7200",
    graphdb_repo: "sales-kg",
    iris: ["https://example.org/sales-kg/resource/Deal_D007"],
  },
};

export const TRANSCRIPT_FIXTURE = {
  transcript_id: "T007",
  deal_id: "D007",
  account_id: "A007",
  activity_date: "2026-01-01",
  channel: "Sales Call",
  transcript: "governance resolved body",
};

// Regex source string for the GraphDB visual-link href shape. Host-agnostic:
// the UI derives the host from window.location, so links work locally and on
// the deployed host (localhost vs 127.0.0.1 vs the EC2 public IP).
export const VISUAL_LINK_RE =
  ":7200/graphs-visualizations\\?uri=[^&\\s]+&role=subject$";
