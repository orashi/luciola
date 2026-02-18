from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import time

from guessit import guessit
from sqlmodel import Session, select

from app.models.entities import Episode, Show
from app.services.matcher import extract_episode_no
from app.services.notifier import notify
from app.services.organizer import organize_file
from app.services.qbit_client import get_client
from app.settings import settings

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v"}
NON_EPISODE_PAT = re.compile(
    r"\b(?:pv|preview|trailer|teaser|ncop|nced|creditless|sample)\b", re.IGNORECASE
)


def _is_valid_media(path: Path) -> bool:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    return p.returncode == 0


def _iter_video_files(root: Path):
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.endswith(".!qB"):
            # basic guard against tiny/trash files
            if p.stat().st_size > 50 * 1024 * 1024:
                yield p


def _infer_season(show_title: str) -> int:
    m = re.search(r"(?:season|s)\s*([1-9]\d?)", show_title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"第\s*([1-9]\d?)\s*[季期]", show_title)
    if m:
        return int(m.group(1))
    return 1


def _is_non_episode_asset(file_name: str) -> bool:
    low = file_name.lower()
    if NON_EPISODE_PAT.search(low):
        return True
    if re.search(r"\b(?:menu|extras?)\b", low):
        return True
    return False


def _container_to_host_path(path_str: str) -> Path:
    p = Path(path_str)
    try:
        qroot = Path(settings.qbit_save_root)
        if p.is_absolute() and str(p).startswith(str(qroot)):
            rel = p.relative_to(qroot)
            return (Path(settings.incoming_root) / rel).resolve()
    except Exception:
        pass
    return p.resolve()


def _qbit_torrent_rows() -> tuple[object | None, list[dict]]:
    try:
        client = get_client()
        infos = client.torrents_info(limit=500)
    except Exception:
        return None, []

    rows: list[dict] = []
    for t in infos:
        cpath = str(getattr(t, "content_path", "") or "").strip()
        if not cpath:
            continue
        rows.append(
            {
                "hash": str(getattr(t, "hash", "") or ""),
                "state": str(getattr(t, "state", "") or ""),
                "progress": float(getattr(t, "progress", 0.0) or 0.0),
                "content_path": _container_to_host_path(cpath),
            }
        )
    return client, rows


def _match_torrent_for_file(path: Path, torrents: list[dict]) -> dict | None:
    rp = path.resolve()
    for t in torrents:
        cp = t["content_path"]
        if rp == cp:
            return t
        try:
            if rp.is_relative_to(cp):
                return t
        except Exception:
            pass
    return None


def _safe_unmatched_path(root: Path, show_title: str, src: Path) -> Path:
    dst_dir = root / "_unmatched" / show_title
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if not dst.exists():
        return dst
    stem = src.stem
    ext = src.suffix
    ts = int(time.time())
    return dst_dir / f"{stem}.{ts}{ext}"


def reconcile_library(session: Session) -> dict:
    incoming_root = Path(settings.incoming_root)
    shows = session.exec(select(Show)).all()

    moved = 0
    scanned = 0
    invalid = 0
    removed_qb_torrents = 0

    qbit_client, torrents = _qbit_torrent_rows()
    hashes_to_remove: set[str] = set()

    for show in shows:
        show_incoming = incoming_root / show.title_canonical
        for f in _iter_video_files(show_incoming):
            scanned += 1

            torrent = _match_torrent_for_file(f, torrents)
            if torrent and torrent["progress"] < 0.999:
                # File is still downloading in qB.
                continue

            # Skip very fresh files unless qB already reports them complete.
            try:
                age_sec = time.time() - f.stat().st_mtime
                if (not torrent or torrent["progress"] < 0.999) and age_sec < 180:
                    continue
            except Exception:
                continue

            # Ignore PV/trailer/extras artifacts.
            if _is_non_episode_asset(f.name):
                invalid += 1
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            if not _is_valid_media(f):
                invalid += 1
                try:
                    f.unlink(missing_ok=True)
                    nfo = f.with_suffix('.nfo')
                    nfo.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            parsed = guessit(f.name)
            ep = parsed.get("episode")
            season = parsed.get("season")

            if isinstance(ep, list):
                ep = ep[0] if ep else None
            if not isinstance(ep, int):
                ep_title = parsed.get("episode_title")
                if isinstance(ep_title, str) and ep_title.isdigit():
                    ep = int(ep_title)
            if not isinstance(ep, int):
                ep = extract_episode_no(f.name)
            if not isinstance(ep, int):
                continue

            if not isinstance(season, int) or season <= 0:
                season = _infer_season(show.title_canonical)

            # Guard against wrong absolute numbering leaking into the season library
            # (e.g. S02E33 for a 10-episode season).
            if show.total_eps and ep > int(show.total_eps):
                invalid += 1
                try:
                    dst = _safe_unmatched_path(incoming_root, show.title_canonical, f)
                    shutil.move(str(f), str(dst))
                    notify(f"⚠️ unmatched episode number moved: {show.title_canonical} {f.name}")
                except Exception:
                    pass
                continue

            dst = organize_file(f, show.title_canonical, int(season), ep)

            row = session.exec(
                select(Episode).where(Episode.show_id == show.id, Episode.ep_no == ep)
            ).first()
            if not row:
                row = Episode(show_id=show.id, ep_no=ep, state="downloaded")
                session.add(row)
            else:
                row.state = "downloaded"

            moved += 1
            notify(f"✅ {show.title_canonical} E{ep:02d} organized: {dst.name}")

            if torrent and torrent.get("hash"):
                hashes_to_remove.add(torrent["hash"])

    session.commit()

    # Remove completed torrents after files are organized to avoid qB missingFiles leftovers.
    if qbit_client and hashes_to_remove:
        try:
            qbit_client.torrents_delete(torrent_hashes=list(hashes_to_remove), delete_files=False)
            removed_qb_torrents = len(hashes_to_remove)
        except Exception:
            removed_qb_torrents = 0

    return {
        "ok": True,
        "shows": len(shows),
        "scanned": scanned,
        "moved": moved,
        "invalid": invalid,
        "removed_qb_torrents": removed_qb_torrents,
    }
