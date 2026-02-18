# Bangumi Automation - Action Plan to Complete Fix

## Changes Already Applied ✅

1. **Fixed `app/services/qbit_client.py`**
   - Added `is_paused=False` to torrents_add() calls
   - This ensures torrents start downloading immediately after being added

2. **Fixed `app/settings.py`**
   - Increased `max_search_terms_per_show` from 6 to 12
   - Increased `max_feed_urls_per_show` from 12 to 24
   - Increased `rss_timeout_sec` from 4 to 8
   - These changes ensure both English and non-English search terms are used

3. **Cleaned Database**
   - Deleted all stuck releases with state="queued"
   - Database is now ready for fresh polling

4. **Restarted Application**
   - App restarted to pick up new settings

## Remaining Issue: qBittorrent Runtime Problem ❌

**Symptom:** Torrents immediately go to "error" or "stalledDL" state after being added

**Impact:** Prevents all new downloads from starting

**Possible Causes:**
- qBittorrent container needs restart
- Network connectivity issue in Docker
- Disk I/O problem
- Configuration limit (`max_active_checking_torrents: 1`)

## Action Steps to Complete

### Step 1: Restart qBittorrent Container
```bash
cd /home/orashi/.openclaw/workspace/bangumi-automation
docker compose restart qbittorrent

# Wait for it to come back up (check logs)
docker compose logs -f qbittorrent
```

### Step 2: Verify qBittorrent is Healthy
```bash
# Check existing torrent resumed properly
python3 << 'EOF'
from app.services.qbit_client import get_client
client = get_client()
for t in client.torrents_info():
    print(f"{t.name[:70]}")
    print(f"  State: {t.state} | Progress: {t.progress*100:.1f}% | Speed: {t.dlspeed/1024/1024:.2f} MB/s")
    print()
EOF
```

Expected: Oshi no Ko torrent should be "downloading" with >0 MB/s speed

### Step 3: Test Manual Torrent Add
```bash
python3 << 'EOF'
from app.services.qbit_client import add_magnet
from app.services.rss_sources import fetch_candidates
from urllib.parse import quote

# Find a Jujutsu Kaisen episode
search = "Jujutsu Kaisen S03E03"
urls = [f"https://nyaa.si/?page=rss&q={quote(search)}&c=1_2&f=0"]
candidates = fetch_candidates(urls, max_feeds=1, max_entries_per_feed=5, timeout_sec=10)

if candidates:
    print(f"Adding: {candidates[0].title}")
    add_magnet(candidates[0].link, save_path="/media/incoming/Jujutsu Kaisen")
    print("✓ Added successfully")
    
    # Check status after 5 seconds
    import time
    time.sleep(5)
    
    from app.services.qbit_client import get_client
    client = get_client()
    for t in client.torrents_info():
        if "jujutsu" in t.name.lower():
            print(f"\nTorrent: {t.name[:70]}")
            print(f"State: {t.state}")
            print(f"Progress: {t.progress*100:.1f}%")
            
            if t.state in ["downloading", "checkingDL", "queuedDL"]:
                print("✅ SUCCESS - Torrent is starting!")
            elif t.state in ["error", "stalledDL"]:
                print("❌ FAILED - Still have qBittorrent issue")
else:
    print("No candidates found")
EOF
```

### Step 4: Run Full Catch-Up for All Shows
```bash
# Option A: Poll all shows at once
curl -X POST http://localhost:8787/api/jobs/poll-now

# Option B: Poll each show individually (better for monitoring)
for show_id in 1 2 3 4; do
    echo "Polling show $show_id..."
    curl -X POST http://localhost:8787/api/jobs/poll-show-now/$show_id
    sleep 10
done
```

### Step 5: Verify Downloads Started
```bash
# Check qBittorrent
python3 << 'EOF'
from app.services.qbit_client import get_client
client = get_client()
torrents = client.torrents_info()
print(f"Total torrents: {len(torrents)}\n")
for t in sorted(torrents, key=lambda x: x.added_on, reverse=True)[:10]:
    print(f"{t.name[:70]}")
    print(f"  State: {t.state} | Progress: {t.progress*100:.1f}%")
    print()
EOF

# Check database
sqlite3 data/app.db << 'EOF'
SELECT 
    s.title_canonical,
    COUNT(CASE WHEN e.state = 'aired' THEN 1 END) as aired,
    COUNT(CASE WHEN e.state = 'downloaded' THEN 1 END) as downloaded
FROM show s
LEFT JOIN episode e ON e.show_id = s.id
GROUP BY s.id
ORDER BY s.id;
EOF
```

### Step 6: Monitor for 30 Minutes
Watch the logs to ensure scheduler keeps finding and adding new episodes:
```bash
journalctl --user -u bangumi-automation -f
```

Expected behavior:
- Poll jobs run every 15 minutes per show
- New episodes found and added to qBittorrent
- Torrents start downloading (not error/stalled)
- Episodes marked as "downloaded" after reconciliation

## Alternative: If qBittorrent Restart Doesn't Help

### Increase qBittorrent Active Torrent Limits
```python
from app.services.qbit_client import get_client
client = get_client()

# Increase checking limit from 1 to 4
prefs = {
    'max_active_checking_torrents': 4,
    'max_active_downloads': 16,
    'max_active_torrents': 32,
}
client.app_set_preferences(prefs)
print("Updated qBittorrent preferences")
```

### Check Docker Network
```bash
# Check if container can reach trackers
docker exec qbittorrent ping -c 3 nyaa.si
docker exec qbittorrent curl -I https://nyaa.si/

# Check container logs for errors
docker logs qbittorrent --tail=200 | grep -i error
```

### Check Disk Space and I/O
```bash
df -h /media/incoming
iostat -x 2 5  # Monitor disk I/O
```

## Success Criteria

- ✅ qBittorrent showing 10+ torrents downloading
- ✅ All 4 shows have at least 2-3 new episodes downloading
- ✅ No torrents stuck in "error" state
- ✅ Database shows episodes transitioning: aired → downloading → downloaded
- ✅ Scheduler continues finding and adding new episodes automatically

## Rollback Plan

If changes cause issues:
```bash
cd /home/orashi/.openclaw/workspace/bangumi-automation
git checkout app/services/qbit_client.py app/settings.py
pkill -f "uvicorn app.main:app"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8787 &
```

## Files Modified

1. `app/services/qbit_client.py` - Added `is_paused=False`
2. `app/settings.py` - Increased search/feed/timeout limits
3. `DEEP_DIVE_REPORT.md` - Detailed analysis (this file)
4. `ACTION_PLAN.md` - This action plan

## Contact

For questions or issues, refer to:
- DEEP_DIVE_REPORT.md for detailed findings
- App logs: `journalctl --user -u bangumi-automation`
- qBittorrent WebUI: http://localhost:8080 (credentials from your local `.env`, never commit real values)
