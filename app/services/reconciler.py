from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median
import json
import re
import shutil
import subprocess
import time

from guessit import guessit
from sqlmodel import Session, select

from app.models.entities import Episode, Show
from app.services.hash_manifest import (
    check_mapping_consistency,
    compute_md5,
    record_episode_hash,
)
from app.services.matcher import extract_episode_no
from app.services.notifier import notify
from app.services.organizer import _display_title, _safe_name, organize_file
from app.services.qbit_client import get_client
from app.settings import settings

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v"}
EXTRA_KEYWORDS = [
    "pv",
    "trailer",
    "teaser",
    "ncop",
    "nced",
    "creditless",
    "menu",
    "bonus",
    "extra",
    "special",
    "interview",
    "talk",
    "free talk",
    "特典",
    "映像特典",
    "メイキング",
    "cast",
]
WORD_KEYWORDS = {k for k in EXTRA_KEYWORDS if re.fullmatch(r"[a-z ]+", k)}
CJK_OR_SYMBOL_KEYWORDS = [k for k in EXTRA_KEYWORDS if k not in WORD_KEYWORDS]
EXPLICIT_EP_PATTERNS = [
    re.compile(r"\bS\d{1,2}E\d{1,3}\b", re.IGNORECASE),
    re.compile(r"\b(?:E|EP)[\s._-]?0?\d{1,3}\b", re.IGNORECASE),
    re.compile(r"第\s?0?\d{1,3}\s?[话話集]", re.IGNORECASE),
]
REVIEW_QUEUE_PATH = Path(__file__).resolve().parents[2] / "memory" / "bangumi-review-queue.jsonl"


def _is_valid_media(path: Path) -> bool:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    return p.returncode == 0


def _probe_duration_seconds(path: Path) -> float | None:
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        return None
    try:
        v = float((p.stdout or "").strip())
        return v if v > 0 else None
    except Exception:
        return None


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


def _extra_keyword_hits(path_text: str) -> list[str]:
    low = path_text.lower()
    hits: list[str] = []
    for kw in sorted(WORD_KEYWORDS):
        if " " in kw:
            if kw in low:
                hits.append(kw)
            continue
        if re.search(rf"\b{re.escape(kw)}\b", low):
            hits.append(kw)
    for kw in CJK_OR_SYMBOL_KEYWORDS:
        if kw.lower() in low:
            hits.append(kw)
    return hits


def _has_explicit_episode_signal(path_text: str) -> bool:
    for pat in EXPLICIT_EP_PATTERNS:
        if pat.search(path_text):
            return True
    return False


def _extract_episode_with_confidence(
    file_name: str,
    path_text: str,
) -> tuple[int | None, int | None, bool, list[str]]:
    reasons: list[str] = []
    parsed = guessit(file_name)

    ep = parsed.get("episode")
    season = parsed.get("season")
    if isinstance(ep, list):
        ep = ep[0] if ep else None

    explicit_signal = _has_explicit_episode_signal(path_text)
    if isinstance(ep, int):
        return ep, season if isinstance(season, int) else None, explicit_signal, reasons

    ep_title = parsed.get("episode_title")
    if isinstance(ep_title, str) and ep_title.isdigit():
        return int(ep_title), season if isinstance(season, int) else None, explicit_signal, reasons

    fallback = extract_episode_no(file_name)
    if isinstance(fallback, int):
        if explicit_signal:
            return fallback, season if isinstance(season, int) else None, True, reasons
        reasons.append("low_confidence_episode_extraction")
        return fallback, season if isinstance(season, int) else None, False, reasons

    reasons.append("low_confidence_episode_extraction")
    return None, season if isinstance(season, int) else None, False, reasons


def _series_root_folder(show_title: str) -> Path:
    return Path(settings.library_root) / _safe_name(_display_title(show_title))


def _collect_show_runtime_baseline_seconds(show_title: str) -> float | None:
    series_root = _series_root_folder(show_title)
    if not series_root.exists():
        return None

    durations: list[float] = []
    for season_dir in sorted(series_root.glob("Season *")):
        if not season_dir.is_dir():
            continue
        for p in season_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                d = _probe_duration_seconds(p)
                if d is not None:
                    durations.append(d)

    if len(durations) < 3:
        return None
    return float(median(durations))


def _is_runtime_outlier(duration_sec: float | None, baseline_sec: float | None) -> bool:
    if duration_sec is None or baseline_sec is None:
        return False
    if baseline_sec <= 0:
        return False
    return duration_sec < baseline_sec * 0.55 or duration_sec > baseline_sec * 1.8


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


def _safe_move_target(dst_dir: Path, name: str) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / name
    if not dst.exists():
        return dst
    ts = int(time.time())
    stem = Path(name).stem
    ext = Path(name).suffix
    return dst_dir / f"{stem}.{ts}{ext}"


