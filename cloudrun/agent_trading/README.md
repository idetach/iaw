# agent_trading

Trade execution layer. Reads proposals from GCS, places orders via `bybit_trading`, persists results.

## Dependencies

Requires `bybit_trading` service to be running and reachable at `BYBIT_TRADING_URL`.

## Setup

```bash
cp .env.example .env
# fill GCS_BUCKET, BYBIT_TRADING_URL
```

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash run_local.sh
# http://127.0.0.1:8082/docs
```

## Docker

```bash
# from repo root
docker build -f cloudrun/agent_trading/Dockerfile -t agent_trading .
docker run --env-file cloudrun/agent_trading/.env -p 8082:8080 agent_trading
```

## Deploy to Cloud Run

```bash
gcloud run deploy agent-trading \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=...,CASES_PREFIX=cases,BYBIT_TRADING_URL=https://bybit-trading-xxx.run.app
```

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/v1/config` | Runtime config |
| POST | `/v1/trader/cases/{case_id}/execute` | Auto-place order from `proposal_validated.json` |
| POST | `/v1/trader/cases/{case_id}/manual` | Manual order from trade form |
| GET | `/v1/trader/cases/{case_id}/trade` | Read saved `trade.json` |

## Key env vars

| Var | Default | Description |
|-----|---------|-------------|
| `GCS_BUCKET` | — | GCS bucket (same as agent_charts_signal) |
| `CASES_PREFIX` | `cases` | GCS prefix for cases |
| `BYBIT_TRADING_URL` | `http://localhost:8081` | bybit_trading service URL |
| `BYBIT_TRADING_TOKEN` | — | Optional bearer token for bybit_trading |
| `BYBIT_TRADING_TIMEOUT` | `30.0` | Request timeout (seconds) |
| `FRONTEND_CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated CORS origins |
| `PORT` | `8082` | Server port |

## Execute from proposal example

```bash
curl -X POST http://localhost:8082/v1/trader/cases/abc123/execute \
  -H 'Content-Type: application/json' \
  -d '{"orderType":"Limit","setLeverage":true}'
```

Auto-calculates qty from `balance × margin_percent% × leverage / entry_price`.  
Override qty explicitly:

```bash
curl -X POST http://localhost:8082/v1/trader/cases/abc123/execute \
  -H 'Content-Type: application/json' \
  -d '{"orderType":"Market","qty":"0.01","setLeverage":false}'
```

## Manual trade example

```bash
curl -X POST http://localhost:8082/v1/trader/cases/abc123/manual \
  -H 'Content-Type: application/json' \
  -d '{
    "symbol": "BTCUSDT",
    "side": "Buy",
    "orderType": "Limit",
    "qty": "0.001",
    "price": "80000",
    "stopLoss": "79000",
    "takeProfit": "85000",
    "leverage": 10
  }'
```

## Architecture

```
Frontend
  └──▶ agent_trading  (this service)
            │ reads proposal from GCS
            │ writes trade.json to GCS
            └──▶ bybit_trading  (order execution)
                      └──▶ Bybit v5 API

Future expansions in this service:
  Bybit webhooks  →  POST /webhook/bybit
  Strategy runner →  background loop
```
