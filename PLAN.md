# PLAN — Sales Intelligence KG: Security, Scale, Maintainability

## Goal
Evolve the working prototype (UI -> backend -> agent (OpenCode) -> MCP -> GraphDB / ChromaDB / BM25)
into a reviewable, secure, scalable app. Preserve working behavior at every step. Implement one
milestone at a time, with tests, and stop for review before the next.

## Locked decisions
1. **GraphDB auth:** single read-only service account for chat-time reads. GraphDB lives on an
   internal Docker network only (`7200` NOT published to host). Backend proxies visual links.
   App login (email) is the only user credential. Ingestion writes use a separate
   admin/ingest credential available only to the worker (see Open questions).
2. **DB + queue:** Postgres + DB-backed queue (`SELECT ... FOR UPDATE SKIP LOCKED`), worker with
   concurrency cap. In-process TTL cache. No Redis.
3. **Object storage:** MinIO (S3-compatible container). Uploads land in MinIO; worker stages
   locally (morph-kgc needs local CSV files).
4. **Prompt safety (3 layers):** (1) deterministic input validation, always on (length caps,
   jailbreak/injection blocklist, SPARQL-write rejection); (2) read-only tool sandbox — the real
   guarantee, the agent has no write tools; (3) optional LLM safety classifier gated by
   `PROMPT_GUARD=off|classifier`.
5. **Agent engine:** keep OpenCode subprocess + `sales` agent as the default answerer.
   Keep `pydantic_ai` registered in the factory but never the default; do not delete it.
6. **Auth stack:** minimal hand-rolled JWT (`pyjwt` + `passlib[bcrypt]` + `email-validator`).
   Chats are user-scoped; retrieval/ingestion data is global. PII is fine for demo.
7. **Transcripts:** `contact_ids` is REQUIRED, 7 columns always
   (`transcript_id,deal_id,account_id,contact_ids,activity_date,channel,transcript`).
   Missing values in existing data are backfilled with invented `C000`. No 6-vs-7 debate.
8. **Testing (test-first, every milestone):** M0 builds the safety net BEFORE any refactoring —
   API e2e (stub contract + ingestion) + agent-live structural test + LLM-judge on D007 +
   Playwright browser specs (chat, evidence, transcript modal, ingestion, GraphDB links).
   Each later milestone RUNs the net and ADDs/MODs tests where behavior changes.
   Follow `DESIGN.md` testing philosophy: few high-value tests, no trivial-test bloat.
9. **LLM judge (in M0):** single reference question `qa/q_easy.txt` (D007 decision criteria);
   judge = cheap OpenRouter model via `JUDGE_MODEL` env; pass = `score >= 50 AND verdict == pass`.
   Live tests (`-m live`) are default-off and skip when binary/key/services are missing.

## Supersession note
This plan supersedes the old prototype plan (M1–M8: package skeleton, chat backend, UI,
retrieval, MCP, agent, ingestion, cleanup) — that work is done. It also explicitly reverses
`DESIGN.md`'s "do not introduce queues / auth" constraint for this phase, because persistent
jobs, auth, and storage are now required. Still excluded: Redis, Elasticsearch/OpenSearch,
Kubernetes, microservices, LangChain/LlamaIndex, custom agent framework, CI/CD.

## Stack / architecture delta
- Add: `postgres` + `minio` + `worker` services to `docker-compose.yml`; internal network;
  named volumes for `chroma_db` and `kg.nt`/data state.
- Add: `app/db/` (engine/session/models/migrations), `app/auth/` (JWT), `app/queue/`
  (enqueue/claim/complete), `app/storage.py` (MinIO), `app/cache.py` (TTL), `app/safety/`
  (prompt guard).
- Change: `/api/ingest*` becomes validate -> MinIO -> enqueue -> `{job_id}`;
  `GET /api/jobs`, `GET /api/jobs/{id}` expose status; `ui/ingest.html` polls status.
