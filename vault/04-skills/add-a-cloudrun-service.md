---
title: "Skill: Add a Cloud Run service"
tags: [skill]
updated: 2026-07-25
---

# Skill: Add a Cloud Run service (the iaw way)

Use when adding a new backend service (e.g. `cloudrun/conductor`). Match the
existing `cloudrun/agent_trading` and `cloudrun/bybit_trading` layout exactly.

## Steps

1. **Scaffold** under `cloudrun/<name>/<name>/app/`:
   - `main.py` — FastAPI app, CORS from settings, `/health`, `/v1/config`,
     global exception handler, include routers.
   - `config.py` — `pydantic-settings` `Settings`; `get_settings()` cached.
   - routers per concern (e.g. `loop.py`, `governor.py`, `indicators.py`).
2. **Env**: add `.env.example` with every setting documented. Never commit real
   secrets. Reuse shared vars (`GCS_BUCKET`, `CASES_PREFIX`, `BYBIT_*`).
3. **Ops scripts**: `run_local.sh` (uvicorn on a distinct port) and `start.sh`
   (container entrypoint on `$PORT`).
4. **Dockerfile** under `cloudrun/<name>/Dockerfile`, building from repo root so
   `shared/` is importable.
5. **README.md**: routes table, env-var table, run/deploy commands — same shape as
   the other services.
6. **Tests**: add `tests/` with pure-function unit tests (see
   `grafana/metrics_margin/tests` for the pattern).
7. **Wire shared**: import `chart_vision_common` models rather than redefining.
8. **Deploy**: `gcloud run deploy <name> --source . --region <region>` with env
   vars; keep `EXECUTION_MODE=demo` default for any trading path.
9. **Document**: add an ADR if the service introduces a new pattern; link it from
   [[system-overview]] and [[reusable-modules]].

## Definition of done
Health check passes locally and on Cloud Run; `/v1/config` echoes settings; README
routes match reality; tests green; no secrets committed.
