from __future__ import annotations

from conductor.app.cases import _derive_status, _item_from_case


def test_status_progression():
    assert _derive_status({}) == "queued"
    assert _derive_status({"snapshot": {}}) == "scanned"
    assert _derive_status({"snapshot": {}, "gate": {"plausible": False}}) == "gate_rejected"
    assert _derive_status({"snapshot": {}, "gate": {"plausible": True}}) == "gate_passed"
    assert (
        _derive_status({"gate": {"plausible": True}, "proposal": {"long_short_none": "NONE"}})
        == "abstained"
    )
    assert (
        _derive_status({"proposal": {"long_short_none": "LONG"}, "governor": {"action": "REJECT"}})
        == "gov_rejected"
    )
    assert (
        _derive_status({"governor": {"action": "RESIZE"}, "execution": {"placed": True}})
        == "executed"
    )
    assert _derive_status({"execution": {"placed": False}}) == "exec_failed"
    assert _derive_status({"error": "boom", "execution": {"placed": True}}) == "error"


def test_item_shape_matches_manual_case_list():
    case = {
        "symbol": "BTCUSDT",
        "tick_id": "tick-20260726T120000Z-abc123",
        "timestamp_utc": "2026-07-26T12:00:00+00:00",
        "source": "radar",
        "execution_mode": "demo",
        "snapshot": {},
        "gate": {"plausible": True},
        "proposal": {"long_short_none": "SHORT"},
        "governor": {"action": "APPROVE"},
        "execution": {"placed": True, "note": "Sell 0.01 @ 64000"},
    }
    item = _item_from_case("2026-07-26/tick-20260726T120000Z-abc123/BTCUSDT", case)
    assert item["symbol"] == "BTCUSDT"
    assert item["date"] == "2026-07-26"
    assert item["direction"] == "SHORT"
    assert item["status"] == "executed"
    assert item["executed"] is True
    assert item["model"] == "radar"  # source rendered in the small gray slot


def test_item_direction_none_hidden():
    item = _item_from_case("d/t/X", {"symbol": "X", "proposal": {"long_short_none": "NONE"}})
    assert item["direction"] is None
    assert item["status"] == "abstained"
