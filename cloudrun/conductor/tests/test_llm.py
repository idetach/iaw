from __future__ import annotations

from types import SimpleNamespace

import pytest

from conductor.app import llm
from conductor.app.config import Settings


def make_settings() -> Settings:
    return Settings(_env_file=None, GCS_BUCKET="test", ANTHROPIC_API_KEY="test-key")


class FakeClient:
    """Returns queued responses; records the max_tokens of each call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[int] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, max_tokens, system, messages):
        self.calls.append(max_tokens)
        return self._responses.pop(0)


def resp(text: str, stop_reason: str = "end_turn"):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def test_extract_json_plain_and_fenced():
    assert llm._extract_json('{"a": 1}') == {"a": 1}
    assert llm._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm._extract_json('noise before {"a": 1} after') == {"a": 1}
    with pytest.raises(ValueError):
        llm._extract_json("")


def test_call_retries_on_truncation_with_bigger_budget(monkeypatch):
    fake = FakeClient(
        [
            resp('{"plausible": false, "setup_hint": "cut of', stop_reason="max_tokens"),
            resp('{"plausible": true, "setup_hint": "ok", "reject_reason": ""}'),
        ]
    )
    monkeypatch.setattr(llm, "_client", lambda s: fake)
    out = llm._call(make_settings(), model="m", system="s", user="u", max_tokens=300)
    assert out["plausible"] is True
    assert fake.calls == [300, 1200]  # retried with 4x budget


def test_call_retries_on_empty_output(monkeypatch):
    fake = FakeClient(
        [
            resp("", stop_reason="max_tokens"),  # thinking ate the whole budget
            resp('{"ok": 1}'),
        ]
    )
    monkeypatch.setattr(llm, "_client", lambda s: fake)
    out = llm._call(make_settings(), model="m", system="s", user="u", max_tokens=300)
    assert out == {"ok": 1}
    assert fake.calls == [300, 1200]


def test_call_raises_after_failed_retry(monkeypatch):
    fake = FakeClient(
        [
            resp("", stop_reason="max_tokens"),
            resp("still not json", stop_reason="end_turn"),
        ]
    )
    monkeypatch.setattr(llm, "_client", lambda s: fake)
    with pytest.raises(ValueError, match="unparseable"):
        llm._call(make_settings(), model="m", system="s", user="u", max_tokens=300)


def test_gate_failure_is_not_a_pass(monkeypatch):
    """A gate error must resolve to plausible=False — never default-pass."""
    def boom(settings, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(llm, "_call", boom)
    from conductor.app.models import IndicatorSnapshot
    from datetime import datetime, timezone

    snap = IndicatorSnapshot(
        symbol="BTCUSDT", timestamp_utc=datetime.now(timezone.utc), timeframes=[]
    )
    out = llm.gate(make_settings(), snap)
    assert out["plausible"] is False
    assert "gate_error" in out["reject_reason"]
