"""
Cloud Scheduler admin (ADR-0009).

On Cloud Run the conductor's internal ticker is off (TICK_INTERVAL_MINUTES=0)
and a Cloud Scheduler job drives ticks via POST /v1/loop/tick. This router lets
the web_app change that job's cadence from the UI instead of re-running
deploy/setup_scheduler.sh, by editing the job's cron schedule through the Cloud
Scheduler API.

Auth: the conductor is private and reachable only through the iaw-web reverse
proxy (Firebase-verified users) or the scheduler invoker SA (ADR-0008), so no
extra auth is added here. The conductor's runtime service account needs
roles/cloudscheduler.admin to update the job.

The Scheduler job is the single source of truth for the cloud cadence; this
router reads/writes it live and persists nothing locally.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .config import Settings, get_settings

router = APIRouter(prefix="/v1/admin/scheduler", tags=["admin"])
_log = logging.getLogger("conductor.scheduler")


def _configured(s: Settings) -> bool:
    return bool(s.gcp_project and s.scheduler_location and s.scheduler_job)


def _cron_for_minutes(minutes: int) -> str:
    """Build a cron expression for an every-N-minutes cadence."""
    if minutes < 1:
        raise HTTPException(status_code=422, detail="minutes must be >= 1")
    if minutes < 60:
        return f"*/{minutes} * * * *"
    if minutes % 60 == 0 and minutes < 1440:
        return f"0 */{minutes // 60} * * *"
    if minutes == 1440:
        return "0 0 * * *"
    raise HTTPException(
        status_code=422,
        detail="minutes must be 1-59, a multiple of 60 up to 1440, or 1440 (daily)",
    )


def _minutes_from_cron(cron: str) -> int | None:
    """Best-effort inverse of _cron_for_minutes for display; None if not simple."""
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour = parts[0], parts[1]
    if hour == "*" and minute.startswith("*/"):
        try:
            return int(minute[2:])
        except ValueError:
            return None
    if minute == "0" and hour.startswith("*/"):
        try:
            return int(hour[2:]) * 60
        except ValueError:
            return None
    if minute == "0" and hour == "0":
        return 1440
    return None


def _client_and_name(s: Settings):
    from google.cloud import scheduler_v1  # deferred import

    client = scheduler_v1.CloudSchedulerClient()
    name = client.job_path(s.gcp_project, s.scheduler_location, s.scheduler_job)
    return client, name


def _map_google_error(exc: Exception) -> HTTPException:
    from google.api_core import exceptions as gexc  # deferred import

    if isinstance(exc, gexc.PermissionDenied):
        return HTTPException(
            status_code=403,
            detail=(
                "permission denied — grant roles/cloudscheduler.admin to the "
                "conductor's runtime service account (ADR-0009)"
            ),
        )
    if isinstance(exc, gexc.NotFound):
        return HTTPException(status_code=404, detail="scheduler job not found")
    return HTTPException(status_code=502, detail=f"cloud scheduler error: {exc}")


@router.get("")
def get_scheduler() -> dict:
    s = get_settings()
    if not _configured(s):
        return {
            "configured": False,
            "note": (
                "set GCP_PROJECT, SCHEDULER_LOCATION and SCHEDULER_JOB on the "
                "conductor to enable UI cadence control (ADR-0009)"
            ),
        }
    try:
        client, name = _client_and_name(s)
        job = client.get_job(name=name)
    except Exception as exc:  # noqa: BLE001 — mapped to HTTP below
        raise _map_google_error(exc)
    from google.cloud import scheduler_v1

    return {
        "configured": True,
        "job": s.scheduler_job,
        "location": s.scheduler_location,
        "schedule": job.schedule,
        "time_zone": job.time_zone,
        "state": scheduler_v1.Job.State(job.state).name,
        "interval_minutes": _minutes_from_cron(job.schedule),
    }


@router.post("/interval")
def set_scheduler_interval(body: dict) -> dict:
    s = get_settings()
    if not _configured(s):
        raise HTTPException(
            status_code=400,
            detail=(
                "cloud scheduler admin not configured — set GCP_PROJECT, "
                "SCHEDULER_LOCATION and SCHEDULER_JOB (ADR-0009)"
            ),
        )
    if "minutes" not in body:
        raise HTTPException(status_code=422, detail="body must include 'minutes'")
    try:
        minutes = int(body["minutes"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="minutes must be an integer")

    cron = _cron_for_minutes(minutes)

    try:
        from google.cloud import scheduler_v1
        from google.protobuf import field_mask_pb2

        client, name = _client_and_name(s)
        job = scheduler_v1.Job(name=name, schedule=cron)
        updated = client.update_job(
            job=job,
            update_mask=field_mask_pb2.FieldMask(paths=["schedule"]),
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — mapped to HTTP below
        raise _map_google_error(exc)

    _log.warning("cloud scheduler cadence updated to %s (%d min)", cron, minutes)
    return {
        "configured": True,
        "job": s.scheduler_job,
        "schedule": updated.schedule,
        "interval_minutes": _minutes_from_cron(updated.schedule),
    }
