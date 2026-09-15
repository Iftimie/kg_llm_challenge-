"""Read-only guards for the MCP tool surface (stdlib only).

The MCP server must never mutate the knowledge graph, so every SPARQL entry
point is validated here before it reaches the retrieval layer.
"""
import re

# SPARQL query forms that are safe to run through the MCP tools.
READ_ONLY = ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE")

# Update/DDL keywords that must never reach GraphDB.
BLOCKED = ("INSERT", "DELETE", "CLEAR", "DROP", "CREATE", "LOAD", "MOVE", "COPY", "ADD")

# Shared limits for the MCP tools.
SPARQL_TIMEOUT = 30
MAX_ROWS = 100
MAX_TOP_K = 10

_COMMENT_RE = re.compile(r"#[^\n]*")
# IRIs (<...>) and quoted literals are masked before comment stripping so a
# '#' inside them (e.g. <http://www.w3.org/2000/01/rdf-schema#>) is never
# mistaken for the start of a comment.
_MASK_RE = re.compile(r"<[^>]*>|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
_MASKED_RE = re.compile(r"\x00(\d+)\x00")
# Prologue declarations that may legally precede the query keyword.
_PREFIX_IRI_RE = re.compile(r"PREFIX\s+\S+\s*<[^>]*>", re.IGNORECASE)
_PREFIX_PNAME_RE = re.compile(r"PREFIX\s+\S+:\s*\S+", re.IGNORECASE)
_BASE_RE = re.compile(r"BASE\s+<[^>]*>", re.IGNORECASE)


def _strip_comments(sparql: str) -> str:
    """Drop ``#`` line comments without touching IRIs or quoted literals.

    IRI ``<...>`` blocks and quoted strings are swapped for ``\\x00N\\x00``
    placeholders, comments are removed outside those placeholders, and the
    originals are restored afterwards.
    """
    masked = []

    def _mask(match):
        masked.append(match.group(0))
        return "\x00%d\x00" % (len(masked) - 1)

    out = _MASK_RE.sub(_mask, sparql)
    out = _COMMENT_RE.sub(" ", out)

    def _restore(match):
        return masked[int(match.group(1))]

    return _MASKED_RE.sub(_restore, out)


def assert_readonly(sparql) -> str:
    """Validate a SPARQL string and return its leading keyword (upper-case).

    Comments, ``PREFIX`` declarations, and ``BASE`` declarations are stripped
    before the first keyword is inspected, so ``PREFIX crm: <...> SELECT ...``
    is accepted. Raises ``ValueError`` unless that keyword is
    SELECT/ASK/CONSTRUCT/DESCRIBE.
    """
    stripped = _strip_comments(sparql or "")
    stripped = _PREFIX_IRI_RE.sub(" ", stripped)
    stripped = _PREFIX_PNAME_RE.sub(" ", stripped)
    stripped = _BASE_RE.sub(" ", stripped)
    stripped = stripped.strip()
    keyword = stripped.split(None, 1)[0].upper() if stripped else ""
    if keyword not in READ_ONLY:
        raise ValueError(
            f"refusing {keyword or '<empty>'} query: only "
            "SELECT/ASK/CONSTRUCT/DESCRIBE allowed"
        )
    return keyword


def clamp_top_k(v, default=3, lo=1, hi=10) -> int:
    """Coerce ``v`` to an int within ``[lo, hi]``, falling back to ``default``."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = default
    return min(max(n, lo), hi)
