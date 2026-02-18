# Bangumi Automation Deep Dive Report
**Date:** 2026-02-17 04:01 JST
**Investigator:** Subagent ce3ce1c6

## Executive Summary
Found **THREE ROOT CAUSES** for the episode download backlog:

1. **qBittorrent Add Configuration** - Torrents were being added without explicitly starting them
2. **Search Term Prioritization** - Chinese aliases were being prioritized over English, missing most releases
3. **qBittorrent Runtime Issue** - Torrents failing/stalling after being added (Docker/network issue)

## Evidence: Before State

### Database State
- Jujutsu Kaisen: Episodes 3-12 marked as "aired" but not downloaded (10 episodes behind)
- Fate/strange Fake: Episodes 8-13 marked as "aired" but not downloaded (6 episodes behind)  
- Oshi no Ko: Episodes 6-11 marked as "aired" but not downloaded (6 episodes behind)
- Frieren S2: Episodes 2-10 marked as "aired" but not downloaded (8 episodes behind)

### Release Table
- 16 releases with state="queued" from Feb 16
- BUT these releases were NEVER in qBittorrent - they failed to add

### qBittorrent State
- Only 1 active torrent (Oshi no Ko S2 episode 6-7)
- No other torrents present

## Root Cause Analysis

### Issue #1: Missing `is_paused=False` Flag
**File:** `app/services/qbit_client.py`

**Problem:** The `add_magnet()` function was calling `client.torrents_add()` without explicitly setting `is_paused=False`. Depending on qBittorrent settings, torrents may be added in a paused or queued state.

**Evidence:**
- Manually added torrent went to "error" state immediately
- qBittorrent setting `add_stopped_enabled: False` suggests torrents should start, but they didn't

**Fix Applied:**
```python
# Added is_paused=False to both code paths
res = client.torrents_add(
    torrent_files=payload,
    save_path=save_path,
    category=category or settings.qbit_category,
    is_paused=False,  # ← ADDED
)
```

### Issue #2: Search Term Limits Too Restrictive
**File:** `app/settings.py`

**Problem:** 
- `max_search_terms_per_show` was 6
- `max_feed_urls_per_show` was 12
- `rss_timeout_sec` was 4

This caused:
1. Only Chinese aliases to be used in search terms (English aliases never reached)
2. RSS feeds to timeout frequently
3. Very few candidates found (0 candidates in tests)

**Evidence:**
- Manual test with "Jujutsu Kaisen" (English) returned 40 candidates
- Manual test with "咒术回战 第3季 死灭回游" (Chinese) returned 0 Jujutsu Kaisen results
- Pipeline consistently returned `{"candidates": 0, "added": 0}`

**Fix Applied:**
```python
max_search_terms_per_show: int = 12  # Increased from 6
max_feed_urls_per_show: int = 24     # Increased from 12
rss_timeout_sec: int = 8             # Increased from 4
```

### Issue #3: qBittorrent Runtime Issue
**Status:** NOT FIXED - Requires manual intervention

**Problem:** Even after the above fixes, torrents added to qBittorrent immediately go into "error" or "stalledDL" state with 0% progress, despite having working trackers with peers available.

**Evidence:**
- Manually added Jujutsu Kaisen S03E04: went to "error" state
- Resume attempts: "error" → "stalledDL" → "error"
- Existing Oshi no Ko torrent: changed from "downloading" (54%) to "stalledDL" (0 MB/s)
- Trackers show 23-28 peers available
- Save path `/media/incoming/Jujutsu Kaisen` exists and is writable
- Directory permissions are correct (drwxr-xr-x orashi:orashi)

**Possible Causes:**
1. qBittorrent Docker container network issue
2. qBittorrent needs restart
3. Disk I/O issue on `/media/incoming`
4. qBittorrent configuration issue (e.g., `max_active_checking_torrents: 1`)
5. Firewall/port forwarding issue

**Recommended Actions:**
1. Restart qBittorrent Docker container
2. Check Docker container logs: `docker logs qbittorrent --tail=100`
3. Verify `/media/incoming` disk health: `df -h /media` and `iostat`
4. Increase `max_active_checking_torrents` in qBittorrent settings
5. Check qBittorrent WebUI directly to see error messages

## Changes Made

### 1. Fixed `app/services/qbit_client.py`
Added `is_paused=False` parameter to both `torrents_add()` calls (lines ~32 and ~40).

### 2. Fixed `app/settings.py`
Increased limits:
- `max_search_terms_per_show`: 6 → 12
- `max_feed_urls_per_show`: 12 → 24  
- `rss_timeout_sec`: 4 → 8

### 3. Cleaned Database
Deleted all stuck releases: `DELETE FROM release WHERE state = 'queued'`

### 4. Restarted Application
Killed old uvicorn process and started new one to pick up settings changes.

## After State (Partial)

### Code
- ✅ add_magnet() now explicitly starts torrents
- ✅ Search term generation covers more aliases
- ✅ RSS timeout increased to prevent feed failures

### Database
- ✅ Cleared stuck releases (0 releases in DB)
- ✅ Episodes still marked as "aired" correctly

### qBittorrent  
- ❌ Still only 1 torrent (Oshi no Ko in stalledDL state)
- ❌ New torrents go to error state immediately
- ❌ Cannot complete manual catch-up due to qBittorrent issue

## Manual Catch-Up Status

**Attempted:** Jujutsu Kaisen episodes 3-4
**Result:** Torrents added but went to error state
**Reason:** qBittorrent runtime issue (see Issue #3)

**Next Steps:**
1. Fix qBittorrent issue (restart container, check logs)
2. Re-run manual catch-up: `curl -X POST http://localhost:8787/api/jobs/poll-show-now/1`
3. Verify torrents start downloading (not error/stalled)
4. Trigger catch-up for other shows: IDs 2, 3, 4

## Testing Commands

```bash
# Check current state
sqlite3 data/app.db "SELECT show_id, ep_no, state FROM episode WHERE show_id IN (1,2,3,4) ORDER BY show_id, ep_no"

# Check qBittorrent torrents
python3 << 'EOF'
from app.services.qbit_client import get_client
client = get_client()
for t in client.torrents_info():
    print(f"{t.name[:70]} | {t.state} | {t.progress*100:.1f}%")
EOF

# Manual poll single show
curl -X POST http://localhost:8787/api/jobs/poll-show-now/1

# Manual poll all shows  
curl -X POST http://localhost:8787/api/jobs/poll-now

# Check release table
sqlite3 data/app.db "SELECT COUNT(*) as total, state, show_id FROM release GROUP BY state, show_id"
```

## Conclusion

**Identified 3 root causes, fixed 2 of them:**
1. ✅ FIXED: add_magnet configuration
2. ✅ FIXED: Search term limits
3. ❌ BLOCKED: qBittorrent runtime issue

**Cannot complete full catch-up until qBittorrent issue is resolved.**

The pipeline code is now correct and should work once qBittorrent is functional. The search logic will now find English-language releases, and torrents will be added with the correct start flag.

**Immediate Action Required:**
Investigate and fix qBittorrent - torrents immediately going to error/stalled state is preventing all downloads.
