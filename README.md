# luciola

Delta-first Bangumi monitor, reconcile, and notifier.

`luciola` tracks episode releases, coordinates qBittorrent downloads, reconciles media into your library, and supports Jellyfin refresh workflows.

## What it does

- Track shows + episode state (`planned` / `aired` / `downloaded`)
- Poll RSS/search sources for release candidates
- Add download tasks to qBittorrent
- Reconcile completed media into library layout
- Trigger Jellyfin refresh when needed
- Expose API endpoints for automation (OpenClaw, cron, scripts)

## Stack

- Python + FastAPI
- SQLModel / SQLite
- qBittorrent Web API
- Jellyfin API (optional but recommended)
- `uv` for Python dependency/env management

## Quick start (local)

```bash
cd bangumi-automation
cp .env.example .env
# edit .env with your real values

uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

## Docker

```bash
docker compose up -d
```

Default service ports:

- qBittorrent WebUI: `8080`
- Jellyfin: `8096`
- App API: `8787`

> For public/remote deployments, lock down exposure via firewall/reverse proxy/VPN.

## Core API endpoints

- `POST /api/intake` — upsert show metadata/aliases/profile
- `POST /api/shows` — add a show manually
- `GET /api/shows` — list tracked shows
- `GET /api/shows/{id}/status` — show progress/status
- `POST /api/jobs/poll-now` — poll sources and enqueue downloads
- `POST /api/jobs/reconcile-now` — reconcile downloaded media into library
- `POST /api/jobs/sync-now` — metadata sync + poll + reconcile flow
- `POST /api/jobs/jellyfin-refresh-now` — trigger Jellyfin refresh

## Security

Read [SECURITY.md](./SECURITY.md) before deployment or contribution.

Key rules:

- Never commit real secrets (`.env`, tokens, passwords)
- Keep runtime state out of git (`data/`, caches, logs)
- Use strong credentials and least-privilege tokens
- Re-run security scans before public push

## Project docs

- Operations defaults: [OPERATIONS.md](./OPERATIONS.md)
- Pipeline runbook: [docs/PIPELINE_RUNBOOK.md](./docs/PIPELINE_RUNBOOK.md)
- Codex autopilot workflow: [docs/CODEX_AUTOPILOT.md](./docs/CODEX_AUTOPILOT.md)
