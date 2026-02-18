from __future__ import annotations

import os
import time
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.entities import Episode, Show
from app.services import hash_manifest, reconciler


def _mem_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _mkfile(path: Path, content: bytes = b"video-data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old = time.time() - 1000
    os.utime(path, (old, old))
    return path


def _setup_paths(monkeypatch, tmp_path: Path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    monkeypatch.setattr(reconciler.settings, "incoming_root", str(incoming))
    monkeypatch.setattr(reconciler.settings, "library_root", str(library))
    monkeypatch.setattr(reconciler, "REVIEW_QUEUE_PATH", tmp_path / "memory" / "bangumi-review-queue.jsonl")
    monkeypatch.setattr(hash_manifest, "MANIFEST_ROOT", tmp_path / "data" / "hash-manifests")
    monkeypatch.setattr(reconciler, "_is_valid_media", lambda _: True)
    monkeypatch.setattr(reconciler, "_probe_duration_seconds", lambda _: 1440.0)
    monkeypatch.setattr(reconciler, "_iter_video_files", lambda root: [p for p in root.rglob("*.mkv")])
    return incoming, library


def test_interview_like_file_routes_to_known_extras(monkeypatch, tmp_path):
    session = _mem_session()
    show = Show(title_input="A", title_canonical="Demo Show")
    session.add(show)
    session.commit()

    incoming, library = _setup_paths(monkeypatch, tmp_path)
    src = _mkfile(incoming / "Demo Show" / "Interview" / "Demo Show - cast interview.mkv")

    out = reconciler.reconcile_library(session)

    assert out["classification"]["extra_known"] == 1
    assert not src.exists()
    moved = library / "Demo Show" / "Extras" / "Known" / "Interview" / "Demo Show - cast interview.mkv"
    assert moved.exists()

    eps = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
    assert eps == []


def test_ambiguous_numeric_file_routes_to_needs_review(monkeypatch, tmp_path):
    session = _mem_session()
    show = Show(title_input="B", title_canonical="Ambiguous Show")
    session.add(show)
    session.commit()

    incoming, library = _setup_paths(monkeypatch, tmp_path)
    src = _mkfile(incoming / "Ambiguous Show" / "Ambiguous Show 03 [1080p].mkv")

    out = reconciler.reconcile_library(session)

    assert out["classification"]["needs_review"] == 1
    assert not src.exists()
    moved = library / "Ambiguous Show" / "Extras" / "Needs-Review" / "Ambiguous Show 03 [1080p].mkv"
    assert moved.exists()

    eps = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
    assert eps == []


def test_confident_episode_organized_and_marked_downloaded(monkeypatch, tmp_path):
    session = _mem_session()
    show = Show(title_input="C", title_canonical="Confident Show")
    session.add(show)
    session.commit()

    incoming, library = _setup_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(reconciler, "_probe_duration_seconds", lambda _: 1420.0)

    src = _mkfile(incoming / "Confident Show" / "Confident.Show.S01E02.mkv", b"ep2-content")

    out = reconciler.reconcile_library(session)

    assert out["classification"]["episode_confident"] == 1
    assert not src.exists()
    dst = library / "Confident Show" / "Season 01" / "Confident Show - S01E02.mkv"
    assert dst.exists()

    ep = session.exec(
        select(Episode).where(Episode.show_id == show.id, Episode.ep_no == 2)
    ).first()
    assert ep is not None
    assert ep.state == "downloaded"


def test_low_confidence_numeric_token_does_not_mark_downloaded(monkeypatch, tmp_path):
    session = _mem_session()
    show = Show(title_input="D", title_canonical="Guarded Show", total_eps=12)
    session.add(show)
    session.commit()
    session.refresh(show)

    session.add(Episode(show_id=show.id, ep_no=2, state="aired"))
    session.commit()

    incoming, library = _setup_paths(monkeypatch, tmp_path)
    src = _mkfile(incoming / "Guarded Show" / "Guarded Show 2 [v2][1080p].mkv")

    out = reconciler.reconcile_library(session)

    assert out["classification"]["needs_review"] == 1
    assert not src.exists()
    moved = library / "Guarded Show" / "Extras" / "Needs-Review" / "Guarded Show 2 [v2][1080p].mkv"
    assert moved.exists()

    ep2 = session.exec(
        select(Episode).where(Episode.show_id == show.id, Episode.ep_no == 2)
    ).first()
    assert ep2 is not None
    assert ep2.state == "aired"
