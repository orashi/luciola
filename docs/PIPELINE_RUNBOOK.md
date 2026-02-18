# Pipeline Runbook

Operational reference for running and debugging `luciola`.

## Primary flow

1. Poll release sources
2. Enqueue candidate torrents
3. Reconcile completed media into library
4. Refresh Jellyfin when library changes
5. Emit only meaningful deltas (if integrated with notifier/cron)

## Manual job endpoints

- `POST /api/jobs/sync-metadata-now`
- `POST /api/jobs/poll-now`
- `POST /api/jobs/reconcile-now`
- `POST /api/jobs/sync-now`
- `POST /api/jobs/recovery-now`
- `POST /api/jobs/qbit-maintenance-now`
- `POST /api/jobs/jellyfin-refresh-now`

## Fast diagnostics

Health/API:

```bash
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/api/debug/runtime
```

qBittorrent auth/version:

```bash
curl --data "username=$QBIT_USERNAME&password=$QBIT_PASSWORD" \
  http://127.0.0.1:8080/api/v2/auth/login
curl http://127.0.0.1:8080/api/v2/app/version
```

Jellyfin public info:

```bash
curl http://127.0.0.1:8096/System/Info/Public
```

## Common failure patterns

### 1) Poll succeeds but no downloads added

Check:
- source query quality (aliases / season filtering)
- candidate rejection filters
- qB API auth and category/save path config

### 2) Torrents added but never complete

Check:
- qB state (`error`, `stalledDL`, tracker errors)
- container/network reachability to trackers
- disk space and write permissions on incoming path

### 3) Files downloaded but not visible in Jellyfin

Check:
- reconcile logs/path mapping
- library destination naming/season layout
- Jellyfin refresh auth (`JELLYFIN_API_KEY` / host / port)

## Safe restart pattern

If process/service is stuck:

1. Stop app process/service cleanly
2. Ensure no stale worker remains
3. Start app again
4. Re-run health + one manual job endpoint

## Notes

- Prefer small, observable changes in production.
- Validate each stage independently before enabling high-frequency automation.
