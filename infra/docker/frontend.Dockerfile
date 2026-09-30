# syntax=docker/dockerfile:1
# Next.js frontend served by `next start` (compose profile "full").
#   docker compose -f infra/compose/compose.yaml --profile full up -d --wait
#
# NEXT_PUBLIC_API_URL is inlined into the client bundle at build time; the browser calls the
# API directly, so it must be the API address as seen from the host (http://localhost:<API_PORT>).

ARG NODE_IMAGE=node:24-bookworm-slim

# --- dependencies (frontend/.npmrc keeps engine-strict, so NODE_IMAGE must satisfy engines.node)
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund

# --- production build ---------------------------------------------------------------------
FROM ${NODE_IMAGE} AS build
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build \
    && npm prune --omit=dev --no-audit --no-fund

# --- runtime ------------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=build --chown=node:node /app/package.json /app/next.config.js ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
USER node
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
