"""Canned answerer used for wiring/tests (ANSWERER=stub). Makes no external calls."""
from app import config
from app.backend.schemas import ChatResponse


def answer(question: str, history=None) -> ChatResponse:
    """Return a fixed response so the API can be exercised without services."""
    return ChatResponse(
        answer=f"stub answer to: {question}",
        sources=[],
        meta={
            "engine": "stub",
            "graphdb_url": config.GRAPHDB_URL,
            "graphdb_repo": config.GRAPHDB_REPO,
            "iris": [],
        },
    )
