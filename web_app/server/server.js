/**
 * iaw-web runtime server (ADR-0008).
 *
 * Serves the built SPA and reverse-proxies /api/conductor/* to the PRIVATE
 * conductor Cloud Run service. This keeps the conductor
 * `--no-allow-unauthenticated` while letting the browser reach it same-origin:
 *
 *   Browser --(Firebase ID token)--> iaw-web /api/conductor/*  (public)
 *   iaw-web --(Google ID token)-----> conductor                (private, IAM)
 *
 * Two auth layers:
 *   1. User auth:   the browser's Firebase ID token is verified here
 *      (Authorization: Bearer <token> for REST, ?access_token=<token> for SSE
 *      since EventSource cannot set headers).
 *   2. Service auth: this server mints a Google ID token for the conductor URL
 *      (Cloud Run IAM). This server's service account needs roles/run.invoker.
 *
 * SSE endpoints stream through http-proxy unbuffered.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import express from "express";
import admin from "firebase-admin";
import httpProxy from "http-proxy";
import { GoogleAuth } from "google-auth-library";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT = process.env.PORT || 8080;
const CONDUCTOR_URL = (process.env.CONDUCTOR_URL || "").replace(/\/$/, "");
const FIREBASE_PROJECT_ID = process.env.FIREBASE_PROJECT_ID || "";
// When true, user Firebase tokens are verified before proxying. Disable only
// for local debugging; never in production.
const VERIFY_USERS = (process.env.VERIFY_USERS || "true").toLowerCase() !== "false";
const DIST_DIR = path.join(__dirname, "dist");
const PROXY_PREFIX = "/api/conductor";

if (!CONDUCTOR_URL) {
  console.error("FATAL: CONDUCTOR_URL env var is required");
  process.exit(1);
}

if (VERIFY_USERS) {
  admin.initializeApp({
    credential: admin.credential.applicationDefault(),
    projectId: FIREBASE_PROJECT_ID || undefined,
  });
}

// --- Google ID token for the conductor (Cloud Run IAM) ----------------------
// getIdTokenClient caches the token and refreshes it automatically.
const auth = new GoogleAuth();
let idTokenClient = null;
async function conductorAuthHeader() {
  if (!idTokenClient) {
    idTokenClient = await auth.getIdTokenClient(CONDUCTOR_URL);
  }
  const headers = await idTokenClient.getRequestHeaders();
  return headers.Authorization || headers.authorization;
}

// --- Firebase user verification --------------------------------------------
function extractUserToken(req) {
  const header = req.headers.authorization || "";
  if (header.startsWith("Bearer ")) return header.slice(7).trim();
  // EventSource (SSE) cannot set headers — accept a query param instead.
  if (typeof req.query.access_token === "string") return req.query.access_token;
  return "";
}

async function verifyUser(req) {
  if (!VERIFY_USERS) return true;
  const token = extractUserToken(req);
  if (!token) return false;
  try {
    await admin.auth().verifyIdToken(token);
    return true;
  } catch (err) {
    console.warn("Firebase token verification failed:", err.message);
    return false;
  }
}

// --- Reverse proxy ----------------------------------------------------------
const proxy = httpProxy.createProxyServer({
  target: CONDUCTOR_URL,
  changeOrigin: true,
  xfwd: true,
  // Do not buffer: required for Server-Sent Events to stream in real time.
  buffer: undefined,
  proxyTimeout: 0,
  timeout: 0,
});

proxy.on("error", (err, _req, res) => {
  console.error("proxy error:", err.message);
  if (res && !res.headersSent && typeof res.writeHead === "function") {
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "bad_gateway", detail: err.message }));
  }
});

const app = express();
app.disable("x-powered-by");

app.get("/healthz", (_req, res) => res.json({ status: "ok" }));

// Authenticated proxy for the conductor. No body parsers before this — the raw
// request stream (incl. POST bodies and SSE) is piped straight through.
app.use(PROXY_PREFIX, async (req, res) => {
  const ok = await verifyUser(req);
  if (!ok) {
    res.status(401).json({ error: "unauthorized", detail: "missing or invalid user token" });
    return;
  }

  let authHeader;
  try {
    authHeader = await conductorAuthHeader();
  } catch (err) {
    console.error("could not mint conductor ID token:", err.message);
    res.status(502).json({ error: "bad_gateway", detail: "identity token unavailable" });
    return;
  }

  // Under app.use(PROXY_PREFIX, ...) Express already strips the mount prefix
  // from req.url, so it is the conductor's native path (e.g. /v1/loop/status).
  // Replace the browser's Firebase token with the Cloud Run identity token.
  req.headers.authorization = authHeader;
  // Drop the SSE query-param token so it never reaches the backend/logs.
  if (req.query.access_token) {
    const u = new URL(req.url, "http://placeholder");
    u.searchParams.delete("access_token");
    req.url = u.pathname + (u.search || "");
  }

  proxy.web(req, res);
});

// --- Static SPA -------------------------------------------------------------
app.use(
  express.static(DIST_DIR, {
    setHeaders: (res, filePath) => {
      if (/\.(js|css|png|svg|ico|woff2?)$/.test(filePath)) {
        res.setHeader("Cache-Control", "public, max-age=604800");
      }
    },
  })
);

// SPA fallback: any non-asset, non-api route returns index.html.
app.get("*", (_req, res) => {
  res.sendFile(path.join(DIST_DIR, "index.html"));
});

app.listen(PORT, () => {
  console.log(`iaw-web serving on :${PORT}`);
  console.log(`proxying ${PROXY_PREFIX}/* -> ${CONDUCTOR_URL} (verify_users=${VERIFY_USERS})`);
});
