"""Optional client for a local OpenAI-compatible chat server.

Nothing in the book calls this unless a page asks for a note. A missing
model name, a refused connection, or a bad reply leaves the share counts
where the engine put them.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://192.168.10.3:8998/v1"
TIMEOUT_SECONDS = 120


class ModelError(Exception):
    """The local server could not be used. The book is unchanged."""


def settings() -> dict[str, str]:
    return {
        "base_url": os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "model": os.environ.get("QWEN_MODEL", "").strip(),
        "api_key": os.environ.get("QWEN_API_KEY", "").strip(),
    }


def configured() -> bool:
    """True only when a model id is set. The default URL alone is not enough."""
    return bool(settings()["model"])


def reachable() -> bool:
    """True when GET /models on the configured server answers."""
    if not configured():
        return False
    try:
        _request("GET", "/models")
    except ModelError:
        return False
    return True


def chat(messages: list[dict[str, str]], timeout: int = TIMEOUT_SECONDS) -> str:
    """Send one chat completion and return the assistant text."""
    if not configured():
        raise ModelError("Set QWEN_MODEL when you want a note. The book does not need it.")
    payload = {
        "model": settings()["model"],
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 600,
    }
    try:
        body = _request("POST", "/chat/completions", payload, timeout=timeout)
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelError("The model reply did not include a message.") from exc


def _request(method: str, path: str, payload: dict | None = None, timeout: int = 10) -> dict:
    url = settings()["base_url"] + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = settings()["api_key"]
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ModelError(f"The model server returned {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ModelError("The model server was not reached. The book is unchanged.") from exc
