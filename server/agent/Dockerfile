FROM python:3.12-slim

WORKDIR /app

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
