FROM node:20-slim

WORKDIR /app

# Install gateway dependencies
COPY server/gateway/package*.json ./server/gateway/
RUN cd server/gateway && npm ci --omit=dev

# Copy shared types (gateway tsconfig references ../../shared/types)
COPY shared/ ./shared/

# Copy gateway source and build
COPY server/gateway/tsconfig.json ./server/gateway/
COPY server/gateway/src/ ./server/gateway/src/
RUN cd server/gateway && npx tsc -b

EXPOSE 8080

WORKDIR /app/server/gateway
CMD ["node", "dist/index.js"]
