#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8787}"
WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"

printf "[health] app endpoint... "
APP_HEALTH=$(curl -fsS "${BASE_URL}/health" || true)
if [[ -z "$APP_HEALTH" ]]; then
  echo "FAIL"
  exit 1
fi
echo "OK ${APP_HEALTH}"

printf "[health] qBittorrent auth + prefs... "
cd "$WORKDIR"
UV_PROJECT_ENVIRONMENT=.venv-user uv run python - <<'PY'
from qbittorrentapi import Client

env = {}
with open('.env', 'r', encoding='utf-8') as f:
    for line in f:
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k,v=line.split('=',1)
        env[k]=v

client = Client(
    host=env.get('QBIT_HOST','127.0.0.1'),
    port=int(env.get('QBIT_PORT','8080')),
    username=env.get('QBIT_USERNAME',''),
    password=env.get('QBIT_PASSWORD',''),
)
client.auth_log_in()
prefs = client.app.preferences
print(f"OK version={client.app.version} save_path={prefs.get('save_path','')} category={env.get('QBIT_CATEGORY','anime')}")
PY
