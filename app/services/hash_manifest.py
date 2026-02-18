from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
import json

from app.services.organizer import _display_title, _safe_name

MANIFEST_ROOT = Path(__file__).resolve().parents[2] / "data" / "hash-manifests"


@dataclass
class ManifestCheckResult:
    ok: bool
    reasons: list[str]


def _series_key(show_title: str) -> str:
    return _safe_name(_display_title(show_title))


def manifest_path(show_title: str) -> Path:
    return MANIFEST_ROOT / f"{_series_key(show_title)}.json"


def _default_manifest(show_title: str) -> dict:
    return {
        "series": _series_key(show_title),
        "updated_at": None,
        "episodes": {},
        "hash_index": {},
    }


def load_manifest(show_title: str) -> dict:
    path = manifest_path(show_title)
    if not path.exists():
        return _default_manifest(show_title)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_manifest(show_title)
        data.setdefault("episodes", {})
        data.setdefault("hash_index", {})
        return data
    except Exception:
        return _default_manifest(show_title)


def save_manifest(show_title: str, manifest: dict) -> Path:
    path = manifest_path(show_title)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def episode_key(season: int, ep_no: int) -> str:
    return f"S{int(season):02d}E{int(ep_no):02d}"


def compute_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = md5()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def check_mapping_consistency(show_title: str, season: int, ep_no: int, file_md5: str) -> ManifestCheckResult:
    manifest = load_manifest(show_title)
    key = episode_key(season, ep_no)
    reasons: list[str] = []

    indexed = manifest.get("hash_index", {}).get(file_md5)
    if indexed and indexed != key:
        reasons.append(f"hash_conflicts_with_{indexed}")

    existing = manifest.get("episodes", {}).get(key)
    if isinstance(existing, dict):
        old_md5 = existing.get("md5")
        if old_md5 and old_md5 != file_md5:
            reasons.append("episode_md5_mismatch")

    return ManifestCheckResult(ok=len(reasons) == 0, reasons=reasons)


def record_episode_hash(
    show_title: str,
    season: int,
    ep_no: int,
    file_path: Path,
    file_md5: str,
) -> Path:
    manifest = load_manifest(show_title)
    key = episode_key(season, ep_no)
    episodes = manifest.setdefault("episodes", {})
    hash_index = manifest.setdefault("hash_index", {})

    episodes[key] = {
        "md5": file_md5,
        "path": str(file_path),
        "size": int(file_path.stat().st_size),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    hash_index[file_md5] = key

    return save_manifest(show_title, manifest)


def verify_range_against_manifest(show_title: str, season: int, start_ep: int, end_ep: int) -> list[dict]:
    manifest = load_manifest(show_title)
    episodes = manifest.get("episodes", {})
    mismatches: list[dict] = []

    for ep_no in range(int(start_ep), int(end_ep) + 1):
        key = episode_key(season, ep_no)
        entry = episodes.get(key)
        if not isinstance(entry, dict):
            mismatches.append({"episode": key, "status": "missing_manifest_entry"})
            continue

        p = Path(str(entry.get("path", "")))
        expected = str(entry.get("md5", ""))
        if not p.exists():
            mismatches.append({"episode": key, "status": "missing_file", "path": str(p)})
            continue

        actual = compute_md5(p)
        if expected != actual:
            mismatches.append(
                {
                    "episode": key,
                    "status": "md5_mismatch",
                    "expected_md5": expected,
                    "actual_md5": actual,
                    "path": str(p),
                }
            )

    return mismatches
