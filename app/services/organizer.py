from pathlib import Path
import re
import shutil

from app.settings import settings


def _safe_name(s: str) -> str:
    # Keep cross-platform safe and human-readable naming.
    s = s.replace('/', ' - ').replace('／', ' - ').replace('\\', ' - ').strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def _display_title(show_title: str) -> str:
    # Normalize canonical titles like "X Season 3" to series root folder "X".
    t = show_title.strip()
    t = re.sub(r"\s+(?:season|s)\s*\d{1,2}$", "", t, flags=re.IGNORECASE)
    return t


def organize_file(src: Path, show_title: str, season: int, ep_no: int) -> Path:
    safe_title = _safe_name(_display_title(show_title))
    dst_dir = Path(settings.library_root) / safe_title / f"Season {season:02d}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix
    dst = dst_dir / f"{safe_title} - S{season:02d}E{ep_no:02d}{ext}"
    shutil.move(str(src), str(dst))

    # Write local episode metadata to avoid Jellyfin season ambiguity.
    nfo = dst.with_suffix('.nfo')
    nfo.write_text(
        f'''<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<episodedetails>\n  <plot />\n  <lockdata>false</lockdata>\n  <title>{dst.stem}</title>\n  <showtitle>{safe_title}</showtitle>\n  <episode>{ep_no}</episode>\n  <season>{season}</season>\n</episodedetails>\n''',
        encoding='utf-8',
    )

    return dst
