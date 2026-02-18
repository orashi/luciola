# Bangumi Automation Runbook (Doctor)

## Current Execution Model

### Automatic (scheduler)
- `poll_releases`: every 15 min
- `reconcile_library`: every 10 min
- `qbit_maintenance`: every 30 min
- `recovery_job` (metadata sync + reconcile + poll): every 20 min
- `metadata_sync` (AniList authoritative sync): every 6 hours
- `poster_job`: every 120 min

### Manual acceleration (used during catch-up/debug)
- `POST /api/jobs/sync-metadata-now`
- `POST /api/jobs/poll-now`
- `POST /api/jobs/reconcile-now`
- `POST /api/jobs/recovery-now`
- `POST /api/jobs/qbit-maintenance-now`

## Why torrent count can look lower than backlog
- qB state `stalledUP` usually means **completed and seeding**, not failed download.
- Backlog size is based on episode metadata (aired/missing), but available torrent candidates can still be limited.

## Source strategy (current)
- Primary: bangumi.moe RSS + search RSS
- Fallback: nyaa RSS search (`c=1_2`, `c=1_3`)
- Episode-targeted search terms generated for missing episodes:
  - `E01`, `E1`, `Episode 1`, `第1话`, `第1集`

## Quality/Safety filters
- Reject known bad release patterns (e.g., cam/screen-record, `theaniplex.in`).
- Validate media with ffprobe before marking downloaded/organizing.
- Invalid files are deleted during reconcile to trigger re-fetch.

## Operational caveat
- User service restart can occasionally stick in `deactivating (stop-sigterm)` while background tasks are active.
- Recovery pattern used:
  1. kill stuck uvicorn process
  2. `systemctl --user reset-failed bangumi-automation`
  3. `systemctl --user start bangumi-automation`

## Quick checks
- Health: `curl http://127.0.0.1:8787/health`
- qB state summary: via qB WebUI/API (`stalledUP`, `downloading`, etc.)
- Jellyfin season anomalies: refresh library after path/naming corrections.
