"""The local model is optional. A bad reply does not change the book."""

import inspect
import json

import pytest

import recommender.brief as brief
from recommender.brief import BriefError, write_notes
from recommender.llm import ModelError, chat, configured


def test_a_json_reply_becomes_three_notes():
    def complete(messages):
        assert "share count" in messages[0]["content"]
        return json.dumps({"trend": "The sleeve is invested.", "cost": "The round trip is in the payload.", "news": "One headline was attached."})

    notes = write_notes({"cash_amount": 10}, {"total": 26}, headlines=["results"], complete=complete)
    assert set(notes) == {"trend", "cost", "news"}
    assert notes["trend"] == "The sleeve is invested."


def test_no_headlines_replaces_the_news_note():
    notes = write_notes({}, {}, complete=lambda messages: json.dumps({"trend": "Flat.", "cost": "Small.", "news": "Invented story."}))
    assert notes["news"] == "No headlines were attached."


def test_a_prose_reply_is_rejected():
    with pytest.raises(BriefError):
        write_notes({}, {}, complete=lambda messages: "Buy the dip.")


def test_the_brief_does_not_rebuild_the_book_or_call_a_broker():
    source = inspect.getsource(brief)
    assert "recommend(" not in source
    assert "shoonya" not in source


def test_an_unconfigured_model_never_opens_the_network(monkeypatch):
    monkeypatch.delenv("QWEN_MODEL", raising=False)
    monkeypatch.setattr("recommender.llm._request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    assert configured() is False
    with pytest.raises(BriefError, match="book does not need it"):
        write_notes({}, {})


def test_chat_reads_an_openai_style_body(monkeypatch):
    monkeypatch.setenv("QWEN_MODEL", "local")

    class _Body:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("recommender.llm.urllib.request.urlopen", lambda *args, **kwargs: _Body())
    assert chat([{"role": "user", "content": "ping"}]) == "hello"


def test_a_dead_server_is_a_model_error(monkeypatch):
    monkeypatch.setenv("QWEN_MODEL", "local")

    def _down(*args, **kwargs):
        raise TimeoutError("down")

    monkeypatch.setattr("recommender.llm.urllib.request.urlopen", _down)
    with pytest.raises(ModelError, match="unchanged"):
        chat([{"role": "user", "content": "ping"}])
