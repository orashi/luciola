# Bangumi Automation — Operations Playbook

## Goal
Provide low-noise, cost-aware episode tracking:
1. Detect newly aired episodes
2. Detect successful download completion
3. Confirm visibility in Jellyfin
4. Send only delta updates (no spam)

## Default monitoring strategy (Asia/Shanghai)
Use focused windows around expected release times + subtitle lag, not 24/7 polling:

- `*/15 22-23 * * 3-6`  (Wed–Sat)
- `*/15 0-2 * * 0,4,5,6` (Thu/Fri/Sat/Sun post-air)
- `*/15 7-10 * * 0` (Sun morning)

## Execution loop
1. `POST /api/jobs/poll-now`
2. Check qBittorrent completion state
3. `POST /api/jobs/reconcile-now` when completed downloads exist
4. `POST /Library/Refresh` in Jellyfin when files moved/index changed
5. Emit report only when there are meaningful changes/errors
6. Return `NO_REPLY` when no change

## Dedupe
Persist per-episode notification state in workspace memory file to avoid repeat alerts.
Recommended path:

`/home/orashi/.openclaw/workspace/memory/bangumi-episode-reminder-state.json`

## Cost baseline
Default model for routine cron loops:

`openrouter/minimax/minimax-m2.5`

Escalate only on explicit request.

## When adding new Bangumi requests
- Reuse existing focused-window jobs where possible.
- Avoid creating duplicate overlapping jobs.
- Keep prompts explicit about:
  - no fanart/bonus/preview downloads
  - strict episode mapping rules
  - NO_REPLY on no-op
  - no direct `message` tool usage inside isolated run if delivery is already configured.
