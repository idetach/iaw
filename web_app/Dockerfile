# web_app: Vite build -> nginx static serve (Cloud Run friendly, listens on $PORT)
FROM node:22-slim AS build
WORKDIR /app

# Vite env vars are BUILD-time — pass as build args (see deploy/deploy_web_app.sh)
ARG VITE_API_BASE_URL
ARG VITE_AGENT_TRADING_URL
ARG VITE_CONDUCTOR_URL
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_STORAGE_BUCKET
ARG VITE_FIREBASE_MESSAGING_SENDER_ID
ARG VITE_FIREBASE_APP_ID
ARG VITE_FIREBASE_MEASUREMENT_ID
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_AGENT_TRADING_URL=$VITE_AGENT_TRADING_URL \
    VITE_CONDUCTOR_URL=$VITE_CONDUCTOR_URL \
    VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY \
    VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN \
    VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID \
    VITE_FIREBASE_STORAGE_BUCKET=$VITE_FIREBASE_STORAGE_BUCKET \
    VITE_FIREBASE_MESSAGING_SENDER_ID=$VITE_FIREBASE_MESSAGING_SENDER_ID \
    VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID \
    VITE_FIREBASE_MEASUREMENT_ID=$VITE_FIREBASE_MEASUREMENT_ID

COPY web_app/package.json web_app/package-lock.json* ./
RUN npm ci || npm install
COPY web_app/ ./
RUN npm run build

# Runtime: Node static server + authenticated reverse proxy to the private
# conductor (ADR-0008). CONDUCTOR_URL / FIREBASE_PROJECT_ID are RUNTIME env vars.
FROM node:22-slim AS runtime
WORKDIR /app
COPY web_app/server/package.json web_app/server/package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY web_app/server/server.js ./
COPY --from=build /app/dist ./dist
ENV PORT=8080
EXPOSE 8080
CMD ["node", "server.js"]