def _move_to_extras_bucket(src: Path, show_title: str, incoming_show_root: Path, bucket: str) -> Path:
    series_root = _series_root_folder(show_title)
    rel_parent = src.parent.relative_to(incoming_show_root)
    target_dir = series_root / "Extras" / bucket
    if str(rel_parent) != ".":
        target_dir = target_dir / rel_parent
    dst = _safe_move_target(target_dir, src.name)
    shutil.move(str(src), str(dst))
    return dst


def _append_review_queue(
    show: Show,
    src_path: Path,
    dst_path: Path,
    classification: str,
    reasons: list[str],
) -> None:
    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "show_id": show.id,
        "show_title": show.title_canonical,
        "src_path": str(src_path),
        "dst_path": str(dst_path),
        "classification": classification,
        "reasons": reasons,
    }
    with REVIEW_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def reconcile_library(session: Session) -> dict:
    incoming_root = Path(settings.incoming_root)
    shows = session.exec(select(Show)).all()

    moved = 0
    scanned = 0
    invalid = 0
    removed_qb_torrents = 0
    classification_counts = {
        "episode_confident": 0,
        "extra_known": 0,
        "needs_review": 0,
    }

    qbit_client, torrents = _qbit_torrent_rows()
    hashes_to_remove: set[str] = set()

    for show in shows:
        show_incoming = incoming_root / show.title_canonical
        runtime_baseline = _collect_show_runtime_baseline_seconds(show.title_canonical)

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

            if not _is_valid_media(f):
                invalid += 1
                try:
                    f.unlink(missing_ok=True)
                    nfo = f.with_suffix('.nfo')
                    nfo.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            src_original = f.resolve()
            rel_path_for_match = str(f.relative_to(show_incoming))
            keyword_hits = _extra_keyword_hits(rel_path_for_match)
            has_extra_keyword = bool(keyword_hits)
            explicit_episode_signal = _has_explicit_episode_signal(rel_path_for_match)

            ep, parsed_season, confident_ep, parse_reasons = _extract_episode_with_confidence(
                f.name,
                rel_path_for_match,
            )

            reasons: list[str] = []
            reasons.extend(parse_reasons)
            if keyword_hits:
                reasons.append(f"extra_keyword:{'|'.join(sorted(set(keyword_hits)))}")

            classification = "episode_confident"

            if has_extra_keyword and explicit_episode_signal:
                classification = "needs_review"
                reasons.append("conflicting_signals")
            elif has_extra_keyword:
                classification = "extra_known"
            elif ep is None or not confident_ep:
                classification = "needs_review"
            else:
                if show.total_eps and ep > int(show.total_eps):
                    classification = "needs_review"
                    reasons.append("episode_out_of_range")

                if classification == "episode_confident":
                    duration_sec = _probe_duration_seconds(f)
                    if _is_runtime_outlier(duration_sec, runtime_baseline):
                        classification = "needs_review"
                        reasons.append("runtime_outlier")

            if classification in {"extra_known", "needs_review"}:
                bucket = "Known" if classification == "extra_known" else "Needs-Review"
                dst = _move_to_extras_bucket(f, show.title_canonical, show_incoming, bucket)
                _append_review_queue(show, src_original, dst.resolve(), classification, sorted(set(reasons)))
                moved += 1
                classification_counts[classification] += 1
                notify(f"🗂️ {show.title_canonical} {classification}: {dst.name}")
                if torrent and torrent.get("hash"):
                    hashes_to_remove.add(torrent["hash"])
                continue

            season = parsed_season if isinstance(parsed_season, int) and parsed_season > 0 else _infer_season(
                show.title_canonical
            )

            file_md5 = compute_md5(f)
            manifest_check = check_mapping_consistency(show.title_canonical, int(season), int(ep), file_md5)
            if not manifest_check.ok:
                reasons.extend(manifest_check.reasons)
                dst = _move_to_extras_bucket(f, show.title_canonical, show_incoming, "Needs-Review")
                _append_review_queue(
                    show,
                    src_original,
                    dst.resolve(),
                    "needs_review",
                    sorted(set(reasons)),
                )
                moved += 1
                classification_counts["needs_review"] += 1
                notify(f"🗂️ {show.title_canonical} needs_review: {dst.name}")
                if torrent and torrent.get("hash"):
                    hashes_to_remove.add(torrent["hash"])
                continue

            dst = organize_file(f, show.title_canonical, int(season), int(ep))
            record_episode_hash(show.title_canonical, int(season), int(ep), dst, file_md5)

            row = session.exec(
                select(Episode).where(Episode.show_id == show.id, Episode.ep_no == int(ep))
            ).first()
            if not row:
                row = Episode(show_id=show.id, ep_no=int(ep), state="downloaded")
                session.add(row)
            else:
                row.state = "downloaded"

            moved += 1
            classification_counts["episode_confident"] += 1
            notify(f"✅ {show.title_canonical} E{int(ep):02d} organized: {dst.name}")

            if torrent and torrent.get("hash"):
                hashes_to_remove.add(torrent["hash"])

    session.commit()

    # Remove completed torrents after files are organized/moved to avoid qB missingFiles leftovers.
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
        "classification": classification_counts,
    }
