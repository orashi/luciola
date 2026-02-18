# luciola

<p align="center">
  <img src="assets/logo/luciola-logo.png" alt="luciola logo" width="640" />
</p>

<p align="center">
  <strong>Delta-first Bangumi monitor, reconcile loop, and notifier.</strong>
</p>

<p align="center">
  <a href="https://github.com/orashi/luciola/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/orashi/luciola/ci.yml?branch=main&label=ci"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Package manager" src="https://img.shields.io/badge/env-uv-7c3aed">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

`luciola` tracks episode releases, coordinates qBittorrent downloads, reconciles media into library layout, and supports Jellyfin refresh workflows.

---

## Features

- Episode state tracking (`planned` / `aired` / `downloaded`)
- RSS/search polling with season-aware matching
- qBittorrent enqueue + maintenance operations
- Reconcile completed media into library structure
- Jellyfin refresh trigger endpoint
- API-first design for OpenClaw/cron automation

## Quick start (local)

```bash
cd bangumi-automation
cp .env.example .env
# edit .env with real values

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

Default ports:

- qBittorrent WebUI: `8080`
- Jellyfin: `8096`
- App API: `8787`

> For remote/public environments, place services behind firewall/VPN/reverse proxy.

## API endpoints (core)

- `POST /api/intake` — upsert shows + aliases/profile
- `POST /api/shows` — add a show manually
- `GET /api/shows` — list tracked shows
- `GET /api/shows/{id}/status` — progress/status
- `POST /api/jobs/poll-now` — poll + enqueue
- `POST /api/jobs/reconcile-now` — reconcile library
- `POST /api/jobs/sync-now` — metadata sync + poll + reconcile
- `POST /api/jobs/jellyfin-refresh-now` — trigger Jellyfin refresh

## Project layout

```text
app/                    FastAPI app + services
docs/                   Runbooks and architecture
scripts/                Ops utilities
tests/                  Test suite
docker-compose.yml      Local stack
```

## Documentation

- Security policy: [SECURITY.md](./SECURITY.md)
- Contributing guide: [CONTRIBUTING.md](./CONTRIBUTING.md)
- Operations defaults: [OPERATIONS.md](./OPERATIONS.md)
- Pipeline runbook: [docs/PIPELINE_RUNBOOK.md](./docs/PIPELINE_RUNBOOK.md)
- Architecture: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
- Codex workflow: [docs/CODEX_AUTOPILOT.md](./docs/CODEX_AUTOPILOT.md)

## Brand assets

Selected logo:
- `assets/logo/luciola-logo.png`
- Source image kept as `assets/logo/luciola-logo.jpg`

Legacy logo candidates remain in `assets/logo/` for reference.

## Security baseline

- Do **not** commit `.env` or real credentials
- Keep runtime state out of git (`data/`, caches, logs)
- Prefer least-privilege tokens and rotate credentials periodically
- Re-run secret/static scans before public pushes

## License

MIT — see [LICENSE](./LICENSE).
