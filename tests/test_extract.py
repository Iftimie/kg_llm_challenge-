"""Unit tests for the OpenRouter-backed transcript extraction (``extract.py``).

No network/model calls: ``extract.requests.post`` is always monkeypatched.
"""
import csv

import pytest

import extract
from app import config

VALID_TURTLE = (
    "@prefix crm: <https://example.org/sales-kg/> .\n"
    "<https://example.org/sales-kg/resource/Blocker_T001> a crm:Blocker .\n"
)


class _FakeResponse:
    def __init__(self, content):
        self._content = content
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def test_generate_posts_openrouter(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse("<turtle>")

    monkeypatch.setattr(extract.requests, "post", fake_post)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(config, "EXTRACT_MODEL", "meta/muse-spark-1.3-contributor")

    out = extract._generate("hi")

    assert out == "<turtle>"
    assert captured["url"] == config.OPENROUTER_URL
    assert captured["json"]["model"] == config.EXTRACT_MODEL
    assert "k" in captured["headers"]["Authorization"]


def test_generate_missing_key_raises(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    with pytest.raises(RuntimeError):
        extract._generate("hi")


def test_extract_loop_writes_ttl_and_failures(monkeypatch, tmp_path):
    # Minimal repo-root fixtures used by extract().
    prompt_template = (
        "ONTOLOGY\n{{ONTOLOGY\\_TTL}}\n"
        "CONTEXT\n{{CRM\\_CONTEXT}}\n"
        "id {{TRANSCRIPT\\_ID}} deal {{DEAL\\_ID}} account {{ACCOUNT\\_ID}} "
        "date {{ACTIVITY\\_DATE}} channel {{CHANNEL}}\n"
        "TRANSCRIPT\n{{TRANSCRIPT}}\n"
    )
    (tmp_path / "TranscriptRDFTurtleExtractionPrompt.md").write_text(prompt_template, encoding="utf-8")
    (tmp_path / "sales_kg_ontology_v1.ttl").write_text(
        "@prefix crm: <https://example.org/sales-kg/> .\n", encoding="utf-8"
    )
    (tmp_path / "kg.nt").write_text(
        "<https://example.org/sales-kg/resource/Deal_D001> "
        "<https://example.org/sales-kg/name> \"D001\" .\n",
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with open(data_dir / "transcripts.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "transcript_id",
                "deal_id",
                "account_id",
                "activity_date",
                "channel",
                "transcript",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "transcript_id": "T001",
                "deal_id": "D001",
                "account_id": "A001",
                "activity_date": "2024-01-01",
                "channel": "call",
                "transcript": "GOODTRANSCRIPT",
            }
        )
        writer.writerow(
            {
                "transcript_id": "T002",
                "deal_id": "D001",
                "account_id": "A001",
                "activity_date": "2024-01-02",
                "channel": "email",
                "transcript": "BADTRANSCRIPT",
            }
        )

    def fake_post(url, headers=None, json=None, timeout=None):
        prompt = json["messages"][0]["content"]
        if "GOODTRANSCRIPT" in prompt:
            return _FakeResponse(VALID_TURTLE)
        raise RuntimeError("OpenRouter error 500: boom")

    monkeypatch.setattr(extract, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(extract.requests, "post", fake_post)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "k")

    result = extract.extract(data_dir=data_dir)

    assert result["ok"] == ["T001"]
    assert result["failed"] == ["T002"]
    assert (data_dir / "extracted" / "T001.ttl").read_text(encoding="utf-8").strip() == VALID_TURTLE.strip()
    assert (data_dir / "extracted" / "failed" / "T002.txt").exists()


def test_extract_ids_filters_rows(monkeypatch, tmp_path):
    """A non-empty ``ids`` list extracts only those transcript_ids."""
    (tmp_path / "TranscriptRDFTurtleExtractionPrompt.md").write_text(
        "id {{TRANSCRIPT\\_ID}} body {{TRANSCRIPT}}\n", encoding="utf-8"
    )
    (tmp_path / "sales_kg_ontology_v1.ttl").write_text(
        "@prefix crm: <https://example.org/sales-kg/> .\n", encoding="utf-8"
    )
    (tmp_path / "kg.nt").write_text(
        "<https://example.org/sales-kg/resource/Deal_D1> "
        "<https://example.org/sales-kg/name> \"D1\" .\n",
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with open(data_dir / "transcripts.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "transcript_id",
                "deal_id",
                "account_id",
                "activity_date",
                "channel",
                "transcript",
            ],
        )
        writer.writeheader()
        for tid in ("T1", "T2", "T3"):
            writer.writerow(
                {
                    "transcript_id": tid,
                    "deal_id": "D1",
                    "account_id": "A1",
                    "activity_date": "2024-01-01",
                    "channel": "call",
                    "transcript": f"body {tid}",
                }
            )

    monkeypatch.setattr(extract, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(extract.requests, "post", lambda *a, **k: _FakeResponse(VALID_TURTLE))
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "k")

    result = extract.extract(data_dir=data_dir, ids=["T2"])

    assert result["ok"] == ["T2"]
    assert result["failed"] == []
    assert (data_dir / "extracted" / "T2.ttl").exists()
    assert not (data_dir / "extracted" / "T1.ttl").exists()
    assert not (data_dir / "extracted" / "T3.ttl").exists()
