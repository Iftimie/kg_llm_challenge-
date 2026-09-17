"""Optional LLM safety classifier (layer 3 of the 3-layer guard).

This is a STUB INTERFACE for a future network/LLM classifier: ``classify``
today is a pure keyword heuristic that reuses the deterministic jailbreak
blocklist, so it is offline and deterministic. A real implementation would call
a hosted moderation model while keeping the same ``classify(text) -> bool``
contract (True = safe, False = blocked).
"""
from app.safety.validator import JAILBREAK_PHRASES


def classify(text: str) -> bool:
    """Return False if any jailbreak phrase is present, else True.

    KeywordClassifier heuristic stand-in: no network, no model. Gated by
    ``PROMPT_GUARD=classifier``; the deterministic validator always runs first.
    """
    lowered = (text or "").lower()
    for phrase in JAILBREAK_PHRASES:
        if phrase in lowered:
            return False
    return True
