#!/usr/bin/env bash
# Container entrypoint: swap in the Linux/container opencode config and prepare
# writable paths, then exec the service command (uvicorn by default).
#
# The checked-in dev file opencode.json (Windows paths, .venv python, absolute
# file:// plugin URL) is never modified: the image carries both files and this
# script overwrites /app/opencode.json at container start only.
set -euo pipefail

cd /app

if [ -f /app/opencode.docker.json ]; then
  cp /app/opencode.docker.json /app/opencode.json
fi

# --- Plugin path fallback -----------------------------------------------------
# opencode.docker.json uses a relative plugin path ("./.opencode/plugins/trace-log.ts").
# If this opencode build rejects relative plugin paths, uncomment the sed below to
# rewrite it to an absolute file:// URL at container start.
# sed -i 's#"./\.opencode/plugins/trace-log.ts"#"file:///app/.opencode/plugins/trace-log.ts"#' /app/opencode.json
# ------------------------------------------------------------------------------

mkdir -p /app/logs

# --- GraphDB auto-secure (demo creds; interview challenge, not production) ---
# Wait up to ~60s for GraphDB REST, then enable security + reader account.
# Best-effort: never blocks app boot; failures only warn.
if [ "${GRAPHDB_AUTO_SECURE:-1}" = "1" ]; then
  for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('${GRAPHDB_URL:-http://graphdb:7200}/rest/security', timeout=2)" 2>/dev/null; then break; fi
    sleep 2
  done
  python scripts/graphdb_secure.py || echo "WARNING: GraphDB auto-secure failed; continuing open (dev)"
fi

exec "$@"
