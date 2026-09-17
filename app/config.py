"""Centralized configuration for the Sales Intelligence app.

Standard library only. Every setting can be overridden with an environment
variable; defaults match the values previously hardcoded in the top-level scripts.
"""
import os
from pathlib import Path

# Repository root = parent of the app/ package.
REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Services -----------------------------------------------------------------
GRAPHDB_URL = os.environ.get("GRAPHDB_URL", "http://localhost:7200")
GRAPHDB_REPO = os.environ.get("GRAPHDB_REPO", "sales-kg")
# GraphDB credentials. Empty = no auth (local dev, security off); compose sets
# the read-only reader account after scripts/graphdb_secure.py enables security.
GRAPHDB_USER = os.environ.get("GRAPHDB_USER", "")
GRAPHDB_PASSWORD = os.environ.get("GRAPHDB_PASSWORD", "")
# Admin creds for auto-provisioning a GraphDB user per app registration (interview challenge, not production)
GRAPHDB_ADMIN_USER = os.environ.get("GRAPHDB_ADMIN_USER", "admin")
GRAPHDB_ADMIN_PASSWORD = os.environ.get("GRAPHDB_ADMIN_PASSWORD", "admin")
# "1" (default) provisions a read-only GraphDB user on every registration; set
# "0" to skip (offline unit tests) so register never touches GraphDB.
GRAPHDB_AUTO_PROVISION = os.environ.get("GRAPHDB_AUTO_PROVISION", "1")
# Upstream timeout (seconds) for the authenticated GraphDB visual proxy.
GRAPHDB_TIMEOUT_S = float(os.environ.get("GRAPHDB_TIMEOUT_S", "10"))

# off|classifier; deterministic validator always on, classifier optional; unknown value fails closed (500)
PROMPT_GUARD = os.environ.get("PROMPT_GUARD", "off")
MAX_PROMPT_CHARS = int(os.environ.get("MAX_PROMPT_CHARS", "4000"))

# --- Rate limiting (in-memory, single instance) -------------------------------
# 0 disables a limit. Chat is scoped per authenticated user, auth per client IP.
RATE_LIMIT_CHAT_PER_MIN = int(os.environ.get("RATE_LIMIT_CHAT_PER_MIN", "10"))
RATE_LIMIT_AUTH_PER_MIN = int(os.environ.get("RATE_LIMIT_AUTH_PER_MIN", "5"))

# Worker concurrency cap: max concurrently-running ingest jobs per worker process.
INGEST_CONCURRENCY = int(os.environ.get("INGEST_CONCURRENCY", "2"))

# --- Database -----------------------------------------------------------------
# Postgres is the only supported backend; there is no SQLite fallback. Offline
# tests override this via env/monkeypatch to an in-memory SQLite engine.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://sales:sales@localhost:5432/sales"
)

# --- Auth ---------------------------------------------------------------------
# dev-only default; set JWT_SECRET env in production
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-secret-change-me-in-production-0123456789")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta/muse-spark-1.3-contributor")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# DeepSeek (OpenAI-compatible) — the single model used for answers + extraction.
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_APIKEY = os.environ.get("DEEPSEEK_APIKEY", "")

# OpenCode agent model id (provider/model), default DeepSeek Flash.
OPENCODE_MODEL = os.environ.get("OPENCODE_MODEL", "deepseek/deepseek-flash")

# Transcript extraction reuses the agent model unless overridden.
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", DEEPSEEK_MODEL)

# PydanticAI answerer (OpenAI-compatible endpoint, default OpenRouter).
PYDANTIC_MODEL = os.environ.get("PYDANTIC_MODEL", OPENROUTER_MODEL)
PYDANTIC_BASE_URL = os.environ.get("PYDANTIC_BASE_URL", "https://openrouter.ai/api/v1")
PYDANTIC_API_KEY = os.environ.get("PYDANTIC_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))

# Answerer implementation selected by the QA/agent layer.
ANSWERER = os.environ.get("ANSWERER", "agent")

# "chroma-default" means "use ChromaDB's built-in embedding function".
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "chroma-default")

# --- Paths (relative to the repository root) ----------------------------------
ONTOLOGY_PATH = REPO_ROOT / "sales_kg_ontology_v1_llm_friendly.ttl"  # canonical ontology
BASE_ONTOLOGY_PATH = REPO_ROOT / "sales_kg_ontology_v1.ttl"
SHAPES_PATH = REPO_ROOT / "shapes.ttl"
MAPPINGS_PATH = REPO_ROOT / "mappings.ttl"
MORPH_INI = REPO_ROOT / "morph.ini"
CRM_DIR = REPO_ROOT / "mock_crm_dataset"
DATA_DIR = Path(os.environ.get("DATA_DIR", str(REPO_ROOT / "mock_crm_dataset")))
KG_NT = REPO_ROOT / "kg.nt"
EXTRACTED_DIR = DATA_DIR / "extracted"
CHROMA_DIR = REPO_ROOT / "chroma_db"
QA_DIR = REPO_ROOT / "qa"
COMPETENCY_QUERIES = REPO_ROOT / "competency_queries.txt"

# --- Logging ------------------------------------------------------------------
LOG_FILE = Path(os.environ.get("LOG_FILE", REPO_ROOT / "logs" / "app.log"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# JSON-lines log of MCP tool calls, written by app.mcp.server and read by the
# agent harness to rebuild the retrieval trace from server-side ground truth.
MCP_LOG = REPO_ROOT / "logs" / "mcp_calls.jsonl"
