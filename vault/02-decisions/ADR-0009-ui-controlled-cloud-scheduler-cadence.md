---
title: "ADR-0009: UI-controlled Cloud Scheduler tick cadence"
tags: [adr, cloud-run, cloud-scheduler, conductor, operations]
status: accepted
date: 2026-07-26
---

# ADR-0009: UI-controlled Cloud Scheduler tick cadence

## Status

Accepted. Builds on [[ADR-0006-runtime-settings-governance]] and
[[ADR-0008-cloud-run-service-to-service-auth]].

## Context

On Cloud Run the conductor's internal ticker is off (`TICK_INTERVAL_MINUTES=0`,
enforced by `deploy_conductor.sh`) because scale-to-zero would kill a background
loop. A Cloud Scheduler job (`conductor-tick`) drives ticks by calling
`POST /v1/loop/tick` on the schedule set in `deploy/setup_scheduler.sh`.

Changing the cadence therefore meant editing the scheduler job by hand
(`gcloud scheduler jobs update ...`) or re-running the setup script. The
conductor's runtime `tick_interval_minutes` setting in the UI only affects the
in-process ticker, which is disabled in the cloud — so the UI could not change
the real cloud cadence, which is confusing.

## Decision

Add an admin endpoint that edits the Cloud Scheduler job directly, and surface
it in the web_app settings UI as a distinct "Cloud tick cadence" control.

- `GET /v1/admin/scheduler` — returns the live job schedule, state, and a
  best-effort `interval_minutes` parsed from the cron.
- `POST /v1/admin/scheduler/interval` `{ "minutes": N }` — converts N to a cron
  expression (`*/N * * * *` for N<60, `0 */H * * *` for whole hours, `0 0 * * *`
  for daily) and updates the job's `schedule` field via the Cloud Scheduler API.

The Scheduler job is the single source of truth for cloud cadence; the endpoint
reads/writes it live and persists nothing locally (unlike behavioral settings in
ADR-0006, which persist to GCS).

### Auth & permissions

- No new auth layer: the conductor is private and reachable only through the
  `iaw-web` reverse proxy (Firebase-verified users) or the scheduler invoker SA
  (ADR-0008). The admin route rides that same boundary.
- The conductor's runtime service account needs `roles/cloudscheduler.admin`
  (the only predefined role that allows `cloudscheduler.jobs.update`).
  `deploy_conductor.sh` grants it and passes `GCP_PROJECT`,
  `SCHEDULER_LOCATION`, `SCHEDULER_JOB` as env vars. Empty project disables the
  feature and the endpoint returns `configured: false` (the UI hides the card).

## Consequences

- Positive: cadence is changed from the UI, no shell/redeploy; the internal
  ticker field and the cloud cadence are clearly separated in the UI.
- Positive: the scheduler stays authoritative, so there is no drift between a
  persisted setting and the actual job.
- Negative: broadens the conductor SA to `cloudscheduler.admin` (project-scoped);
  acceptable since the conductor is private and single-tenant. A custom role
  limited to `cloudscheduler.jobs.get/update` could tighten this later.
- Negative: cron granularity is coarse (every-N-minutes / whole hours / daily);
  arbitrary schedules still need `gcloud`.

## Alternatives considered

- **Persist cadence in GCS + a self-scheduling loop**: rejected — reintroduces
  the background-loop-on-scale-to-zero problem the scheduler exists to solve.
- **Keep manual `setup_scheduler.sh` only**: rejected — the whole point is
  UI control; the script remains the initial-provisioning path.

## Implementation references

- `cloudrun/conductor/conductor/app/scheduler.py` — the admin router.
- `cloudrun/conductor/conductor/app/config.py` — `gcp_project`,
  `scheduler_location`, `scheduler_job`.
- `cloudrun/conductor/conductor/app/main.py` — router registration.
- `cloudrun/conductor/requirements.txt` — `google-cloud-scheduler`.
- `web_app/src/pages/settings/ConductorTickSettings.jsx` — the UI card.
- `web_app/src/lib/api.js` — `getSchedulerInterval` / `setSchedulerInterval`.
- `deploy/deploy_conductor.sh` — env vars + `cloudscheduler.admin` grant.
