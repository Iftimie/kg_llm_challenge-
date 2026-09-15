# PLAN

## Goal
Evolve the working experiment scripts into a tidy prototype:
UI -> backend -> agent (OpenCode) -> MCP -> GraphDB / ChromaDB / BM25.
Reuse existing code and preserve behavior at every step.

## Decisions locked
- Ontology: `sales_kg_ontology_v1_llm_friendly.ttl` is canonical (`BASE_ONTOLOGY_PATH` kept for reference).
- Models are selectable via env: `OPENROUTER_MODEL`, `DEEPSEEK_MODEL`, `ANSWERER`, `EMBEDDING_MODEL`.
- Ship pre-extracted TTLs in the repo; no re-extraction needed to run the app.
- Extraction baseline stays the existing `extract.py` functions (local Ollama).
- Backend responses are non-streaming (single JSON response).
- FastAPI serves the static UI from `ui/`.

## Milestones
Order: M1, M5, M6, M2, M3, M4, M7, M8. One bounded change + review per milestone.

- M1 Package skeleton + centralized config + transport schemas.
  Verify: `python -c "import app.config; import app.backend.schemas"`.
- M5 Backend: minimal `POST /api/chat` wrapping the agent.
  Verify: one end-to-end API call returns a JSON answer.
- M6 UI: minimal chat page served by the backend.
  Verify: send a question in the browser and see the answer.
- M2 Retrieval services: thin interfaces over GraphDB / Chroma / BM25 / transcripts.
  Verify: each service returns known expected results independently.
- M3 MCP server exposing `query_kg`, `semantic_search`, `keyword_search`, `get_transcript`, `describe_kg_schema`.
  Verify: call each tool once; destructive SPARQL is rejected.
- M4 Agent integration: OpenCode uses the MCP tools.
  Verify: several questions trigger different retrieval-strategy choices.
- M7 Ingestion cleanup: single `python -m app.ingestion` orchestrating existing scripts.
  Verify: full rebuild from CSVs/transcripts succeeds.
- M8 End-to-end cleanup: remove obsolete scripts, update README, add high-value smoke tests.
  Verify: clean-clone runbook succeeds.

## Rules
- Small, reviewable diffs; do not refactor unrelated code.
- Reuse existing scripts; do not rewrite working logic.
- Stop and request review after each milestone.
