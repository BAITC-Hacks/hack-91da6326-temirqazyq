"""Offline by construction: developer .env can never fund ordinary tests."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.setenv("AI_ALLOW_TEMPLATE_FALLBACK", "true")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("ALLOW_LIVE_AI_TESTS", "false")

    async def no_network(*args, **kwargs):
        raise AssertionError("Real HTTP requests are forbidden in ordinary pytest runs")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
    from app.main import _requests
    _requests.clear()
