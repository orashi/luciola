# Architecture

## High-level flow

```text
RSS/Search Sources
      │
      ▼
 Poll + Candidate Match
      │
      ▼
 qBittorrent Enqueue
      │
      ▼
 Download Completion
      │
      ▼
 Reconcile / Organize
      │
      ▼
 Jellyfin Refresh
      │
      ▼
 Delta Notification (optional)
```

## Core modules

- `app/services/pipeline.py` — polling and enqueue pipeline
- `app/services/rss_sources.py` — RSS/search fetch and candidate collection
- `app/services/matcher.py` — episode/title/season matching and filtering
- `app/services/qbit_client.py` — qBittorrent API wrapper
- `app/services/reconciler.py` — media validation + library organization
- `app/services/qbit_maintenance.py` — stale/error cleanup and maintenance
- `app/services/anime_db.py` — metadata sync + episode state updates
- `app/services/scheduler.py` — periodic job orchestration

## Data model (SQLite)

Primary entities:
- `show`
- `episode`
- `release`

State progression (typical):
- `planned` -> `aired` -> `downloaded`

## Integration points

- qBittorrent Web API
- Jellyfin API
- Telegram notifier (optional)
- OpenClaw cron/operator loops (optional)

## Design goals

- Delta-first updates (no spam)
- Conservative matching (season-safe)
- Recoverable operations with clear health endpoints
- Keep runtime secrets and state outside git
