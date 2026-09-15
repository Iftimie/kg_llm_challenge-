# Sales Intelligence demo container.
#
# Layer order is intentional: Python requirements are installed before the repo
# is copied so edits to app code do not invalidate the (slow) pip layer.
FROM python:3.11-slim

# Node 20 (for opencode) + curl/ca-certificates/gnupg to set up the apt source.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g opencode-ai@1.1.48 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first for cache friendliness.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# Now the repo. chroma_db/ is copied in on purpose (small, ~0.5 MB) so vector
# search works out of the box; logs/ and caches are excluded via .dockerignore.
COPY . /app

# System Python lives at /usr/local/bin/python (already on PATH); keep it first
# so the MCP command ["python","-m","app.mcp.server"] resolves without a venv.
ENV PATH="/usr/local/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GRAPHDB_URL="http://graphdb:7200" \
    ANSWERER="agent" \
    PORT="8000"

# entrypoint.sh does the runtime opencode config swap; ensure it is executable
# even when the build context comes from Windows (no exec bit preserved).
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uvicorn", "app.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
