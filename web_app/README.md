# iawwai frontend (React + Vite + Zustand)

High-contrast dark UI for case browsing and trade form editing.

## Stack

- React + Vite
- Zustand (state)
- Chakra UI
- Firebase Auth (email/password + Google)

## Run locally

```bash
npm install
npm run dev
```

Default frontend URL: `http://127.0.0.1:5173`

## Environment

Copy `.env.example` to `.env` and fill values.

### Required for backend calls

- `VITE_API_BASE_URL` (Cloud Run/FastAPI base URL)

### Required for Firebase auth

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_STORAGE_BUCKET`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_APP_ID`
- `VITE_FIREBASE_MEASUREMENT_ID` (optional)

If Firebase values are missing, app offers a local-dev bypass.

## Backend endpoints used

- `GET /v1/frontend/meta`
- `GET /v1/cases`
- `GET /v1/cases/{case_id}`
- `POST /v1/cases/{case_id}/trade`
- `POST /v1/cases/create`
- `POST /v1/cases/{case_id}/generate`
- `POST /v1/cases/{case_id}/upload-urls`
- `POST /v1/worker/capture/trigger`

## Case updates behavior

- On case navigation, frontend fetches case once.
- Realtime subscription (SSE) + backup polling starts **only** while generation state is `queued` or `running`.
- Once state becomes `completed` or `failed`, realtime subscription stops.

## Firebase setup checklist

1. Create Firebase project.
2. Enable Authentication methods:
   - Email/Password
   - Google
3. In Firebase Console -> Authentication -> Settings -> Authorized domains:
   - add `localhost`
   - add your deployed frontend domain
4. In Project settings -> General -> Your apps, create web app and copy SDK config into `web_app/.env`.
5. (Optional but recommended) Use Firebase custom claims + backend token verification for protected API access.

## Cloud Run / GCS checklist for this frontend

1. Set Cloud Run env:
   - `FRONTEND_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,https://<your-frontend-domain>`
   - `GCS_BUCKET=<bucket-name>`
   - `CAPTURE_WORKER_URL=<https://your-mac-worker/trigger-capture>`
   - `CAPTURE_WORKER_TOKEN=<shared-secret>` (optional but recommended)
   - `CAPTURE_WORKER_TIMEOUT_SECONDS=30`
   - provider/model envs as needed (`VISION_PROVIDER`, etc.)
2. Ensure Cloud Run service account has GCS permissions required for signed URLs and object read/write.
3. Bucket layout expected by frontend:
   - `cases/YYYY-MM-DD/{case_id}/proposal_validated.json`
   - `cases/YYYY-MM-DD/{case_id}/llm_raw_pass2.json`
   - `cases/YYYY-MM-DD/{case_id}/pass1_observations.json`
   - `cases/YYYY-MM-DD/{case_id}/liquidation_heatmap_observations.json`
   - `cases/YYYY-MM-DD/{case_id}/charts/{1m,5m,15m,30m,1h,4h}.png`
   - `cases/YYYY-MM-DD/{case_id}/charts/liquidation_heatmap.png`
   - `cases/YYYY-MM-DD/{case_id}/trade.json`

## Note about "Generate case"

Current UI flow creates case and calls Cloud Run `/v1/cases/{case_id}/generate`. That endpoint now triggers the configured capture worker URL.

### Local mac worker server

Run this on your mac host:

```bash
python -m pip install -r mac/agent_charts_screen/requirements.txt
uvicorn mac.agent_charts_screen.worker_server:app --host 0.0.0.0 --port 8090
```

Required env vars for mac worker process:

- `CAPTURE_WORKER_TOKEN` (if Cloud Run sends bearer token)
- `CAPTURE_LAYOUT_PATH` (defaults to `mac/agent_charts_screen/layout.json`)
- `AGENT_CHARTS_SIGNAL_BASE_URL` (Cloud Run API base URL the capture script should call)