- Keep: OpenCode `sales` agent, MCP 5-tool surface (read-only), GraphDB + Chroma + BM25.

## CSV merge (current behavior, preserved under single worker in M9)
- `merge_csv_files` (CRM tables): append-only, dedup-by-primary-key, all-or-nothing per upload.
  Resolve table by filename -> read existing keys from `DATA_DIR` -> parse upload -> validate
  everything (unknown table, empty/headerless, column mismatch, missing key, dup-in-batch,
  dup-vs-disk) -> append or reject whole upload.
- `append_transcript_rows` (transcripts): same idea with `transcript_id` key and 7-column
  layout; `contact_ids` required. Returns new ids; pipeline re-runs
  `build,index,extract,load` with `extract_ids=<new ids>` so the LLM step only processes
  new transcripts.
- In M9 the worker is the single writer (plus file lock), so merge races disappear.

## Testing strategy (applies to every milestone)
- **Shared offline fixture:** `tests/conftest.py` provides tmp `DATA_DIR`/`CHROMA_DIR`/`KG_NT`,
  `ANSWERER=stub`, stubbed `extract._generate` + `load.load` — every API test is
  offline/deterministic. M3 adds an `auth_headers` fixture (register+login, returns bearer
  header); M9 adds a `wait_for_job(client, job_id, headers)` helper driving the worker
  in-process (no container needed in tests).
- **Unit substitutes:** SQLite-in-memory for Postgres unit tests (real migrations verified
  manually via compose); monkeypatched/moto S3 client for MinIO unit tests; compose-file
  parse assertions where the real check needs Docker. Real container checks
  (restart persistence, host-port isolation) are manual and gated behind a `-m docker` marker,
  never in the default suite.
- **Playwright (Node runner):** scaffold lands in M0 — root `package.json` +
  `playwright.config.ts` (`webServer` boots uvicorn on 8123 with `ANSWERER=stub`), run with
  `npx playwright test` (one-time `npx playwright install chromium`, ~150MB, needs network once;
  test runtime is offline). Node is chosen because UI JS is already tested via `node:test`
  (`tests/ui.test.mjs`) and the Python env stays free of browser binaries. M0 specs: chat,
  evidence, transcript modal, ingestion, GraphDB links. Specs grow per milestone
  (M3 login, M4 proxy links, M9 job status, M11 contacts modal). Agent runs are API-level
  only, never Playwright (300s subprocess in a browser webServer would hang).
- **`data-testid` hooks** (all land in M0): `ui/index.html`: `chat-input, send-button,
  message-row, assistant-answer, evidence-headline, evidence-checked, evidence-section,
  visual-link, transcript-modal, contact-ids`; `ui/ingest.html`: `ingest-form,
  transcript-form, result, upload-error`. Later milestones add: M3 `login-form, login-email,
  login-password, login-submit`; M5 `chat-error`; M9 `job-status, job-id, job-error`;
  M13 `chat-history`.
- **Per-milestone rule:** each milestone lists RUN (existing files) + ADD/MOD (new/changed
  tests). The milestone is done only when its tests pass and the report includes
  command + output + exit code.

## Milestones — M0 first (safety net, no refactoring), then M1–M13 one at a time, stop for review after each

