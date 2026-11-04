FROM python:3.12-slim

# Pinned to the combination the rest of the MCP fleet runs:
# mcp-proxy 0.14+ validates the Host header (HTTP 421 behind a reverse proxy) unless --allowed-host is set.
RUN pip install --no-cache-dir "mcp-proxy==0.13.0" "mcp==1.30.0"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV EARLYON_DB_PATH=/data/earlyon.db \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 3000

# stdio MCP server wrapped by mcp-proxy -> streamable HTTP at :3000/mcp.
# --pass-environment: without it the child only sees a minimal env and ignores EARLYON_* settings.
CMD ["mcp-proxy", "--port", "3000", "--host", "0.0.0.0", "--pass-environment", "--", "earlyon-mcp", "serve"]
