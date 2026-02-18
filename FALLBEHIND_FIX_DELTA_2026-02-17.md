# Fall-behind Fix Delta Report (2026-02-17 JST)

## End-state verification (current)

- **Aired backlog (all tracked shows): 0**
- **qB active/stale torrents: 0**
- **release table stale rows: 0**
- **Library episode ordering normalized for tracked shows**

DB snapshot:

```
(1) Jujutsu Kaisen              aired=0 downloaded=7 planned=5
(2) Fate/strange Fake           aired=0 downloaded=7 planned=6
(3) Oshi no Ko                  aired=0 downloaded=5 planned=6
(4) Sousou no Frieren Season 2  aired=0 downloaded=5 planned=5
```

qB snapshot:

```
qb_torrents=0
```

Incoming snapshot:

```
incoming video files: 1
- /media/incoming/_unmatched/Sousou no Frieren Season 2/Sousou no Frieren - S02E33.mkv
```

(kept as quarantined unmatched file; not part of active pipeline)

Library normalization applied:
- `Sousou no Frieren` season layout corrected to `Season 02 / S02E01..S02E05`
- `Fate - strange Fake` normalized (`Season 00` special + `Season 01` E01..E07 naming)

---

## Root-cause fixes applied

### 1) AniList aired-window bug (major)
**File:** `app/services/anime_db.py`

**Problem:** `_fetch_aired_upto()` treated future airing schedule rows as already aired. This created fake backlog (e.g., S3 episode counts beyond actually released).

**Fix:** only count schedule rows with `airingAt <= now`.

---

### 2) Search term starvation + poor alias coverage
**File:** `app/services/pipeline.py`

**Problem:** search terms were dominated by the first alias and episode expansions, starving canonical English terms.

**Fix:**
- alias-priority + round-robin term expansion
- explicit URL quoting with `quote(..., safe="")`
- wider feed depth retained

Result: reliable discovery for Frieren/Fate/JJK catch-up.

---

### 3) Wrong-season candidate pollution
**Files:**
- `app/services/matcher.py`
- `app/services/pipeline.py`

**Problem:** S02 releases could be accepted for S03 shows (episode-number-only matching).

**Fix:**
- added `extract_season_no()`
- inferred expected season from aliases
- hard-filtered season-mismatch candidates

---

### 4) Duplicate episode enqueues
**File:** `app/services/pipeline.py`

**Problem:** episodes already having queued releases could be re-enqueued in fallback pass.

**Fix:** include `eps_with_release` in `seen_eps` and cap enqueue attempts per show.

---

### 5) Planned-episode overreach
**File:** `app/services/pipeline.py`

**Problem:** poller treated `planned` episodes as wanted, increasing false positives.

**Fix:** only poll `aired|missing` by default; full-range backfill allowed only on first sync bootstrap.

---

### 6) qB API call hangs
**File:** `app/services/qbit_client.py`

**Fix:** set `REQUESTS_ARGS={"timeout": 20}` for qB WebAPI client.

---

### 7) Reconcile moved/handled files unsafely vs qB state
**File:** `app/services/reconciler.py`

**Problems fixed:**
- container path vs host path mismatch (`/downloads` vs `/media/incoming`)
- partial download handling
- completed torrents not cleaned after organize
- out-of-range episodes (e.g., S02E33 in 10-episode season)
- PV/trailer junk

**Fixes:**
- container→host path mapping
- skip active incomplete torrents
- process completed torrents and remove them from qB after organize
- quarantine out-of-range episode numbers to `_unmatched`
- remove PV/trailer assets
- age guard no longer blocks completed torrent files

---

### 8) qB maintenance false positives + stale release cleanup
**File:** `app/services/qbit_maintenance.py`

**Fixes:**
- container→host path mapping before file existence checks
- handle `missingFiles` state explicitly
- prune stale release rows (including non-btih cases via title fallback)
- prune release rows already downloaded

---

### 9) Naming normalization
**File:** `app/services/organizer.py`

**Fix:** sanitize fullwidth slash `／` in safe names.

Manual normalization also applied in Fate library:
- moved `S01E00` to `Season 00/S00E00`
- renamed legacy `Fate／strange Fake` files to `Fate - strange Fake`
- rewrote per-episode NFO for S01 files

---

## Config tuning

**File:** `app/settings.py`
- `rss_max_entries_per_feed`: `20 -> 60`

This enabled older missing episodes (not in top-20 feed entries) to be discovered and recovered.

---

## Rollback notes

If rollback is needed, revert these files to previous versions:

- `app/services/anime_db.py`
- `app/services/pipeline.py`
- `app/services/matcher.py`
- `app/services/qbit_client.py`
- `app/services/reconciler.py`
- `app/services/qbit_maintenance.py`
- `app/services/organizer.py`
- `app/settings.py`

Critical value rollback:
- `rss_max_entries_per_feed` back to `20` (currently `60`)

Operational rollback (service):
1. restore file versions
2. restart app process on `127.0.0.1:8787`
3. run:
   - metadata sync
   - qbit maintenance
   - reconcile

---

## Evidence commands used

```bash
sqlite3 data/app.db "SELECT s.id,s.title_canonical, SUM(CASE WHEN e.state='aired' THEN 1 ELSE 0 END), SUM(CASE WHEN e.state='downloaded' THEN 1 ELSE 0 END), SUM(CASE WHEN e.state='planned' THEN 1 ELSE 0 END) FROM show s LEFT JOIN episode e ON e.show_id=s.id GROUP BY s.id ORDER BY s.id;"

python3 - <<'PY'
from app.services.qbit_client import get_client
c=get_client(); print(len(c.torrents_info()))
PY

sqlite3 data/app.db "SELECT COUNT(*) FROM release;"
```
