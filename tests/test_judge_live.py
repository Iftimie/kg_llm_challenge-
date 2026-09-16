"""Live LLM-judge test on the reference question (``qa/q_easy.txt``).

Default-off: run explicitly with ``python -m pytest -m live``. Judge
infrastructure failures (no ``JUDGE_MODEL``, no network, bad response) skip
rather than fail -- the judge is a scoring aid, not ground truth about the app.
"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.backend.app import app
from tests import judge as judge_mod

pytestmark = pytest.mark.live

client = TestClient(app)

REFERENCE_FACTS = (
    "Deal D007 is in Negotiation stage with value 175000 for FinPeak Risk "
    "Analytics; governance resolved; customer wants 2- and 3-year pricing "
    "options; ready for legal."
)


def test_judge_q_easy_d007_passes(live_guard, monkeypatch):
    question = (config.QA_DIR / "q_easy.txt").read_text(encoding="utf-8").strip()

    monkeypatch.setattr(config, "ANSWERER", "agent")
    response = client.post("/api/chat", json={"message": question})
    assert response.status_code == 200, response.text
    candidate = response.json()["answer"]

    try:
        result = judge_mod.judge(question, REFERENCE_FACTS, candidate)
    except RuntimeError as exc:
        pytest.skip(f"judge unavailable: {exc}")

    assert result["score"] >= 50, result
    assert result["verdict"] == "pass", result
