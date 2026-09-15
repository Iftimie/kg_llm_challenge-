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

exec "$@"
