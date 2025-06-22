FROM python:3.13-slim

# Install required system packages and uv
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    pip install --no-cache-dir uv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files for layer caching
COPY pyproject.toml uv.lock /app/

# Copy source code
COPY src /app/src

# Accept GH_TOKEN for private repo install
ARG GH_TOKEN
ENV GH_TOKEN=${GH_TOKEN}

# Install dependencies using uv
RUN uv sync

# Create non-root user and set permissions
RUN adduser --system --group --home /home/app app && \
    chown -R app:app /app

ENV HOME=/home/app
USER app

EXPOSE 8005

ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=streamable-http
ENV CSV_SOURCES_CONFIG_PATH=/app/src/upphandlat_mcp/csv_sources.yaml

CMD ["uv", "run", "-m", "uvicorn", "upphandlat_mcp.server:app", "--host", "0.0.0.0", "--port", "8005"]