- **M0 — Test-first safety net (no app behavior changes; only `data-testid` hooks in UI).**
  Goal: lock current behavior — ask -> answer -> evidence panel -> GraphDB links -> ingestion —
  with stub tests, one agent test, one LLM-judge test, and browser specs, before refactoring.
  Files: ADD `pytest.ini` (register `live` marker, `addopts = -m "not live"`),
  `tests/conftest.py` (shared offline fixture + live skip-guard), `tests/test_api_e2e.py`,
  `tests/test_api_agent_live.py`, `tests/judge.py` (helper, not collected),
  `tests/test_judge_live.py`, root `package.json`, `playwright.config.ts`
  (`webServer` boots uvicorn on 8123 with `ANSWERER=stub`), `tests/e2e/fixtures.ts`,
  `tests/e2e/chat.spec.ts`, `tests/e2e/evidence.spec.ts`, `tests/e2e/transcript.spec.ts`,
  `tests/e2e/ingest.spec.ts`, `tests/e2e/links.spec.ts`;
  MOD `ui/index.html` (hooks only: `chat-input, send-button, message-row, assistant-answer,
  evidence-headline, evidence-checked, evidence-section, visual-link, transcript-modal,
  contact-ids`), MOD `ui/ingest.html` (hooks only: `ingest-form, transcript-form, result,
  upload-error`).
  Determinism: stub browser specs hit the real stub answerer (send `Deal_D007`, stub echoes
  it, UI linkifies to a GraphDB visual link); evidence/modal specs use Playwright
  `page.route()` interception with fixtures (zero app-code change). GraphDB link assertions
  check href shape (`/graphs-visualizations?uri=<encoded>&role=subject` + `target=_blank`),
  never navigate — real GraphDB opening is out of scope (offline specs, internal network).
  Tests — default-run: ADD `tests/test_api_e2e.py` (8: stub contract shape, meta evidence
  fields, history accepted, empty -> 400, RuntimeError -> 502, transcript fields,
  transcript 404, health answerer); RUN `tests/test_api.py` (7), `tests/test_ingest_api.py`
  (11: CRM + transcript + error paths), `tests/ui.test.mjs` (5); ADD 5 Playwright specs
  (16: chat 4, evidence 4, transcript 3, ingest 3, links 2).
  Tests — live (`-m live`, default-off, skip when `opencode`/keys/services missing):
  ADD `tests/test_api_agent_live.py` (2: D007 answer structure + sources trace shape, no
  exactness); ADD `tests/test_judge_live.py` (1: `qa/q_easy.txt` through the agent, judged
  by `JUDGE_MODEL`, pass iff `score >= 50 AND verdict == pass`).
  Totals: default 31 pytest (8 new + 7 + 11 + 5 node) + 16 Playwright; live 3.
  Contract locked for M1–M13: `/api/chat` `{answer,sources,meta}` shape,
  `meta.engine/graphdb_url/graphdb_repo/iris`, `health.answerer`, transcript fields,
  evidence headline/`How I checked:`/`details>summary` structure, visual-link path+query
  shape + `target=_blank`. Allowed to change later: auth headers/login (M3), link host/base
  -> proxy (M4), ingest async `{job_id}` (M9), `contact_ids` in modal (M11).
  Verify: `python -m pytest -q` + `node --test tests/ui.test.mjs` +
  `npx playwright test` (after one-time `npx playwright install chromium`); live:
  `python -m pytest -m live -q`.

- **M1 — Read-only guard at retrieval boundary.**
  Goal: no SPARQL write can reach GraphDB from any path.
  Files: `app/retrieval/kg.py` (call `assert_readonly` inside `run_sparql`),
  `app/mcp/guards.py`, `app/mcp/server.py`, `app/backend/answerers/pydantic_agent.py`
  (dedupe guard calls).
  Tests — RUN `tests/test_guards.py`, `tests/test_retrieval.py`; MOD `test_retrieval.py`:
  `test_run_sparql_rejects_insert/_delete` (spy `requests.get`, assert never called),
  `test_run_sparql_select_still_returns`.
  Verify: `python -m pytest tests/test_guards.py tests/test_retrieval.py -q`.

- **M2 — Postgres + base infra.**
  Goal: database and migrations running; nothing else changes behavior.
  Files: `docker-compose.yml` (postgres service + volume), `requirements.txt`
  (`sqlalchemy`, `psycopg[binary]`, `alembic`), `app/config.py` (DSN), new `app/db/`
  (engine/session/models `User,Chat,Message,Job`/migrations), `app/backend/app.py`
  (lifespan/health), new `tests/conftest.py` (shared offline fixture).
  Tests — RUN `tests/test_api.py` (health); ADD `tests/test_db.py`:
  `test_migrations_apply`, `test_user_chat_message_roundtrip` (SQLite unit),
  `test_health_reports_db`.
  Verify: `docker compose config`, `docker compose up -d postgres`,
  `docker compose exec postgres pg_isready`, `python -m pytest tests/test_db.py tests/test_api.py -q`.

