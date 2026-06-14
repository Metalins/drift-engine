# Drift Engine dashboard — Next.js (standalone) for self-hosted docker-compose.
#
# Multi-stage build:
#   1. deps   — install all node_modules (incl. dev) for the build.
#   2. builder — `next build` with output: "standalone".
#   3. runner — minimal runtime image running `node server.js`.
#
# The dashboard talks to the API server over the docker network at
# http://server:8000 (DRIFT_ENGINE_API_URL). No build-time secrets — auth is
# all runtime (the server-minted JWT in the ml_session cookie).

# ---- deps ---------------------------------------------------------------- #
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ---- builder ------------------------------------------------------------- #
FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- runner -------------------------------------------------------------- #
FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Run as an unprivileged user.
RUN groupadd --system --gid 1001 nodejs \
  && useradd --system --uid 1001 --gid nodejs nextjs

# Standalone output bundles a minimal node_modules + server.js. Static assets
# and public/ have to be copied alongside it.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
