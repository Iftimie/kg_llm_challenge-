"""Reproduce an ingested state from the tracked ``datasets/`` source data.

The CSVs under ``datasets/`` are the source of truth — committing them is all the
"packaging" you need. On a fresh deploy (AWS or local Docker), run::

    docker compose exec app python scripts/seed_kg.py

to ingest both ``first_ingestion`` and ``second_ingestion`` and rebuild the
graph, vector index and transcript facts.

Run once against a fresh DATA_DIR (the merge is append-only and rejects duplicate
primary keys). The ``extract`` step calls the configured LLM (``DEEPSEEK_APIKEY``);
for a small test dataset this is cheap.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config  # noqa: E402
from app.ingestion import service  # noqa: E402


def main() -> None:
    data_dir = Path(config.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    for name in ("first_ingestion", "second_ingestion"):
        src = REPO_ROOT / "datasets" / name
        if not src.is_dir():
            continue
        files = [(p.name, p.read_bytes()) for p in sorted(src.glob("*.csv"))]
        if not files:
            continue
        merged = service.merge_csv_files(files, data_dir)
        print(f"{name}: merged {merged}")

    result = service.run(data_dir, steps=("build", "index", "extract", "load"))
    for step, value in result.items():
        print(f"{step}: {value}")


if __name__ == "__main__":
    main()
