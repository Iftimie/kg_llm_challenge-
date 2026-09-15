"""Answerer selection based on ``app.config.ANSWERER``.

``get_answerer()`` returns the module exposing ``answer(question, history)`` so
callers use it uniformly as ``get_answerer().answer(...)``.
"""
from app import config

_DEFAULT = "baseline"
_KNOWN = ("stub", "baseline")


def get_answerer():
    name = (config.ANSWERER or _DEFAULT).strip().lower()

    if name == "stub":
        from app.backend.answerers import stub

        return stub
    if name == "baseline":
        from app.backend.answerers import baseline

        return baseline

    raise ValueError(
        f"Unknown ANSWERER: {config.ANSWERER!r} (expected one of {', '.join(_KNOWN)})"
    )
