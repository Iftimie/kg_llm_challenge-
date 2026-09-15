"""Agent answerer (ANSWERER=agent): delegate to the OpenCode harness.

``run_agent`` raises :class:`RuntimeError` on subprocess failures; it is left to
propagate so the backend maps it to HTTP 502.
"""
from app.agent.opencode import run_agent
from app.backend.schemas import ChatResponse


def answer(question: str, history=None) -> ChatResponse:
    """Run the OpenCode agent and adapt its result to ``ChatResponse``."""
    result = run_agent(question, history=history)
    return ChatResponse(
        answer=result["answer"],
        sources=result.get("sources", []),
        meta=result.get("meta", {}),
    )
