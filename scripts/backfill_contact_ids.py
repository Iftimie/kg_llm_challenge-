"""Backfill empty ``contact_ids`` cells in a ``transcripts.csv`` file.

``contact_ids`` is now required (non-empty) for every transcript row. This
script fills any empty ``contact_ids`` cell with ``C000`` so existing
``transcripts.csv`` files satisfy the new invariant.

Idempotent: the file is rewritten only when at least one empty cell was filled;
re-running over an already-backfilled file leaves it byte-for-byte unchanged.
The header and every row are preserved verbatim (via the stdlib ``csv`` module).

Usage::

    python scripts/backfill_contact_ids.py [path/to/transcripts.csv]

Defaults to ``datasets/first_ingestion/transcripts.csv``.
"""
import csv
import sys
from pathlib import Path

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "datasets" / "first_ingestion" / "transcripts.csv"
)

FALLBACK = "C000"


def backfill(path: Path, fallback: str = FALLBACK) -> dict:
    """Fill empty contact_ids in ``path``; return ``{total, filled, changed}``."""
    path = Path(path)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    if not rows:
        return {"total": 0, "filled": 0, "changed": False}

    header = rows[0]
    try:
        idx = header.index("contact_ids")
    except ValueError:
        idx = 3  # 7-column transcripts.csv layout has contact_ids in column 3

    filled = 0
    for row in rows[1:]:
        if idx < len(row) and not row[idx].strip():
            row[idx] = fallback
            filled += 1

    changed = filled > 0
    if changed:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)

    return {"total": len(rows) - 1, "filled": filled, "changed": changed}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else DEFAULT_PATH
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 2

    result = backfill(path)
    state = "rewritten" if result["changed"] else "unchanged"
    print(f"{path}: filled {result['filled']}/{result['total']} rows ({state})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
