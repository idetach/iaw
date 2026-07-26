from __future__ import annotations

import pytest
from fastapi import HTTPException

from conductor.app import runtime_settings as rs
from conductor.app.config import Settings


def make_settings(**overrides) -> Settings:
    base = dict(GCS_BUCKET="", EXECUTION_MODE="demo")
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_editable_and_guarded_disjoint():
    assert not set(rs.EDITABLE_FIELDS) & set(rs.GUARDED_FIELDS)


def test_apply_overrides_mutates_settings():
    s = make_settings()
    applied = rs.apply_overrides(s, {"model_gate": "claude-haiku-4-5-20251001"})
    assert applied == ["model_gate"]
    assert s.model_gate == "claude-haiku-4-5-20251001"


def test_guarded_field_never_applied():
    s = make_settings()
    before = s.risk_fraction
    applied = rs.apply_overrides(s, {"risk_fraction": 0.5})
    assert applied == []
    assert s.risk_fraction == before


def test_validate_rejects_live_mode():
    with pytest.raises(HTTPException) as exc:
        rs._validate("execution_mode", "live")
    assert exc.value.status_code == 422
    assert "go-live" in exc.value.detail


def test_validate_allows_shadow_and_demo():
    assert rs._validate("execution_mode", "shadow") == "shadow"
    assert rs._validate("execution_mode", "demo") == "demo"


def test_validate_confidence_bounds():
    assert rs._validate("min_confidence", "0.7") == pytest.approx(0.7)
    with pytest.raises(HTTPException):
        rs._validate("min_confidence", 1.5)


def test_validate_coerces_bool_strings():
    assert rs._validate("radar_enabled", "false") is False
    assert rs._validate("radar_enabled", "true") is True
    assert rs._validate("include_recent_outcomes", True) is True


def test_validate_positive_numbers():
    with pytest.raises(HTTPException):
        rs._validate("order_ttl_minutes", 0)
    assert rs._validate("order_ttl_minutes", "90") == pytest.approx(90.0)


def test_default_gate_is_one_tier_cheaper_than_synthesis():
    s = make_settings()
    # ADR-0005: gate must not default to the top-tier model
    assert s.model_gate == "claude-sonnet-5"
    assert s.model_synthesis == "claude-opus-5"
