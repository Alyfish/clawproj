FROM python:3.12-slim

WORKDIR /app

# Install system tools for bash-first agent (curl for SearXNG, jq for JSON parsing)
RUN apt-get update && apt-get install -y --no-install-recommends curl jq && rm -rf /var/lib/apt/lists/*

# Install gws CLI (Google Workspace CLI — native Rust binary from GitHub Releases)
ARG GWS_VERSION=v0.16.0
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
         amd64) GWS_TARGET="x86_64-unknown-linux-gnu" ;; \
         arm64) GWS_TARGET="aarch64-unknown-linux-gnu" ;; \
         *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/googleworkspace/cli/releases/download/${GWS_VERSION}/gws-${GWS_TARGET}.tar.gz" \
       | tar xz --strip-components=1 -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/gws \
    && gws --version

# Install Python dependencies
COPY server/agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server/ ./server/
COPY shared/ ./shared/
COPY SOUL.md .
COPY skills/ ./skills/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "server.agent.main"]
