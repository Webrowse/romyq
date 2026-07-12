"""Planning-provider client — the single place that knows connection details.

The planner defaults to DeepSeek but any OpenAI-compatible endpoint works.
Overridable per environment:

    ROMYQ_PLANNER_BASE_URL   default https://api.deepseek.com
    ROMYQ_PLANNER_MODEL      default deepseek-chat
    ROMYQ_PLANNER_TIMEOUT    seconds per request, default 600
"""
from __future__ import annotations

import os

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_S = 600.0

# Named providers the wizard offers. Any other OpenAI-compatible endpoint
# works via the ROMYQ_PLANNER_* variables ("custom" in the wizard).
KNOWN_PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek",
        "key_var": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_hint": "platform.deepseek.com",
    },
    "openai": {
        "label": "OpenAI",
        "key_var": "ROMYQ_PLANNER_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_hint": "platform.openai.com",
    },
}


class PlannerError(Exception):
    """A planner API call failed. The message is operator-facing."""


def api_key() -> str:
    """The planner API key: ROMYQ_PLANNER_API_KEY wins, DEEPSEEK_API_KEY is
    the backward-compatible fallback."""
    return os.getenv("ROMYQ_PLANNER_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""


def base_url() -> str:
    return os.getenv("ROMYQ_PLANNER_BASE_URL") or DEFAULT_BASE_URL


def model() -> str:
    return os.getenv("ROMYQ_PLANNER_MODEL") or DEFAULT_MODEL


def _timeout() -> float:
    try:
        return float(os.getenv("ROMYQ_PLANNER_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def client(api_key: str):
    import httpx
    from openai import OpenAI

    # Long read timeout for slow generations, short connect timeout so an
    # unreachable endpoint fails in seconds instead of hanging the loop.
    timeout = httpx.Timeout(_timeout(), connect=5.0)
    return OpenAI(api_key=api_key, base_url=base_url(), timeout=timeout)


def chat(api_key: str, messages: list[dict], **kwargs) -> str:
    """Run one chat completion and return the reply text.

    Maps API failures to PlannerError with an actionable message.  The
    OpenAI client already retries transient failures (connection errors,
    429s, 5xxs) twice before they surface here.
    """
    import openai

    try:
        response = client(api_key).chat.completions.create(
            model=model(), messages=messages, **kwargs
        )
    except openai.AuthenticationError as exc:
        raise PlannerError(
            "planner rejected the API key (HTTP 401) — check DEEPSEEK_API_KEY"
        ) from exc
    except openai.APIConnectionError as exc:
        raise PlannerError(f"could not reach the planner at {base_url()}: {exc}") from exc
    except openai.RateLimitError as exc:
        raise PlannerError(f"planner rate limit (HTTP 429): {exc}") from exc
    except openai.OpenAIError as exc:
        raise PlannerError(f"planner request failed: {exc}") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise PlannerError("planner returned an empty response")
    return content.strip()
