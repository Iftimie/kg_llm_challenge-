---
description: "Restricted sales QA runtime: MCP retrieval tools only."
mode: primary
model: openrouter/meta/muse-spark-1.3-contributor
temperature: 0
permission:
  bash: deny
  edit: deny
  write: deny
  glob: deny
  grep: deny
  read: deny
  task: deny
  skill: deny
  webfetch: deny
  websearch: deny
  lsp: deny
  "sales-kg*": allow
  "sales-kg_*": allow
  query_kg: allow
  semantic_search: allow
  keyword_search: allow
  get_transcript: allow
  describe_kg_schema: allow
---

Follow the runtime instructions in `app/agent/system.md`.
