"""Three research notes beside a book the engine already sized.

The model may comment. It may not change a share count, and this module
does not call the broker or rebuild the book. With no model configured,
`write_notes` fails before any network call.
"""

from __future__ import annotations

import json

from recommender.llm import ModelError, chat

_KEYS = ("trend", "cost", "news")


class BriefError(Exception):
    """The note could not be read. The book is unchanged."""


def write_notes(
    book: dict,
    trip: dict,
    mix: dict | None = None,
    headlines: list[str] | None = None,
    complete=None,
) -> dict[str, str]:
    """Ask for trend, cost, and news notes. `complete` is the chat function."""
    payload = {
        "book": book,
        "round_trip": trip,
        "holdings_mix": mix,
        "headlines": list(headlines or []),
    }
    messages = [
        {"role": "system", "content": _instruction(bool(payload["headlines"]))},
        {"role": "user", "content": json.dumps(payload, default=str)},
    ]
    speaker = complete or _complete
    try:
        raw = speaker(messages)
    except ModelError as exc:
        raise BriefError(str(exc)) from exc
    return _parse(raw, payload["headlines"])


def _instruction(has_headlines: bool) -> str:
    lines = [
        "Write three short research notes.",
        "Use only numbers that appear in the payload.",
        "Do not change a share count, a weight, a stop, or an action.",
        "Do not tell the reader to place an order.",
        "Reply with a JSON object and nothing else.",
        "The keys are trend, cost, and news. Each value is one or two sentences.",
    ]
    if not has_headlines:
        lines.append("No headlines were attached. The news value must say that.")
    return " ".join(lines)


def _complete(messages: list[dict[str, str]]) -> str:
    return chat(messages)


def _parse(raw: str, headlines: list[str]) -> dict[str, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise BriefError("The model reply was not the expected note. The book is unchanged.")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise BriefError("The model reply was not the expected note. The book is unchanged.") from exc
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in _KEYS):
        raise BriefError("The model reply was not the expected note. The book is unchanged.")
    notes = {key: payload[key].strip() for key in _KEYS}
    if not headlines:
        notes["news"] = "No headlines were attached."
    return notes
