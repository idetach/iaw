from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_date_from_prefix(case_prefix: str) -> str | None:
    parts = case_prefix.split("/")
    if len(parts) < 3:
        return None
    return parts[-2]


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    as_str = str(value).strip()
    return as_str or None


def build_case_payload(*, case_id: str, case_prefix: str, artifacts: dict[str, Any]) -> dict[str, Any]:
    request_obj = artifacts.get("request.json") if isinstance(artifacts.get("request.json"), dict) else {}
    status_obj = artifacts.get("generate_status.json") if isinstance(artifacts.get("generate_status.json"), dict) else {}
    pass1_obj = artifacts.get("pass1_observations.json") if isinstance(artifacts.get("pass1_observations.json"), dict) else {}
    liq_obj = (
        artifacts.get("liquidation_heatmap_observations.json")
        if isinstance(artifacts.get("liquidation_heatmap_observations.json"), dict)
        else {}
    )
    proposal_obj = (
        artifacts.get("proposal_validated.json") if isinstance(artifacts.get("proposal_validated.json"), dict) else {}
    )
    trade_obj = artifacts.get("trade.json") if isinstance(artifacts.get("trade.json"), dict) else None

    symbol = _safe_str(request_obj.get("symbol") or pass1_obj.get("symbol") or liq_obj.get("symbol"))
    timestamp_utc = _safe_str(request_obj.get("timestamp_utc") or pass1_obj.get("timestamp_utc") or liq_obj.get("timestamp_utc"))
    run_id = f"{case_id}:{timestamp_utc or 'unknown'}"

    case_data = {
        "case_id": case_id,
        "gcs_prefix": case_prefix,
        "date": _normalize_date_from_prefix(case_prefix),
        "created_at": _safe_str(request_obj.get("created_at")),
        "updated_at": _iso_now(),
        "generation_state": _safe_str(status_obj.get("state")) or ("completed" if proposal_obj else "created"),
        "generation_detail": _safe_str(status_obj.get("detail")),
        "include_liquidation_heatmap": bool(request_obj.get("include_liquidation_heatmap", False)),
        "liquidation_horizon_hours": request_obj.get("liquidation_heatmap_time_horizon_hours"),
        "ingestion_updated_at": _iso_now(),
    }

    run_data = {
        "run_id": run_id,
        "case_id": case_id,
        "symbol": symbol,
        "timestamp_utc": timestamp_utc,
        "provider": _safe_str(request_obj.get("vision_provider")),
        "model_pass1": _safe_str(request_obj.get("vision_model_pass1")),
        "model_pass2": _safe_str(request_obj.get("vision_model_pass2")),
        "requested_at": _safe_str(status_obj.get("updated_at")) or _iso_now(),
        "started_at": None,
        "completed_at": _safe_str(status_obj.get("updated_at")) if proposal_obj else None,
        "status": case_data["generation_state"],
    }

    decision = None
    parameters: list[dict[str, Any]] = []
    rationale_tags: list[str] = []
    if proposal_obj:
        decision_id = f"{run_id}:decision"
        decision = {
            "decision_id": decision_id,
            "case_id": case_id,
            "run_id": run_id,
            "long_short_none": _safe_str(proposal_obj.get("long_short_none")),
            "confidence": proposal_obj.get("confidence"),
            "reason_entry": _safe_str(proposal_obj.get("reason_entry")) or "",
            "reason_abstain": _safe_str(proposal_obj.get("reason_abstain")) or "",
            "position_id": _safe_str(proposal_obj.get("position_id")) or f"{case_id}-position",
            "decision_timestamp": _safe_str(proposal_obj.get("timestamp")) or timestamp_utc,
            "model_used": _safe_str(proposal_obj.get("model_used")),
            "artifact_name": "proposal_validated.json",
            "artifact_path": f"{case_prefix}/proposal_validated.json",
        }

        parameter_names = [
            "target_price",
            "stop_loss",
            "leverage",
            "margin_percent",
            "entry_price_min",
            "entry_price_max",
            "entry_time_from",
            "entry_time_to",
            "exit_time_from",
            "exit_time_to",
            "position_duration",
            "position_strategy",
        ]
        for name in parameter_names:
            value = proposal_obj.get(name)
            if value is None:
                continue
            parameters.append(
                {
                    "parameter_id": f"{decision_id}:{name}",
                    "case_id": case_id,
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "name": name,
                    "value": value,
                    "value_type": type(value).__name__,
                    "unit": None,
                    "valid_from": timestamp_utc,
                    "valid_to": None,
                }
            )

        raw_tags = proposal_obj.get("rationale_tags")
        if isinstance(raw_tags, list):
            rationale_tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]

    observations: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    tf_rows = pass1_obj.get("observations") if isinstance(pass1_obj.get("observations"), list) else []
    for tf in tf_rows:
        if not isinstance(tf, dict):
            continue
        timeframe = _safe_str(tf.get("timeframe"))
        if not timeframe:
            continue
        obs_id = f"{run_id}:tf:{timeframe}"
        observations.append(
            {
                "obs_id": obs_id,
                "case_id": case_id,
                "run_id": run_id,
                "source_type": "timeframe_chart",
                "observed_at": timestamp_utc,
                "valid_from": timestamp_utc,
                "valid_to": None,
                "provider": run_data["provider"],
                "model": run_data["model_pass1"],
                "confidence": None,
                "artifact_name": "pass1_observations.json",
                "artifact_path": f"{case_prefix}/pass1_observations.json",
                "timeframe": timeframe,
                "regime": _safe_str(tf.get("regime")),
                "trend_dir": _safe_str(tf.get("trend_dir")),
                "vwap_state": _safe_str(tf.get("vwap_state")),
                "macd_state": _safe_str(tf.get("macd_state")),
                "key_levels": tf.get("key_levels") if isinstance(tf.get("key_levels"), list) else [],
                "notes": _safe_str(tf.get("notes")) or "",
                "warnings": pass1_obj.get("warnings") if isinstance(pass1_obj.get("warnings"), list) else [],
            }
        )
        for name in ["regime", "trend_dir", "vwap_state", "macd_state"]:
            value = _safe_str(tf.get(name))
            if not value:
                continue
            signals.append(
                {
                    "signal_id": f"{obs_id}:signal:{name}:{value}",
                    "obs_id": obs_id,
                    "name": name,
                    "value": value,
                    "numeric_value": None,
                    "unit": None,
                    "timeframe": timeframe,
                }
            )

    if liq_obj:
        obs_id = f"{run_id}:liq"
        observations.append(
            {
                "obs_id": obs_id,
                "case_id": case_id,
                "run_id": run_id,
                "source_type": "liquidation_heatmap",
                "observed_at": _safe_str(liq_obj.get("timestamp_utc")) or timestamp_utc,
                "valid_from": _safe_str(liq_obj.get("timestamp_utc")) or timestamp_utc,
                "valid_to": None,
                "provider": run_data["provider"],
                "model": run_data["model_pass1"],
                "confidence": None,
                "artifact_name": "liquidation_heatmap_observations.json",
                "artifact_path": f"{case_prefix}/liquidation_heatmap_observations.json",
                "time_horizon_hours": liq_obj.get("time_horizon_hours"),
                "liquidity_bias": _safe_str(liq_obj.get("liquidity_bias")),
                "key_liquidity_levels": liq_obj.get("key_liquidity_levels")
                if isinstance(liq_obj.get("key_liquidity_levels"), list)
                else [],
                "eta_summary": _safe_str(liq_obj.get("eta_summary")) or "",
                "notes": _safe_str(liq_obj.get("notes")) or "",
                "warnings": liq_obj.get("warnings") if isinstance(liq_obj.get("warnings"), list) else [],
            }
        )
        bias = _safe_str(liq_obj.get("liquidity_bias"))
        if bias:
            signals.append(
                {
                    "signal_id": f"{obs_id}:signal:liquidity_bias:{bias}",
                    "obs_id": obs_id,
                    "name": "liquidity_bias",
                    "value": bias,
                    "numeric_value": None,
                    "unit": None,
                    "timeframe": None,
                }
            )

    artifacts_out: list[dict[str, Any]] = []
    for artifact_name in sorted(artifacts.keys()):
        artifacts_out.append(
            {
                "case_id": case_id,
                "name": artifact_name,
                "gcs_path": f"{case_prefix}/{artifact_name}",
                "content_type": "application/json",
                "updated_at": _iso_now(),
                "checksum": None,
            }
        )

    text_chunks: list[dict[str, Any]] = []
    for obs in observations:
        notes = _safe_str(obs.get("notes"))
        if notes:
            text_chunks.append(
                {
                    "chunk_id": f"{obs['obs_id']}:notes",
                    "case_id": case_id,
                    "run_id": run_id,
                    "source": obs["source_type"],
                    "source_ref": obs["obs_id"],
                    "text": notes,
                    "kind": "observation",
                }
            )
        if obs.get("source_type") == "liquidation_heatmap":
            eta = _safe_str(obs.get("eta_summary"))
            if eta:
                text_chunks.append(
                    {
                        "chunk_id": f"{obs['obs_id']}:eta",
                        "case_id": case_id,
                        "run_id": run_id,
                        "source": obs["source_type"],
                        "source_ref": obs["obs_id"],
                        "text": eta,
                        "kind": "observation",
                    }
                )

    if decision:
        reason_entry = decision.get("reason_entry")
        if reason_entry:
            text_chunks.append(
                {
                    "chunk_id": f"{decision['decision_id']}:reason_entry",
                    "case_id": case_id,
                    "run_id": run_id,
                    "source": "decision",
                    "source_ref": decision["decision_id"],
                    "text": reason_entry,
                    "kind": "decision",
                }
            )
        reason_abstain = decision.get("reason_abstain")
        if reason_abstain:
            text_chunks.append(
                {
                    "chunk_id": f"{decision['decision_id']}:reason_abstain",
                    "case_id": case_id,
                    "run_id": run_id,
                    "source": "decision",
                    "source_ref": decision["decision_id"],
                    "text": reason_abstain,
                    "kind": "decision",
                }
            )

    influence_links: list[dict[str, Any]] = []
    support_links: list[dict[str, Any]] = []
    if decision:
        decision_id = decision["decision_id"]
        for obs in observations:
            support_links.append(
                {
                    "obs_id": obs["obs_id"],
                    "decision_id": decision_id,
                    "weight": 0.5,
                    "rationale_span": None,
                    "method": "bootstrap_uniform",
                }
            )
            for p in parameters:
                influence_links.append(
                    {
                        "obs_id": obs["obs_id"],
                        "parameter_id": p["parameter_id"],
                        "weight": 0.5,
                        "method": "bootstrap_uniform",
                    }
                )

    return {
        "symbol": symbol,
        "case": case_data,
        "run": run_data,
        "decision": decision,
        "parameters": parameters,
        "rationale_tags": rationale_tags,
        "observations": observations,
        "signals": signals,
        "text_chunks": text_chunks,
        "artifacts": artifacts_out,
        "trade": trade_obj,
        "support_links": support_links,
        "influence_links": influence_links,
    }
