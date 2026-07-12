"""Tests for romyq.provider — planner client configuration and error mapping."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from romyq import provider
from romyq.provider import PlannerError


def _mock_response(content):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _http_response(status: int) -> httpx.Response:
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    return httpx.Response(status, request=req)


class TestConfiguration:
    def test_default_base_url(self, monkeypatch):
        monkeypatch.delenv("ROMYQ_PLANNER_BASE_URL", raising=False)
        assert provider.base_url() == "https://api.deepseek.com"

    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("ROMYQ_PLANNER_MODEL", raising=False)
        assert provider.model() == "deepseek-chat"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_BASE_URL", "https://example.com/v1")
        monkeypatch.setenv("ROMYQ_PLANNER_MODEL", "my-model")
        assert provider.base_url() == "https://example.com/v1"
        assert provider.model() == "my-model"

    def test_empty_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_BASE_URL", "")
        monkeypatch.setenv("ROMYQ_PLANNER_MODEL", "")
        assert provider.base_url() == "https://api.deepseek.com"
        assert provider.model() == "deepseek-chat"

    def test_invalid_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_TIMEOUT", "not-a-number")
        assert provider._timeout() == provider.DEFAULT_TIMEOUT_S

    def test_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_TIMEOUT", "42.5")
        assert provider._timeout() == 42.5

    def test_client_uses_configured_endpoint(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_BASE_URL", "https://example.com/v1")
        with patch("openai.OpenAI") as mock_openai:
            provider.client("sk-key")
        _, kwargs = mock_openai.call_args
        assert kwargs["base_url"] == "https://example.com/v1"
        assert kwargs["api_key"] == "sk-key"


class TestChat:
    def _patch_create(self, mock_openai, **kw):
        instance = mock_openai.return_value
        for k, v in kw.items():
            setattr(instance.chat.completions.create, k, v)
        return instance.chat.completions.create

    def test_returns_stripped_content(self):
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, return_value=_mock_response("  hello \n"))
            out = provider.chat("sk", [{"role": "user", "content": "hi"}])
        assert out == "hello"

    def test_passes_model_and_messages(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_MODEL", "custom-model")
        messages = [{"role": "user", "content": "hi"}]
        with patch("openai.OpenAI") as mock_openai:
            create = self._patch_create(mock_openai, return_value=_mock_response("x"))
            provider.chat("sk", messages, temperature=0.3)
        _, kwargs = create.call_args
        assert kwargs["model"] == "custom-model"
        assert kwargs["messages"] == messages
        assert kwargs["temperature"] == 0.3

    def test_auth_error_maps_to_planner_error(self):
        exc = openai.AuthenticationError(
            "bad key", response=_http_response(401), body=None
        )
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, side_effect=exc)
            with pytest.raises(PlannerError, match="API key"):
                provider.chat("sk", [])

    def test_connection_error_maps_to_planner_error(self):
        exc = openai.APIConnectionError(
            request=httpx.Request("POST", "https://api.deepseek.com")
        )
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, side_effect=exc)
            with pytest.raises(PlannerError, match="could not reach"):
                provider.chat("sk", [])

    def test_rate_limit_maps_to_planner_error(self):
        exc = openai.RateLimitError(
            "slow down", response=_http_response(429), body=None
        )
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, side_effect=exc)
            with pytest.raises(PlannerError, match="429"):
                provider.chat("sk", [])

    def test_empty_content_raises_planner_error(self):
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, return_value=_mock_response(None))
            with pytest.raises(PlannerError, match="empty"):
                provider.chat("sk", [])

    def test_no_choices_raises_planner_error(self):
        resp = MagicMock()
        resp.choices = []
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, return_value=resp)
            with pytest.raises(PlannerError, match="empty"):
                provider.chat("sk", [])

    def test_unexpected_exception_propagates(self):
        with patch("openai.OpenAI") as mock_openai:
            self._patch_create(mock_openai, side_effect=ValueError("bug"))
            with pytest.raises(ValueError):
                provider.chat("sk", [])