- **M3 — Registration + authentication (extends M0 net).**
  Goal: email register/login/me with JWT; chats user-scoped; browser spec logs in first.
  Files: new `app/auth/` (`security.py` hashing+JWT, `deps.py` `get_current_user`,
  `routes.py` register/login/me), `app/backend/app.py` (protect `/api/chat`,
  `/api/transcripts/*`, `/api/ingest*`), `app/backend/schemas.py`, `app/config.py`
  (JWT secret/TTL), `ui/index.html` (login + `Authorization` header + history +
  login `data-testid` hooks: `login-form, login-email, login-password, login-submit`).
  Tests — RUN M0 net (`tests/test_api_e2e.py`, Playwright); ADD `tests/test_auth.py`:
  `test_register_login_happy`, `test_wrong_password_401`, `test_chat_unauth_401`,
  `test_user_a_cannot_read_user_b_chat`; MOD `test_api.py` + `test_api_e2e.py`
  chat/transcript calls to use `auth_headers` fixture; MOD `tests/e2e/chat.spec.ts`
  to log in first.
  Verify: `python -m pytest tests/test_auth.py tests/test_api.py tests/test_api_e2e.py -q` + `npx playwright test tests/e2e/chat.spec.ts`.

- **M4 — GraphDB isolation + visual-link proxy.**
  Goal: GraphDB unreachable from host; UI visual links keep working via auth'd proxy.
  Files: `docker-compose.yml` (drop `7200` publish, internal network, creds env),
  `app/config.py`, `app/backend/app.py` (proxy with host allowlist),
  `ui/index.html` (`gdbBase`, `visualLink`, link builders + `visual-link` hook),
  `load.py` (ingest creds), `docker/entrypoint.sh` if env plumbing changes.
  Tests — RUN `tests/test_api.py`; ADD `tests/test_proxy.py`:
  `test_proxy_requires_auth`, `test_proxy_rejects_foreign_host` (SSRF allowlist),
  `test_compose_7200_not_published` (parse compose yaml; real host-curl check manual);
  ADD Playwright `proxy-links.spec.ts`: visual link href points at proxy (shape assertion
  survives the host/base swap).
  Verify: `python -m pytest tests/test_proxy.py tests/test_api.py -q` + `docker compose config` + `npx playwright test`.

- **M5 — Prompt safety (3 layers).**
  Goal: deterministic validation always on; sandbox verified; classifier optional.
  Files: new `app/safety/` (validator + optional classifier), `app/config.py`
  (`PROMPT_GUARD`), `app/backend/app.py` (validate in `/api/chat` before answerer),
  `app/mcp/server.py` (read-only surface), `app/agent/system.md` (harden grounding),
  `ui/index.html` (`chat-error` hook).
  Tests — RUN `tests/test_guards.py`, `tests/test_api.py`; ADD `tests/test_safety.py`:
  `test_length_cap_400`, `test_jailbreak_blocklist_400`,
  `test_sparql_write_in_message_rejected_before_answerer` (spy answerer, assert not called),
  `test_prompt_guard_off_and_classifier_modes` (classifier stubbed offline);
  sandbox check = static assertion that `sales` agent exposes only MCP tools + fail-closed
  smoke (real headless agent run is manual, not in default suite).
  Verify: `PROMPT_GUARD=off python -m pytest tests/test_safety.py tests/test_guards.py -q`, repeat with `=classifier`.

