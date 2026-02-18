from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select

from app.db import engine
from app.models.entities import Episode, Release, Show
from app.services.qbit_client import get_client
from app.settings import settings


def _extract_btih(link: str) -> str | None:
    m = re.search(r"btih:([A-Fa-f0-9]{32,40})", link or "")
    return (m.group(1).lower() if m else None)


def _container_to_host_path(path_str: str) -> str:
    if not path_str:
        return path_str
    try:
        qroot = settings.qbit_save_root.rstrip("/")
        if path_str.startswith(qroot + "/") or path_str == qroot:
            rel = path_str[len(qroot):].lstrip("/")
            return os.path.join(settings.incoming_root, rel)
    except Exception:
        pass
    return path_str


def _normalize_path(path_str: str) -> str:
    return (path_str or "").rstrip("/").lower()


def cleanup_stalled(max_age_minutes: int = 20) -> dict:
    client = get_client()
    infos = client.torrents_info(limit=500)
    now = int(time.time())
    max_age = max_age_minutes * 60

    remove_hashes: list[str] = []
    active_hashes: set[str] = set()

    with Session(engine) as s:
        downloaded_counts: dict[int, int] = {}
        for ep in s.exec(select(Episode).where(Episode.state == "downloaded")).all():
            downloaded_counts[ep.show_id] = downloaded_counts.get(ep.show_id, 0) + 1

        complete_show_save_paths = {
            _normalize_path(f"{settings.qbit_save_root.rstrip('/')}/{show.title_canonical}")
            for show in s.exec(select(Show)).all()
            if show.total_eps and downloaded_counts.get(show.id, 0) >= int(show.total_eps)
        }

    active_titles = [str(getattr(t, "name", "") or "").lower() for t in infos]

    for t in infos:
        h = str(getattr(t, "hash", "") or "").lower()
        if h:
            active_hashes.add(h)

        state = str(getattr(t, "state", ""))
        progress = float(getattr(t, "progress", 0.0) or 0.0)
        added_on = int(getattr(t, "added_on", now) or now)
        age = now - added_on

        # Guardrail: if the show path is already complete, remove active
        # queued/downloading torrents under that path to prevent false-positive churn.
        save_path = str(getattr(t, "save_path", "") or "")
        save_path_norm = _normalize_path(save_path)
        if state in {"queuedDL", "downloading", "stalledDL", "metaDL", "forcedDL"} and any(
            save_path_norm == p or save_path_norm.startswith(p + "/") for p in complete_show_save_paths
        ):
            remove_hashes.append(t.hash)
            continue

        # Immediate cleanup for known hard-broken qB state.
        if state == "missingFiles":
            remove_hashes.append(t.hash)
            continue

        # Check for "completed but missing files" - this happens when files are
        # moved/deleted externally but qB still thinks torrent is complete.
        if progress >= 0.999 and state in {"stalledUP", "uploading", "queuedUP"}:
            save_path = _container_to_host_path(str(getattr(t, "save_path", "") or ""))
            content_path = _container_to_host_path(str(getattr(t, "content_path", "") or ""))
            if content_path and not os.path.exists(content_path):
                remove_hashes.append(t.hash)
                continue
            if save_path and os.path.isdir(save_path):
                has_files = any(f.endswith((".mkv", ".mp4", ".avi", ".m4v")) for f in os.listdir(save_path))
                if not has_files:
                    remove_hashes.append(t.hash)
                    continue
            continue

        # hard failures: remove quickly so poller can try alternatives
        if state in {"error", "stalledDL", "metaDL"} and age >= max_age:
            remove_hashes.append(t.hash)
            continue

        # soft failure: too old with near-zero progress despite being queued/downloading
        if state in {"queuedDL", "downloading"} and progress < 0.02 and age >= 90 * 60:
            remove_hashes.append(t.hash)

    # De-dup while preserving order
    remove_hashes = list(dict.fromkeys(remove_hashes))

    if remove_hashes:
        client.torrents_delete(torrent_hashes=remove_hashes, delete_files=True)

    with Session(engine) as s:
        rows = s.exec(select(Release)).all()
        downloaded_eps = {
            (e.show_id, e.ep_no)
            for e in s.exec(select(Episode).where(Episode.state == "downloaded")).all()
        }

        removed = 0
        stale_pruned = 0
        dedup_pruned = 0

        # 1) Remove rows that correspond to removed torrent hashes.
        removed_set = {h.lower() for h in remove_hashes}
        for r in list(rows):
            m = (r.magnet_or_torrent or "").lower()
            if any(h in m for h in removed_set):
                s.delete(r)
                removed += 1

        # 2) Prune stale release rows not present in qB anymore.
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes * 2)
        rows = s.exec(select(Release)).all()
        for r in list(rows):
            if not r.created_at or r.created_at.replace(tzinfo=timezone.utc) >= stale_cutoff:
                continue

            link = r.magnet_or_torrent or ""
            btih = _extract_btih(link)
            if btih:
                if btih in active_hashes:
                    continue
                s.delete(r)
                stale_pruned += 1
                continue

            # For plain .torrent URLs (no hash available), use title fuzzy-presence.
            title = (r.title or "").lower()
            if not title:
                s.delete(r)
                stale_pruned += 1
                continue
            present = any(title in n or n in title for n in active_titles if n)
            if not present:
                s.delete(r)
                stale_pruned += 1

        # 3) Remove queued rows for episodes already downloaded.
        rows = s.exec(select(Release)).all()
        for r in list(rows):
            if (r.show_id, r.ep_no) in downloaded_eps:
                s.delete(r)
                dedup_pruned += 1

        s.commit()
    
    return {
        "ok": True,
        "total": len(infos),
        "removed_torrents": len(remove_hashes),
        "removed_release_rows": removed,
        "stale_release_rows": stale_pruned,
        "downloaded_release_rows": dedup_pruned,
        "max_age_minutes": max_age_minutes,
    }
