"""Answerer selection based on ``app.config.ANSWERER``.

``get_answerer()`` returns the module exposing ``answer(question, history)`` so
callers use it uniformly as ``get_answerer().answer(...)``.
"""
from app import config

_DEFAULT = "agent"
_KNOWN = ("stub", "agent", "pydantic")


def get_answerer():
    name = (config.ANSWERER or _DEFAULT).strip().lower()

    if name == "stub":
        from app.backend.answerers import stub

        return stub
    if name == "agent":
        from app.backend.answerers import agent

        return agent
    if name == "pydantic":
        from app.backend.answerers import pydantic_agent

        return pydantic_agent

    raise ValueError(
        f"Unknown ANSWERER: {config.ANSWERER!r} (expected one of {', '.join(_KNOWN)})"
    )
