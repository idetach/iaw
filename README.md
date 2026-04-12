# chart-vision trading assistant (V1)

Monorepo with:

- `cloudrun/agent_charts_signal`: FastAPI service for case creation, signed uploads, 2-pass vision inference, strict validated trade proposal JSON, and case-file logging to GCS.
- `mac/agent_charts_screen`: macOS CLI scripts for layout calibration and capture/crop/resize/upload/analyze.
- `shared/chart_vision_common`: shared pydantic models + utilities.

## Fixed image contract

- 6 separate **color** chart images in this order:
  - `4h`, `1h`, `30m`, `15m`, `5m`, `1m`
- Each image must be **PNG 1308×768**.
- Crop to **chart area only** (no watchlist/chat/sidebar).

## Quickstart (local)

This repo uses **service-local** `.env` files for local development:

- `cloudrun/agent_charts_signal/.env`
- `mac/agent_charts_screen/.env`

### Run order (backend + worker + frontend)

1. Start backend API:
   - `./cloudrun/agent_charts_signal/run_local.sh`
2. Start mac capture worker:
   - `uvicorn mac.agent_charts_screen.worker_server:app --host 127.0.0.1 --port 8090`
3. Start frontend:
   - `cd web_app && npm run dev`

Then open `http://127.0.0.1:5173` and use **Generate case**.

### 1) Create Python env

Python 3.12 recommended.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
```

### 2) Run the Cloud Run service locally

```bash
pip install -r cloudrun/agent_charts_signal/requirements.txt
cp cloudrun/agent_charts_signal/.env.example cloudrun/agent_charts_signal/.env
./cloudrun/agent_charts_signal/run_local.sh
```

Notes:

- The service uses Application Default Credentials for GCS. Ensure one of:
  - `gcloud auth application-default login` (dev), or
  - `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`.

Service listens on `http://127.0.0.1:8080`.

### 2b) Run the Cloud Run service locally via Docker

This is the recommended way to match Cloud Run behavior.

Prereqs:

- Docker Desktop
- `gcloud auth application-default login` (so the container can sign GCS URLs)

Run:

```bash
docker compose up --build
```

### 3) Calibrate layout on macOS

This captures a screenshot and lets you draw 6 rectangles.

```bash
python -m pip install -r mac/agent_charts_screen/requirements.txt
cp mac/agent_charts_screen/.env.example mac/agent_charts_screen/.env
python mac/agent_charts_screen/calibrate_layout.py --out mac/agent_charts_screen/layout.json
```

If you want to capture the TradingView app window directly (recommended when you only have one screen), use:

```bash
python mac/agent_charts_screen/list_windows.py | less
python mac/agent_charts_screen/calibrate_layout.py \
  --window-owner TradingView \
  --out mac/agent_charts_screen/layout.json
```

Useful terminal commands for browser window/tab discovery (no AppleScript):

```bash
# 1) Full dump (paged)
python mac/agent_charts_screen/list_windows.py | less

# 2) Safari window titles (CoinGlass tab titles are usually in window_name)
python mac/agent_charts_screen/list_windows.py \
  | jq -r '.[] | select(.owner_name=="Safari") | .window_name'

# 3) One tab title per line from Safari window_name (comma-separated -> lines)
python mac/agent_charts_screen/list_windows.py \
  | jq -r '.[] | select(.owner_name=="Safari") | .window_name' \
  | tr ',' '\n' \
  | sed 's/^ *//'

# 4) Filter all browser windows quickly (Safari / Chrome / Arc / Brave)
python mac/agent_charts_screen/list_windows.py \
  | jq -r '.[] | select(.owner_name | test("Safari|Chrome|Arc|Brave"; "i")) | "\(.owner_name)\t\(.window_name)"' \
  | less -S

# 5) Search all browsers with "coinglass" in the title
python mac/agent_charts_screen/list_windows.py \
  | jq -r '.[] | select(.owner_name | test("Safari|Chrome|Arc|Brave"; "i")) | "\(.owner_name)\t\(.window_name)"' \
  | grep -i coinglass
```

### 4) Capture → upload → analyze

```bash
export AGENT_CHARTS_SIGNAL_BASE_URL="http://127.0.0.1:8080"
python mac/agent_charts_screen/capture_and_upload.py \
  --layout mac/agent_charts_screen/layout.json \
  --symbol BTCUSDT
```

You can override the capture window at runtime:

```bash
python mac/agent_charts_screen/capture_and_upload.py \
  --layout mac/agent_charts_screen/layout.json \
  --symbol BTCUSDT \
  --window-owner TradingView
```

```bash
python mac/agent_charts_screen/capture_and_upload.py \
  --per-tf-windows \
  --layout mac/agent_charts_screen/layout.json \
  --symbol BTCUSDT \
  --vision-provider gemini \
  --include-liquidation-heatmap \
  --liquidation-heatmap-window-owner Safari \
  --liquidation-heatmap-window-title "Liquidation Heatmap" \
  --liquidation-heatmap-refresh-wait-seconds 4 \
  --liquidation-heatmap-time-horizon-hours 24 \
  --http-timeout-seconds 300 \
  --debug-env
```

The script prints the validated JSON proposal.

## Cloud Run deployment

Build and deploy from `cloudrun/agent_charts_signal`.

The container listens on `$PORT` and runs `uvicorn agent_charts_signal.app.main:app`.

### Build

From repo root:

```bash
gcloud builds submit --tag gcr.io/$GOOGLE_CLOUD_PROJECT/agent-charts-signal
```

### Deploy

```bash
gcloud run deploy agent-charts-signal \
  --image gcr.io/$GOOGLE_CLOUD_PROJECT/agent-charts-signal \
  --region YOUR_REGION \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=YOUR_BUCKET,VISION_PROVIDER=claude \
  --set-secrets ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest
```

### Required env vars

- `GCS_BUCKET` (required)
- `VISION_PROVIDER` in `{claude,openai,gemini}` (default: `claude`)
- `ANTHROPIC_API_KEY` (required if `VISION_PROVIDER=claude`)

### Optional env vars

- `CASES_PREFIX` (default `cases`)
- `SIGNED_URL_TTL_SECONDS` (default `900`)
- `MAX_LEVERAGE` (default `10`)
- `MAX_MARGIN_PERCENT` (default `25`)
- `CLAUDE_MODEL_PASS1` (default `claude-opus-4-6`)
- `CLAUDE_MODEL_PASS2` (default `claude-opus-4-6`)

## Troubleshooting

- If signed uploads fail with 403:
  - Ensure the service account has `storage.objects.create` on the bucket.
  - Ensure the client uses `PUT` with `Content-Type: image/png`.
- If analyze fails with missing objects:
  - Verify the mac script uploaded all 6 images successfully.
- SSE:
  - Use `curl -N http://127.0.0.1:8080/v1/cases/stream` to observe status events.

- If `calibrate_layout.py` says `tkinter/_tkinter is not available`:
  - This commonly occurs with Homebrew `python@3.12` builds without Tk.
  - Options:
    - Use the **python.org** Python installer which includes tkinter, then recreate your venv.
    - Use the script's **manual calibration fallback** (no tkinter required): it will save a full screenshot and prompt you for `x,y,w,h` rectangles.
      - You can also provide rectangles non-interactively via:
        - `--rect 4h:x,y,w,h --rect 1h:x,y,w,h ...` (6 total)
      - And control the screenshot output path via `--screenshot-out`.
