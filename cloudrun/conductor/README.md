# conductor

Autonomous trading orchestrator. Runs the loop: candidates → indicator snapshot
→ Fable gate → Opus synthesis → **risk governor** → execution (demo-first) →
position lifecycle → reflection.

Design docs live in the vault: `vault/01-architecture/conductor-design.md`,
`vault/03-strategy/risk-governor-spec.md`, `vault/03-strategy/position-lifecycle-spec.md`.
Decisions: ADR-0001..0004.

## Safety model

- `EXECUTION_MODE` ∈ `shadow | demo | live` — **default `demo`** (ADR-0003).
  `shadow` logs intended orders without placing them.
- `LOOP_ENABLED=false` = kill switch: no new entries; open positions still managed.
- All risk rules are deterministic code in `governor.py` — never LLM-enforced.
- Positions always carry a stop; lifecycle only ever tightens stops.
- On portfolio-state failure the loop **blocks entries** (equity=0 fail-safe).

## Setup

```bash
cp .env.example .env
# fill ANTHROPIC_API_KEY, GCS_BUCKET, BYBIT_TRADING_URL
```

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash run_local.sh
# http://127.0.0.1:8084/docs
```

Trigger one tick:

```bash
curl -X POST http://127.0.0.1:8084/v1/loop/tick
```

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -v
```

## Docker

```bash
# from repo root
docker build -f cloudrun/conductor/Dockerfile -t conductor .
docker run --env-file cloudrun/conductor/.env -p 8084:8080 conductor
```

## Deploy to Cloud Run

```bash
gcloud run deploy conductor \
  --source . \
  --region <region> \
  --set-env-vars EXECUTION_MODE=demo,LOOP_ENABLED=true,BYBIT_TRADING_URL=... \
  --set-secrets ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest
```

Drive the loop with Cloud Scheduler → `POST /v1/loop/tick` every 5–15 minutes.

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/v1/config` | Runtime config incl. risk params |
| GET | `/v1/loop/status` | Loop mode, models, watchlist, kill-switch state |
| POST | `/v1/loop/enabled` | Runtime kill switch: `{"enabled": false}` halts new entries |
| POST | `/v1/loop/tick` | Run one full tick (idempotent per candle) |
| GET | `/v1/loop/tick/stream` | Run one tick, streaming per-phase SSE events (live UI) |
| GET | `/v1/cases` | List persisted cases from GCS (`limit`/`offset`) |
| GET | `/v1/cases/{date}/{tick_id}/{symbol}` | Full stored case artifact |

Note: the runtime kill switch is in-memory — run with `--max-instances=1`
(required anyway for one-decision-per-symbol semantics).

## Key env vars

| Var | Default | Description |
|-----|---------|-------------|
| `EXECUTION_MODE` | `demo` | `shadow` / `demo` / `live` |
| `LOOP_ENABLED` | `true` | Kill switch for new entries |
| `BYBIT_TRADING_URL` | `http://localhost:8081` | bybit_trading service |
| `MODEL_GATE` | `claude-fable-5` | Cheap pre-filter + monitoring tier |
| `MODEL_SYNTHESIS` | `claude-opus-5` | Entry/exit synthesis tier |
| `MODEL_REFLECTION` | `claude-opus-5` | Post-trade reflection tier |
| `WATCHLIST` | `BTCUSDT,ETHUSDT,SOLUSDT` | Base symbols |
| `TIMEFRAMES` | `4h,1h,30m,15m` | Snapshot timeframes |
| `RISK_FRACTION` | `0.0075` | Equity fraction risked per trade |
| `MAX_CONCURRENT_POSITIONS` | `4` | Portfolio gate |
| `MAX_AGGREGATE_OPEN_RISK` | `0.03` | Sum of at-stop risks / equity |
| `DAILY_LOSS_BREAKER_FRACTION` | `0.03` | Daily circuit breaker |
| `WEEKLY_LOSS_BREAKER_FRACTION` | `0.06` | Weekly circuit breaker |

## Scaffold status / TODO

- [x] Indicator engine (EMA/MACD/RSI/ATR/daily VWAP/swings/levels/regime)
- [x] Risk governor with risk-based sizing + audit log
- [x] Lifecycle decisions (break-even, ATR trail, invalidation, time exit)
- [x] Fable gate / Opus synthesis / reflection prompts
- [x] Realized PnL (daily/weekly) from closed-PnL for breakers
- [x] Symbol cooldown derived from recent closes (code rule, not LLM)
- [x] Persist cases to GCS under `cases-auto/{date}/{tick_id}/` (best-effort)
- [x] Optional LLM memory: `INCLUDE_RECENT_OUTCOMES` (off by default) appends
      the symbol's recent closed trades to Opus synthesis as context
- [ ] Reflection persistence → case_graph_analytics
- [ ] Opus escalation path in lifecycle
- [x] Bybit demo-trading toggle in bybit_trading (`BYBIT_DEMO=true`)
- [x] web_app Conductor page (status, kill switch, manual tick)