- **M6 — Upload + rate hardening.**
  Goal: bounded uploads and chat rate; malicious cells rejected.
  Files: `app/backend/ingest.py` (replace unbounded `await upload.read()` with size/count/
  extension caps), `app/backend/app.py` (body-size middleware + per-user rate limit),
  `app/config.py`, `ui/ingest.html` (413/429 display + `upload-error` hook),
  `tests/test_ingest_api.py`.
  Tests — RUN `tests/test_ingest_api.py`; MOD same file: `test_oversized_upload_413`,
  `test_too_many_files_rejected`, `test_chat_rate_limit_429`,
  `test_formula_injection_cell_rejected`.
  Verify: `python -m pytest tests/test_ingest_api.py -q`.

- **M7 — MinIO object storage.**
  Goal: uploads stored in MinIO instead of direct CSV writes.
  Files: `docker-compose.yml` (minio + volume + network), `requirements.txt` (minio/boto3),
  `app/config.py`, new `app/storage.py` (put/get/list/delete), `app/backend/ingest.py`
  (store bytes in MinIO), `app/ingestion/service.py` (stage from MinIO).
  Tests — RUN `tests/test_ingest_api.py`, `tests/test_ingest_service.py`;
  ADD `tests/test_storage.py`: `test_storage_roundtrip`, `test_upload_lands_in_bucket`
  (monkeypatched/moto S3, no container; real `docker compose up -d minio` manual).
  Verify: `python -m pytest tests/test_storage.py tests/test_ingest_api.py -q`.

- **M8 — Chroma + kg.nt persistence.**
  Goal: vector index and built graph survive container restarts.
  Files: `docker-compose.yml` (named volumes), `Dockerfile` (stop baking `chroma_db`),
  `.dockerignore`/`.gitignore`, `app/config.py` (`CHROMA_DIR`, `KG_NT` under mounted data),
  `build.py`, `index_transcripts.py`, `load.py`.
  Tests — RUN `tests/test_ingest_service.py`; ADD compose-parse test
  `test_named_volumes_for_chroma_and_kgnt`; real `down/up` restart persistence is an
  opt-in `-m docker` script run manually.
  Verify: `python -m pytest tests/test_ingest_service.py -q` + manual restart check.

- **M9 — Job queue + worker + status UI.**
  Goal: ingestion is async, persistent, concurrency-capped, visible in UI.
  Files: `docker-compose.yml` (worker service), new `app/queue/` (`SKIP LOCKED`
  enqueue/claim/complete/fail + cap), `app/backend/ingest.py` (enqueue -> `{job_id}`),
  `app/backend/app.py` (`GET /api/jobs`, `GET /api/jobs/{id}`), `app/ingestion/service.py`
  (worker entry), `ui/ingest.html` (status polling + `job-status/job-id/job-error` hooks).
  Tests — RUN `tests/test_ingest_api.py`; ADD `tests/test_queue.py`:
  `test_queued_running_done`, `test_concurrency_cap_respected`,
  `test_failed_job_surfaces_error`, `test_jobs_scoped_to_user`; MOD `test_ingest_api.py`
  to expect `{job_id}` + drive worker via in-process `wait_for_job` helper;
  ADD Playwright `ingest-job.spec.ts`: upload -> status flips to done.
  Verify: `python -m pytest tests/test_queue.py tests/test_ingest_api.py -q` + `npx playwright test tests/e2e/ingest-job.spec.ts`.

- **M10 — Retrieval performance + caching.**
  Goal: no repeated GraphDB/Chroma/LLM work for identical queries; ingest invalidates.
  Files: new `app/cache.py` (TTL), `app/retrieval/kg.py`, `app/retrieval/vector.py`,
  `app/retrieval/keyword.py`, `app/retrieval/transcripts.py` (row cache),
  `app/config.py`, `app/ingestion/service.py` (invalidate on ingest).
  Tests — RUN `tests/test_retrieval.py`; ADD `tests/test_cache.py`:
  `test_second_identical_query_hits_cache` (backend called once),
  `test_ingest_invalidates_cache`, `test_ttl_expiry`.
  Verify: `python -m pytest tests/test_retrieval.py tests/test_cache.py -q`.

