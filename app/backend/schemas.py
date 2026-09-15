"""Transport schemas for the backend <-> UI boundary.

Dependency-free (stdlib dataclasses only) so the package skeleton imports
before FastAPI/pydantic are introduced.
"""
from dataclasses import dataclass, field


@dataclass
class ChatRequest:
    message: str
    history: list = field(default_factory=list)


@dataclass
class ChatResponse:
    answer: str
    sources: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
