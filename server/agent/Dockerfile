FROM python:3.12-slim

WORKDIR /app

# Install system tools for bash-first agent (curl for SearXNG, jq for JSON parsing)
RUN apt-get update && apt-get install -y --no-install-recommends curl jq && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY server/agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server/ ./server/
COPY shared/ ./shared/
COPY SOUL.md .
COPY skills/ ./skills/

ENV PYTHONPATH=/app

CMD ["python", "-m", "server.agent.main"]