- **M11 — contact_ids required (7 columns always).**
  Goal: kill the 6-vs-7 ambiguity; backfill; enforce; expose.
  Files: `app/ingestion/service.py` (header, `_TRANSCRIPT_FIELDS`, required list),
  `app/backend/ingest.py` (reject rows missing `contact_ids` instead of inserting `""`),
  `app/retrieval/transcripts.py` (`_FIELDS` gains `contact_ids`, returned as list),
  backfill script (invent `C000`) applied to `mock_crm_dataset/transcripts.csv`,
  `data/ingest/transcripts.csv`, `data/new_crm/transcripts.csv`,
  `tests/fixtures/new_crm/transcripts.csv`, `ui/index.html` (transcript modal shows
  contacts + `transcript-modal/contact-ids` hooks).
  Tests — RUN `tests/test_ingest_service.py`, `tests/test_ingest_api.py`,
  `tests/test_retrieval.py`; MOD them: `test_six_col_row_rejected`,
  `test_append_requires_contact_ids`, `test_transcript_includes_contact_ids_list`;
  migrate 6-col fixtures in `test_extract.py`/`test_ingest_api.py` to 7 columns;
  ADD `tests/test_backfill.py`: `test_backfill_invents_c000_idempotent`;
  ADD Playwright `contacts.spec.ts`: modal shows contact_ids.
  Verify: `python -m pytest tests/test_ingest_service.py tests/test_ingest_api.py tests/test_retrieval.py tests/test_backfill.py -q` + `npx playwright test`.

- **M12 — Cleanup / dedup.**
  Goal: smaller, clearer codebase; `pydantic_ai` kept but non-default.
  Files: shared helpers module for `_extract_iris`/`_sparql_bindings`/`_normalize_hit`/
  `_truncate`/`clean` (used by `baseline.py`, `pydantic_agent.py`, `opencode.py`);
  unify transcript field constants; retire obsolete root scripts
  (`ask_step1.py`, `ask_step2.py`, `search_transcripts*.py`); update `DESIGN.md` notes;
  add missing `README.md` runbook.
  Tests — RUN full `python -m pytest -q` + `node --test tests/ui.test.mjs`;
  ADD `tests/test_helpers.py` only for the new shared API (`test_extract_iris_dedupes`,
  `test_normalize_hit_shapes_dict`, `test_truncate`); `test_sources.py` stays the
  regression net.
  Verify: both commands above, exit 0.

- **M13 — Full E2E + final Playwright pass.**
  Goal: one-command confidence across the whole stack.
  Files: new `tests/test_e2e.py`, remaining `data-testid` hooks (`chat-history`),
  Playwright config/specs finalized.
  Tests — RUN everything: `python -m pytest -q`, `node --test tests/ui.test.mjs`,
  `npx playwright test`; ADD `tests/test_e2e.py`: `test_ingest_then_chat_cites_transcript`,
  `test_known_d001_question` (stub/baseline, offline).
  Verify: `python -m pytest tests/test_e2e.py -q` + `npx playwright test`.

## Rules
- Small, reviewable diffs; do not refactor unrelated code; reuse existing code.
- M0 first: safety net green before any refactoring. Every later milestone must RUN the M0
  net (API e2e + Playwright) and ADD/MOD tests where behavior changes; no milestone is done
  with testing deferred.
- After each milestone report: files changed, behavior changed, tests/checks run
  (command + output + exit code), known limitations.
- Stop and wait for review (user says `go`) before the next milestone.

## Open questions (flagged, not blocking M1)
1. GraphDB ingest credential: separate admin user for worker vs single account (M4).
2. Worker concurrency cap value; staging dir location vs `DATA_DIR` mount (M9).
3. Rate-limit backend: in-process is fine single-worker; DB-backed if multi-worker later (M6).
4. M12 deletes vs deprecates root scripts — confirm at M12 time.
