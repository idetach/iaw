---
title: "ADR-0008: Cloud Run service-to-service authentication"
tags: [adr, cloud-run, security, authentication]
status: accepted
date: 2026-07-26
---

# ADR-0008: Cloud Run service-to-service authentication

## Status

Accepted.

## Context

The stack runs on Cloud Run with the following communication paths:

- **Browser → web_app**: public, no auth required.
- **Browser → conductor** (via `VITE_CONDUCTOR_URL`): needs access to `/v1/settings`, `/v1/loop/*`, `/v1/cases/*`, etc.
- **conductor → bybit_trading**: every tick fetches market data, portfolio state, and sends orders.
- **Cloud Scheduler → conductor**: invokes `POST /v1/loop/tick`.

Cloud Run services default to `--no-allow-unauthenticated`. Two problems appeared immediately after first deploy:

1. `conductor → bybit_trading` calls failed with Cloud Run `401 Unauthorized` because the caller had no Google identity token.
2. Passing the application-level shared secret (`BYBIT_TRADING_TOKEN`) in the `Authorization` header conflicted with Cloud Run IAM, which expects `Authorization: Bearer <google-id-token>`.

## Decision

Use **Google IAM identity tokens** for Cloud Run ingress authentication and move the application-level shared secret to a **custom header**.

### conductor → bybit_trading

- `bybit_trading` stays `--no-allow-unauthenticated`.
- `conductor` fetches a Google ID token for the `bybit_trading` service URL and sends it as `Authorization: Bearer <id_token>`.
- `conductor` sends `BYBIT_TRADING_TOKEN` as `X-Internal-Token`.
- `bybit_trading` middleware validates `X-Internal-Token`; `Authorization` is left for Cloud Run IAM.
- The conductor service account is granted `roles/run.invoker` on `bybit_trading`.
- Localhost URLs skip ID-token generation, so local dev continues to work with `X-Internal-Token` only.

### Browser → conductor (reverse proxy through `iaw-web`)

The `conductor` stays `--no-allow-unauthenticated`. Browsers cannot send a
Google identity token (and `EventSource` cannot send any header at all), so the
browser never calls the conductor directly. Instead the deployed `iaw-web`
service (public) runs a Node static server + reverse proxy:

```
Browser --(Firebase ID token)--> iaw-web /api/conductor/*   (public)
iaw-web --(Google ID token)-----> conductor                 (private, IAM)
```

Two auth layers:

1. **User auth** — `iaw-web` verifies the caller's Firebase ID token with
   `firebase-admin` before proxying. REST calls carry it in `Authorization`;
   SSE calls (`EventSource`) carry it as `?access_token=` since headers are not
   available. The proxy strips this before forwarding.
2. **Service auth** — `iaw-web` mints a Google identity token for the conductor
   URL and forwards it in `Authorization`. The `iaw-web` runtime service account
   is granted `roles/run.invoker` on the conductor.

Because the browser and API are same-origin (`/api/conductor/*`), CORS is
eliminated entirely, and SSE streams through unbuffered (Node `http-proxy`).

Chosen over API Gateway (which is the "purer" REST+JWT option) because the app
depends on SSE: ESPv2 buffers/times-out long-lived streams, and `EventSource`
cannot present a JWT at the gateway. Chosen over a public conductor because the
conductor must never be internet-reachable. Additional monthly cost: **$0** — it
reuses the already-deployed `iaw-web` service.

The build-time `VITE_CONDUCTOR_URL` is set to `/api/conductor` (same-origin);
the proxy target (`CONDUCTOR_URL`) and `FIREBASE_PROJECT_ID` are **runtime** env
vars, so the backend URL can change without a rebuild.

### Cloud Scheduler → conductor

`setup_scheduler.sh` already creates a dedicated service account and binds `roles/run.invoker` on the conductor service.

## Consequences

- Positive: neither `bybit_trading` nor `conductor` is exposed to the internet; both require Cloud Run IAM.
- Positive: the browser reaches the conductor same-origin, so CORS is eliminated and SSE streams natively.
- Positive: `$0` additional infrastructure — the proxy lives in the existing `iaw-web` service; the backend URL is a runtime var.
- Positive: local development is unaffected because ID tokens are only generated for `*.run.app` URLs.
- Negative: `iaw-web` is now a Node server instead of static nginx; user-token verification is a hard dependency on the request path.
- Negative: every new upstream service call from `conductor` must repeat the ID-token + custom-header pattern, and every new backend the browser needs must be added to the proxy.

## Implementation references

- `cloudrun/conductor/conductor/app/auth.py` — helper to fetch Cloud Run ID tokens.
- `cloudrun/conductor/conductor/app/market_data.py` — sends `Authorization` + `X-Internal-Token`.
- `cloudrun/conductor/conductor/app/loop.py` — `_bybit_headers()` helper used by get/delete/post callers.
- `cloudrun/bybit_trading/bybit_trading/app/main.py` — middleware validates `X-Internal-Token`.
- `web_app/server/server.js` — Node static server + Firebase-verifying, ID-token-injecting reverse proxy.
- `web_app/Dockerfile` — Node runtime stage replacing nginx.
- `web_app/src/lib/api.js` — attaches the Firebase token (header for REST, `access_token` query for SSE).
- `deploy/deploy_web_app.sh` — sets `CONDUCTOR_URL`/`FIREBASE_PROJECT_ID` and grants `iaw-web` SA `run.invoker`.
- `deploy/README.md` — IAM grant command and deploy order.
