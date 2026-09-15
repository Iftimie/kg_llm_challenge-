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

OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta/muse-spark-1.3-contributor")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Transcript extraction reuses the agent model unless overridden.
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", OPENROUTER_MODEL)

# PydanticAI answerer (OpenAI-compatible endpoint, default OpenRouter).
PYDANTIC_MODEL = os.environ.get("PYDANTIC_MODEL", OPENROUTER_MODEL)
PYDANTIC_BASE_URL = os.environ.get("PYDANTIC_BASE_URL", "https://openrouter.ai/api/v1")
PYDANTIC_API_KEY = os.environ.get("PYDANTIC_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))

# Answerer implementation selected by the QA/agent layer.
ANSWERER = os.environ.get("ANSWERER", "baseline")

# Reserved for a future DeepSeek-backed answerer.
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "")

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
