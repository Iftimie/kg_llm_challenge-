"""Centralized configuration for the Sales Intelligence app.

Standard library only. Every setting can be overridden with an environment
variable; defaults match the values previously hardcoded in the top-level scripts.
"""
import os
from pathlib import Path

# Repository root = parent of the app/ package.
REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Services -----------------------------------------------------------------
GRAPHDB_URL = os.environ.get("GRAPHDB_URL", "http://127.0.0.1:7200")
GRAPHDB_REPO = os.environ.get("GRAPHDB_REPO", "sales-kg")

OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta/muse-spark-1.3-contributor")

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
KG_NT = REPO_ROOT / "kg.nt"
EXTRACTED_DIR = REPO_ROOT / "extracted"
CHROMA_DIR = REPO_ROOT / "chroma_db"
QA_DIR = REPO_ROOT / "qa"
COMPETENCY_QUERIES = REPO_ROOT / "competency_queries.txt"
