"""Package the currently-ingested data back into the tracked ``datasets/``.

If you ingested data through the UI/API, the source CSVs land in the mounted
``data/ingest`` dir (plus extracted transcript facts under ``data/ingest/extracted``).
Copy them into ``datasets/first_ingestion/`` so they can be git-committed and
replayed on another box by ``scripts/seed_kg.py``.

Usage:  python scripts/export_snapshot.py

The extracted facts (``data/ingest/extracted``) are the LLM output; commit them
too (``git add -f`` — they are gitignored) if you want ``seed_kg.py`` deployments
to skip the LLM re-extraction.
"""
from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INGEST = REPO_ROOT / "data" / "ingest"
DATASETS = REPO_ROOT / "datasets" / "first_ingestion"


def _copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst / rel)


def main() -> None:
    if not INGEST.is_dir():
        print(f"no data at {INGEST}; ingest something first")
        return
    DATASETS.mkdir(parents=True, exist_ok=True)
    for csv in sorted(INGEST.glob("*.csv")):
        shutil.copy2(csv, DATASETS / csv.name)
        print("copied", csv.name)
    extracted = INGEST / "extracted"
    if extracted.is_dir():
        _copy_tree(extracted, DATASETS / "extracted")
        print("copied extracted/")
    print("\nCommit them (extracted/ is gitignored; force-add if desired):")
    print("  git add datasets/first_ingestion")
    print("  git add -f datasets/first_ingestion/extracted   # optional")


if __name__ == "__main__":
    main()
