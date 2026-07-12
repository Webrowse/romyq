"""Tests for multi-provider selection — wizard menu, back navigation, env writing."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from romyq import provider
from romyq.wizard_logic import write_env, PROVIDERS
from romyq.wizard_terminal import _select_provider


# ── provider.api_key() precedence ────────────────────────────────────────────

class TestApiKeyPrecedence:
    def test_planner_key_wins(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_PLANNER_API_KEY", "planner-key")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
        assert provider.api_key() == "planner-key"

    def test_deepseek_fallback(self, monkeypatch):
        monkeypatch.delenv("ROMYQ_PLANNER_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
        assert provider.api_key() == "deepseek-key"

    def test_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("ROMYQ_PLANNER_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert provider.api_key() == ""


# ── write_env per provider ────────────────────────────────────────────────────

class TestWriteEnv:
    def test_deepseek_writes_only_deepseek_key(self, tmp_path):
        write_env(str(tmp_path), "sk-deep", provider="deepseek")
        content = (tmp_path / ".env").read_text()
        assert "DEEPSEEK_API_KEY=sk-deep" in content
        assert "ROMYQ_PLANNER" not in content

    def test_openai_writes_planner_trio(self, tmp_path):
        write_env(str(tmp_path), "sk-oai", provider="openai")
        content = (tmp_path / ".env").read_text()
        assert "ROMYQ_PLANNER_API_KEY=sk-oai" in content
        assert "ROMYQ_PLANNER_BASE_URL=https://api.openai.com/v1" in content
        assert "ROMYQ_PLANNER_MODEL=gpt-4o-mini" in content
        assert "DEEPSEEK_API_KEY" not in content

    def test_custom_uses_supplied_endpoint(self, tmp_path):
        write_env(str(tmp_path), "sk-x", provider="custom",
                  base_url="https://llm.internal/v1", model="my-model")
        content = (tmp_path / ".env").read_text()
        assert "ROMYQ_PLANNER_BASE_URL=https://llm.internal/v1" in content
        assert "ROMYQ_PLANNER_MODEL=my-model" in content

    def test_updates_existing_lines_in_place(self, tmp_path):
        (tmp_path / ".env").write_text(
            "OTHER=1\nROMYQ_PLANNER_API_KEY=old\nROMYQ_PLANNER_BASE_URL=old-url\n"
        )
        write_env(str(tmp_path), "new-key", provider="openai")
        content = (tmp_path / ".env").read_text()
        assert "OTHER=1" in content
        assert "ROMYQ_PLANNER_API_KEY=new-key" in content
        assert "old-url" not in content
        assert content.count("ROMYQ_PLANNER_API_KEY=") == 1

    def test_providers_table_has_openai(self):
        assert "openai" in PROVIDERS
        assert PROVIDERS["deepseek"]["key_var"] == "DEEPSEEK_API_KEY"


# ── wizard provider menu ──────────────────────────────────────────────────────

def _drive(inputs: list[str], keys: list[str] | None = None):
    """Run _select_provider feeding scripted line and getpass inputs."""
    out = io.StringIO()
    lines = iter(inputs)
    keys_iter = iter(keys or [])

    def pr(*args, **kwargs):
        print(*args, file=out, **kwargs)

    result = _select_provider(
        pr, "-" * 10,
        lambda prompt: next(lines, ""),
        lambda prompt: next(keys_iter, ""),
    )
    return result, out.getvalue()


class TestProviderMenu:
    def test_deepseek_selection(self):
        (key, pid, base, model), out = _drive(["1"], keys=["sk-deep-123"])
        assert (key, pid) == ("sk-deep-123", "deepseek")
        assert "DeepSeek" in out

    def test_openai_selection(self):
        (key, pid, base, model), out = _drive(["2"], keys=["sk-oai-123"])
        assert (key, pid) == ("sk-oai-123", "openai")
        assert base == "https://api.openai.com/v1"

    def test_custom_selection(self):
        (key, pid, base, model), _ = _drive(
            ["3", "https://llm.internal/v1", "my-model"], keys=["sk-x"]
        )
        assert pid == "custom"
        assert base == "https://llm.internal/v1"
        assert model == "my-model"

    def test_configure_later(self):
        (key, pid, _, _), out = _drive(["4"])
        assert key == ""
        assert "local fallback" in out.lower()

    def test_back_from_key_prompt_reopens_menu(self):
        # Pick OpenAI, type 'b' at the key prompt, then pick DeepSeek.
        (key, pid, _, _), out = _drive(["2", "1"], keys=["b", "sk-deep-123"])
        assert (key, pid) == ("sk-deep-123", "deepseek")
        assert out.count("Provider") >= 2  # menu shown twice

    def test_back_from_custom_base_url(self):
        (key, pid, _, _), _ = _drive(["3", "b", "1"], keys=["sk-deep-123"])
        assert (key, pid) == ("sk-deep-123", "deepseek")

    def test_invalid_choice_reprompts(self):
        (key, pid, _, _), out = _drive(["9", "1"], keys=["sk-deep-123"])
        assert (key, pid) == ("sk-deep-123", "deepseek")
        assert "between 1 and" in out

    def test_empty_key_returns_configure_later_path(self):
        (key, pid, _, _), out = _drive(["1"], keys=[""])
        assert key == ""
        assert "No API key entered" in out
