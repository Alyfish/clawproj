FROM node:20-slim

# better-sqlite3 needs build tools for native compilation
RUN apt-get update && apt-get install -y python3 make g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install gateway dependencies (need devDeps for tsc build, prune after)
COPY server/gateway/package*.json ./server/gateway/
RUN cd server/gateway && npm ci

# Copy shared types (gateway tsconfig references ../../shared/types)
COPY shared/ ./shared/

# Copy gateway source and build
COPY server/gateway/tsconfig.json ./server/gateway/
COPY server/gateway/src/ ./server/gateway/src/
COPY server/gateway/approvals/ ./server/gateway/approvals/
RUN cd server/gateway && npx tsc -b

# Prune devDeps after build
RUN cd server/gateway && npm prune --omit=dev

# Create data directory for SQLite
RUN mkdir -p /app/data

EXPOSE 8080

WORKDIR /app/server/gateway
ENV GATEWAY_DB_PATH=/app/data/gateway.db
CMD ["node", "dist/src/index.js"]
