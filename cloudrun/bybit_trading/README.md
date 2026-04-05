# bybit_trading

Bybit v5 futures trading service — FastAPI + pybit SDK.

## Setup

```bash
cp .env.example .env
# fill BYBIT_API_KEY and BYBIT_API_SECRET
```

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash run_local.sh
# http://127.0.0.1:8081/docs
```

## Docker

```bash
# from repo root
docker build -f cloudrun/bybit_trading/Dockerfile -t bybit_trading .
docker run --env-file cloudrun/bybit_trading/.env -p 8081:8080 bybit_trading
```

## Deploy to Cloud Run

```bash
gcloud run deploy bybit-trading \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars BYBIT_API_KEY=...,BYBIT_API_SECRET=...,BYBIT_TESTNET=false
```

## Routes

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/health` | — | Health check |
| GET | `/v1/config` | — | Runtime config |
| GET | `/v1/market/futures/{symbol}` | — | Klines + orderbook + trades + ticker |
| GET | `/v1/market/overview/{symbol}` | — | Price, OI, funding, 24h stats |
| GET | `/v1/market/instrument/{symbol}` | — | Tick/lot size, leverage filters |
| GET | `/v1/stream/price/{symbol}` | — | SSE real-time ticker (WebSocket bridge) |
| GET | `/v1/radar/extreme-events` | — | Symbols with extreme price/volume moves |
| GET | `/v1/radar/negative-funding` | — | Symbols with extreme negative funding rate |
| GET | `/v1/radar/negative-funding/positions` | ✓ | Open positions on extreme-funding symbols |
| GET | `/v1/trade/balance` | ✓ | USDT wallet balance |
| GET | `/v1/trade/positions` | ✓ | Open positions |
| GET | `/v1/trade/orders` | ✓ | Open orders |
| POST | `/v1/trade/order` | ✓ | Place limit/market order with SL/TP |
| POST | `/v1/trade/sltp` | ✓ | Set SL/TP — entire position |
| POST | `/v1/trade/sltp/partial` | ✓ | Set SL/TP — partial qty |
| POST | `/v1/trade/close` | ✓ | Close full or partial position |
| DELETE | `/v1/trade/order/{order_id}` | ✓ | Cancel order |

## Key env vars

| Var | Default | Description |
|-----|---------|-------------|
| `BYBIT_API_KEY` | — | API key |
| `BYBIT_API_SECRET` | — | API secret |
| `BYBIT_TESTNET` | `false` | Use testnet |
| `BYBIT_CATEGORY` | `linear` | `linear` or `inverse` |
| `FRONTEND_CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated CORS origins |
| `RADAR_PRICE_CHANGE_PCT_THRESHOLD` | `3.0` | % move to flag as extreme |
| `RADAR_VOLUME_THRESHOLD_USDT` | `50000000` | 24h turnover threshold |
| `RADAR_FUNDING_RATE_THRESHOLD` | `-0.0005` | Funding rate floor |
| `PORT` | `8080` | Server port |

## SSE stream example

```js
const es = new EventSource('http://localhost:8081/v1/stream/price/BTCUSDT');
es.addEventListener('ticker', e => console.log(JSON.parse(e.data)));
es.addEventListener('heartbeat', e => console.log('ping', e.data));
```

## Place order example

```bash
curl -X POST http://localhost:8081/v1/trade/order \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"BTCUSDT","side":"Buy","orderType":"Limit","qty":"0.001","price":"80000","stopLoss":"79000","takeProfit":"85000"}'
```

## Close position example

```bash
# Full close (auto-detects size and side)
curl -X POST http://localhost:8081/v1/trade/close \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"BTCUSDT"}'

# Partial close
curl -X POST http://localhost:8081/v1/trade/close \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"BTCUSDT","qty":"0.001"}'
```
