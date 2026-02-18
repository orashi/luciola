# Bangumi Automation (uv-based)

Personal automation stack for tracking releases, downloading via qBittorrent, organizing files, and notifying via Telegram.

## 1) Environment policy
This project uses **uv** for Python env + deps.

## 2) Quick start
```bash
cd bangumi-automation
cp .env.example .env
# edit .env values

uv sync
uv run uvicorn app.main:app --reload --port 8787
```

Health check:
```bash
curl http://127.0.0.1:8787/health
```

## 3) Docker stack
```bash
docker compose up -d
```

Services:
- qBittorrent: http://localhost:8080
- Jellyfin: http://localhost:8096
- App API: http://localhost:8787

## 4) Current API (agent-orchestrated mode)
- `POST /api/intake` upsert show(s) with aliases/profile (intended to be called by OpenClaw)
- `POST /api/shows` simple add for manual testing
- `GET /api/shows` list tracked shows
- `GET /api/shows/{id}/status` show download progress
- `POST /api/jobs/poll-now` run immediate RSS poll + enqueue
- `POST /api/jobs/reconcile-now` scan incoming files and organize into library
- `POST /api/jobs/sync-now` poll + reconcile in one call

Example intake:
```bash
curl -X POST http://127.0.0.1:8787/api/intake \
  -H 'content-type: application/json' \
  -d '{
    "shows": [
      {
        "title": "葬送のフリーレン",
        "canonical_title": "Sousou no Frieren",
        "total_eps": 28,
        "aliases": ["Frieren", "葬送的芙莉莲", "そうそうのフリーレン"],
        "preferred_subgroups": ["喵萌奶茶屋"],
        "min_score": 75
      }
    ]
  }'

curl -X POST http://127.0.0.1:8787/api/jobs/sync-now
```

## 5) Next implementation tasks
- [x] Add source adapters (RSS-based)
- [ ] Add bangumi.moe query/search adapter (not only RSS)
- [ ] Add metadata provider client (Bangumi API + fallback)
- [ ] Wire qBittorrent completion callback → organizer + mark Episode downloaded
- [ ] Telegram commands: /add /status /latest /pause
- [ ] Per-show subgroup/quality profile

## 5) Suggested cron/scheduler cadence
- Poll releases: every 15 min
- Verify missing episodes: every 6 hours
- Library reconcile: daily at 03:00

## 6) SMB/Jellyfin NAS-like access
- Share `/media/library` via SMB for other PCs
- Use Jellyfin for browser/mobile streaming

## 7) Health checks
One-time qB setup (save path + category):
```bash
uv run python scripts/configure_qbit.py
```

Run health check:
```bash
./scripts/healthcheck.sh
```
Checks:
- app `/health` endpoint
- qB API auth
- qB save path/category
