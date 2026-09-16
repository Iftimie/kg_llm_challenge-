"""Shared pytest fixtures for the API test suite.

The default suite must stay offline: no LLM, no GraphDB. Tests that need live
services opt in with ``pytestmark = pytest.mark.live`` (see ``pytest.ini``) and
request the ``live_guard`` fixture, which skips when a dependency is missing.
"""
import shutil

import pytest
import requests

from app import config


@pytest.fixture
def stub_env(monkeypatch):
    """Force the offline ``stub`` answerer for the duration of a test."""
    monkeypatch.setattr(config, "ANSWERER", "stub")
    return "stub"


def needs_live():
    """Skip the calling test unless every live dependency looks available."""
    if shutil.which("opencode") is None:
        pytest.skip("opencode binary not on PATH")
    if not config.OPENROUTER_API_KEY:
        pytest.skip("OPENROUTER_API_KEY not set")
    try:
        requests.get(config.GRAPHDB_URL, timeout=2)
    except Exception as exc:  # any failure means "GraphDB not up"
        pytest.skip(f"GraphDB not reachable at {config.GRAPHDB_URL}: {exc}")


@pytest.fixture
def live_guard():
    """Skip live tests when opencode, the key or GraphDB are unavailable."""
    needs_live()
