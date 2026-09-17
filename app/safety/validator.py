"""Deterministic prompt-safety validation (layer 1 of the 3-layer guard).

Always-on checks run in ``/api/chat`` before the answerer is invoked: a length
cap, a jailbreak/injection blocklist, and rejection of pasted SPARQL write
statements. Stdlib only, so importing this module never pulls in LLM or MCP
server dependencies.
"""
import re

from app import config
from app.mcp.guards import BLOCKED

# Imported from config so tests/env can override the cap.
MAX_PROMPT_CHARS = config.MAX_PROMPT_CHARS

# Case-insensitive substring blocklist for jailbreak / prompt-injection attempts.
JAILBREAK_PHRASES = (
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "act as",
    "dan mode",
    "system prompt",
    "reveal your prompt",
    "jailbreak",
    "do anything now",
)

# SPARQL-write keyword check for chat messages. We reuse the MCP guard's BLOCKED
# word list so both surfaces deny the same verbs, but we compile our OWN
# CASE-SENSITIVE regex (no re.IGNORECASE): only UPPERCASE keywords match.
# Tradeoff: natural-language uses of the same words in lowercase (e.g. "please
# add a note", "let's create a list") are NOT blocked, which would otherwise be
# a constant false positive on free prose. The read-only tool sandbox (layer 2)
# is the real guarantee against writes; this check is a coarse deterrent against
# obviously pasted SPARQL update statements.
_SPARQL_WRITE_RE = re.compile(
    r"(?<![\w:?])(?:" + "|".join(BLOCKED) + r")(?![\w:])"
)


def validate(message: str) -> None:
    """Raise ``ValueError`` with a clear detail if ``message`` is unsafe.

    Order: empty -> length -> jailbreak -> SPARQL-write. The empty check
    duplicates the one already in ``chat()`` on purpose so ``validate`` is safe
    to call standalone; the duplication is harmless.
    """
    if not message or not message.strip():
        raise ValueError("message must be a non-empty string")

    if len(message) > MAX_PROMPT_CHARS:
        raise ValueError(f"message too long: max {MAX_PROMPT_CHARS} characters")

    lowered = message.lower()
    for phrase in JAILBREAK_PHRASES:
        if phrase in lowered:
            raise ValueError(f"blocked phrase: {phrase}")

    blocked = _SPARQL_WRITE_RE.search(message)
    if blocked:
        raise ValueError(
            f"SPARQL update keyword {blocked.group(0).upper()} not allowed in chat"
        )
