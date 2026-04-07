from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import Settings
from app.db import Database
from app.transforms import build_derived_metric_rows

CUTOFF_TIME = datetime(2026, 4, 6, 11, 37, 59, tzinfo=ZoneInfo("Europe/Helsinki"))
CUTOFF_DELTA = timedelta(minutes=45)
TARGET_METRICS = (
    "rolling_corr_price_vs_inventory_24h",
    "rolling_corr_price_vs_inventory_7d",
)
# backup dir is in gitignore
BACKUP_DIR = Path("/app/backups")


def _corr_points(settings: Settings) -> tuple[int, int]:
    corr_24h_points = max(2, round((24 * 60 * 60) / settings.inventory_poll_seconds))
    corr_7d_points = max(2, round((7 * 24 * 60 * 60) / settings.inventory_poll_seconds))
    return corr_24h_points, corr_7d_points


def _cutoff_utc() -> datetime:
    return CUTOFF_TIME.astimezone(UTC)


def _rewrite_cutoff_utc() -> datetime:
    return _cutoff_utc() + CUTOFF_DELTA


def _default_backup_file() -> Path:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return BACKUP_DIR / f"derived_metrics_corr_pre_20260406T083759Z_{ts}.json"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def backup_rows(db: Database, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    rows = db.fetch_all(
        """
        SELECT collected_at, asset, symbol, metric_name, metric_value, window_label, metadata
        FROM derived_metrics
        WHERE metric_name = ANY(%(metric_names)s)
          AND collected_at < %(cutoff)s
        ORDER BY collected_at, asset, symbol, metric_name, window_label
        """,
        {"metric_names": list(TARGET_METRICS), "cutoff": _cutoff_utc()},
    )
    payload = {
        "cutoff_time": CUTOFF_TIME.isoformat(),
        "cutoff_utc": _cutoff_utc().isoformat(),
        "rewrite_cutoff_utc": _rewrite_cutoff_utc().isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }
    output_file.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    print(f"backup_written file={output_file} rows={len(rows)}")


def restore_rows(db: Database, backup_file: Path) -> None:
    payload = json.loads(backup_file.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    if not rows:
        print(f"backup_empty file={backup_file}")
        return

    keys = [
        {
            "collected_at": row["collected_at"],
            "asset": row["asset"],
            "symbol": row["symbol"],
            "metric_name": row["metric_name"],
            "window_label": row["window_label"],
        }
        for row in rows
    ]

    delete_query = """
        DELETE FROM derived_metrics
        WHERE collected_at = %(collected_at)s
          AND asset IS NOT DISTINCT FROM %(asset)s
          AND symbol IS NOT DISTINCT FROM %(symbol)s
          AND metric_name = %(metric_name)s
          AND window_label = %(window_label)s
    """
    db.executemany(delete_query, keys)

    restored = []
    for row in rows:
        restored.append(
            {
                "collected_at": datetime.fromisoformat(row["collected_at"]),
                "asset": row["asset"],
                "symbol": row["symbol"],
                "metric_name": row["metric_name"],
                "metric_value": row["metric_value"],
                "window_label": row["window_label"],
                "metadata": row.get("metadata") or {},
            }
        )
    db.upsert_derived_metrics(restored)
    print(f"restore_complete file={backup_file} rows={len(restored)}")


def rewrite_rows(db: Database, settings: Settings) -> None:
    cutoff = _rewrite_cutoff_utc()
    existing_rows = db.fetch_all(
        """
        SELECT DISTINCT asset, symbol
        FROM derived_metrics
        WHERE metric_name = ANY(%(metric_names)s)
          AND collected_at < %(cutoff)s
          AND symbol IS NOT NULL
          AND asset IS NOT NULL
        ORDER BY asset, symbol
        """,
        {"metric_names": list(TARGET_METRICS), "cutoff": cutoff},
    )
    if not existing_rows:
        print("rewrite_nothing_to_do rows=0")
        return

    corr_24h_points, corr_7d_points = _corr_points(settings)
    rewritten_rows: list[dict] = []

    for pair in existing_rows:
        asset = pair["asset"]
        symbol = pair["symbol"]
        inventory_rows = db.fetch_all(
            """
            SELECT collected_at, available_inventory::double precision AS available_inventory
            FROM margin_available_inventory_snapshots
            WHERE asset = %(asset)s
              AND collected_at < %(cutoff)s
              AND collected_at >= %(cutoff)s - INTERVAL '14 days'
            ORDER BY collected_at ASC
            """,
            {"asset": asset, "cutoff": cutoff},
        )
        price_rows = db.fetch_all(
            """
            SELECT close_time AS collected_at, close::double precision AS close_price
            FROM spot_klines
            WHERE symbol = %(symbol)s
              AND close_time < %(cutoff)s
              AND close_time >= %(cutoff)s - INTERVAL '14 days'
            ORDER BY close_time ASC
            """,
            {"symbol": symbol, "cutoff": cutoff},
        )
        if not inventory_rows or not price_rows:
            continue

        import pandas as pd

        inv_df = pd.DataFrame(inventory_rows)
        inv_df["collected_at"] = pd.to_datetime(inv_df["collected_at"], utc=True)
        price_df = pd.DataFrame(price_rows)
        price_df["collected_at"] = pd.to_datetime(price_df["collected_at"], utc=True)
        merged = pd.merge_asof(
            inv_df.sort_values("collected_at"),
            price_df.sort_values("collected_at"),
            on="collected_at",
            direction="nearest",
            tolerance=pd.Timedelta("2h"),
        )
        merged = merged.dropna(subset=["close_price", "available_inventory"])
        points = merged.to_dict("records")
        if len(points) < 2:
            continue

        derived_rows = build_derived_metric_rows(
            asset=asset,
            symbol=symbol,
            points=points,
            corr_24h_points=corr_24h_points,
            corr_7d_points=corr_7d_points,
        )
        for row in derived_rows:
            if row["metric_name"] not in TARGET_METRICS:
                continue
            if row["collected_at"] >= cutoff:
                continue
            rewritten_rows.append(row)

    delete_query = """
        DELETE FROM derived_metrics
        WHERE metric_name = ANY(%(metric_names)s)
          AND collected_at < %(cutoff)s
    """
    db.execute(delete_query, {"metric_names": list(TARGET_METRICS), "cutoff": cutoff})
    if rewritten_rows:
        db.upsert_derived_metrics(rewritten_rows)
    print(
        "rewrite_complete "
        f"pairs={len(existing_rows)} rows_rewritten={len(rewritten_rows)} "
        f"corr_24h_points={corr_24h_points} corr_7d_points={corr_7d_points} cutoff_utc={cutoff.isoformat()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["backup", "rewrite", "restore"])
    parser.add_argument("--file", dest="file_path", default="")
    args = parser.parse_args()

    settings = Settings()
    db = Database(settings)

    if args.mode == "backup":
        backup_rows(db, Path(args.file_path) if args.file_path else _default_backup_file())
        return
    if args.mode == "restore":
        if not args.file_path:
            raise SystemExit("--file is required for restore")
        restore_rows(db, Path(args.file_path))
        return
    if args.mode == "rewrite":
        rewrite_rows(db, settings)
        return


if __name__ == "__main__":
    main()
