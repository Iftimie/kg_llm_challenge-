# Sales Intelligence KG

A prototype "sales intelligence assistant" that answers questions about deals,
accounts, contacts and call/email transcripts by grounding an LLM agent in a
small knowledge graph, a vector index and a lexical index.

```
CRM CSVs ──► GraphDB KG ──┐
transcripts ─► Chroma     ├─► MCP tools ─► OpenCode agent ─► FastAPI backend ─► UI
transcripts ─► BM25 ──────┘
```

## Stack

- **Ingestion**: Morph-KGC (CSV → RDF), SHACL validation, LLM transcript
  extraction, load into GraphDB, Chroma + BM25 indexing.
- **Retrieval**: GraphDB SPARQL, Chroma semantic search, BM25 keyword search.
- **Agent**: [OpenCode](https://opencode.ai) harness (`--agent sales`) exposing
  five MCP tools: `query_kg`, `semantic_search`, `keyword_search`,
  `get_transcript`, `describe_kg_schema`.
- **Backend**: FastAPI (`app/backend`), hand-rolled JWT auth (PyJWT + bcrypt),
  Postgres for users/chats/jobs, an async ingestion job queue with a worker.
- **UI**: two static pages (`ui/index.html` chat, `ui/ingest.html` ingestion).

## Quick start (Docker)

```sh
docker compose up --build -d
```

This starts:

| Service   | Port | Notes |
|-----------|------|-------|
| `graphdb` | 7200 | GraphDB Workbench; security ON with demo creds `reader`/`reader` (read-only) and `admin`/`admin` |
| `postgres`| —    | internal only (users/chats/jobs) |
| `app`     | 8000 | FastAPI + static UI |
| `worker`  | —    | processes the ingestion job queue |

Open <http://localhost:8000/index.html> (chat) and
<http://localhost:8000/ingest.html> (ingest). Register/login on either page.

Ingestion is **asynchronous**: `POST /api/ingest*` validates synchronously and
returns `202 {"job_id", ...}`; the `worker` service runs the pipeline and flips
the job to `done`/`failed` (`GET /api/jobs/{id}`).

## Environment variables

See `app/config.py` for the full list and defaults. The ones you are most likely
to set:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEPSEEK_APIKEY` | *(empty)* | model provider key (required for live answers/extraction) |
| `DEEPSEEK_MODEL` | `deepseek-flash` | DeepSeek model id for answers + transcript extraction |
| `ANSWERER` | `agent` | answerer backend: `agent` (OpenCode) or `pydantic` |
| `ADMIN_EMAILS` | *(empty)* | comma-separated emails granted admin rights (clear/ingest) |
| `GRAPHDB_URL` / `GRAPHDB_REPO` | `http://localhost:7200` / `sales-kg` | GraphDB endpoint |
| `GRAPHDB_AUTO_SECURE` | `1` | auto-enable GraphDB security at boot (`0` to skip) |
| `GRAPHDB_AUTO_PROVISION` | `1` | provision a read-only GraphDB user per registration (`0` to skip) |
| `DATABASE_URL` | `postgresql+psycopg://sales:sales@localhost:5432/sales` | app DB |
| `DATA_DIR` | `datasets/first_ingestion` | working CSV dir (compose mounts `./data/ingest`) |
| `PROMPT_GUARD` | `off` | `off` or `classifier` (a deterministic validator is always on) |
| `INGEST_CONCURRENCY` | `2` | max concurrently-running ingest jobs per worker |
| `RATE_LIMIT_CHAT_PER_MIN` | `10` | per-user chat requests/min (`0` disables) |
| `RATE_LIMIT_AUTH_PER_MIN` | `5` | per-IP auth requests/min (`0` disables) |

## Tests

```sh
# Offline Python suite (no LLM / GraphDB / Postgres); ~40s.
python -m pytest

# Live tests (opencode binary + DEEPSEEK_APIKEY + GraphDB required).
python -m pytest -m live

# UI unit tests (node --test).
node --test tests/ui.test.mjs

# Browser (Playwright) suite; boots its own uvicorn + worker on sqlite.
npx playwright test
```

Tests are offline by default (`-m "not live"` in `pytest.ini`) and carry a 60s
per-test timeout via `pytest-timeout`. The `auth_headers` fixture and every
register call skip GraphDB auto-provisioning so the suite never touches GraphDB.

## Repository layout

```
app/
  backend/          FastAPI app, answerers (agent/pydantic/stub), trace_helpers
  agent/            OpenCode harness + system.md agent instructions
  mcp/              MCP server (5 tools) + guards
  retrieval/        kg (SPARQL), vector (Chroma), keyword (BM25), transcripts
  ingestion/        service.run / merge / append / process_job + pipeline scripts
  auth/             JWT + GraphDB provisioning
  safety/           prompt validator + optional classifier
  queue/            DB-backed job queue + worker
  db/               SQLAlchemy models/engine/session
ontology/            TTL ontology, SHACL shapes, R2RML mappings
prompts/             extraction prompt + SPARQL example queries
datasets/            CRM source data (first_ingestion/ = seed, second_ingestion/ = extra)
docs/                challenge/notes documents
ui/                 static chat + ingest pages
tests/              pytest (offline default) + Playwright e2e + ui.test.mjs
```

## Notes

- This is an interview/prototype challenge: GraphDB is published with demo
  credentials and auth is a hand-rolled JWT. Not production security.
- The live `load` step writes to GraphDB via the admin path; the compose stack
  runs it with the read-only `reader` credential, so ingestion enqueues but the
  final GraphDB write can degrade with 403 (known, tracked as the "ingest
  credential" open question).
