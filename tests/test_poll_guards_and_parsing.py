from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.entities import Episode, Release, Show
from app.services.matcher import extract_episode_no
from app.services.pipeline import poll_and_enqueue
from app.services.rss_sources import FeedCandidate


def _mem_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_extract_episode_no_ignores_season_only_token():
    title = "[SomeGroup] New PANTY & STOCKING with GARTERBELT S02 MULTi 1080p"
    assert extract_episode_no(title) is None


def test_batch_range_candidate_maps_to_wanted_overlap(monkeypatch):
    session = _mem_session()
    show = Show(title_input="Demo Show", title_canonical="Demo Show", total_eps=13)
    session.add(show)
    session.commit()
    session.refresh(show)

    for ep_no in range(1, 14):
        state = "downloaded" if ep_no <= 9 else "aired"
        session.add(Episode(show_id=show.id, ep_no=ep_no, state=state))
    session.commit()

    monkeypatch.setattr("app.services.pipeline.settings.rss_urls", "https://example.invalid/rss")
    monkeypatch.setattr("app.services.pipeline.fetch_bangumi_api_candidates", lambda *a, **k: [])
    monkeypatch.setattr("app.services.pipeline.resolve_download_link", lambda link: link)
    monkeypatch.setattr("app.services.pipeline.score_release", lambda *a, **k: 100)

    def fake_fetch_candidates(*args, **kwargs):
        return [
            FeedCandidate(
                title="[Demo] Demo Show - 01-13 [1080p]",
                link="magnet:?xt=urn:btih:" + "a" * 40,
                source="rss",
            )
        ]

    monkeypatch.setattr("app.services.pipeline.fetch_candidates", fake_fetch_candidates)

    added_links: list[str] = []

    def fake_add(link: str, save_path: str):
        added_links.append(link)

    monkeypatch.setattr("app.services.pipeline.add_magnet", fake_add)

    out = poll_and_enqueue(session, only_show_ids={show.id})
    assert out["ok"] is True
    assert out["added"] == 1
    assert len(added_links) == 1

    rel = session.exec(select(Release).where(Release.show_id == show.id)).all()
    assert len(rel) == 1
    assert rel[0].ep_no == 10


def test_poll_skips_complete_show_without_backlog(monkeypatch):
    session = _mem_session()
    show = Show(title_input="Complete Show", title_canonical="Complete Show", total_eps=2)
    session.add(show)
    session.commit()
    session.refresh(show)

    session.add(Episode(show_id=show.id, ep_no=1, state="downloaded"))
    session.add(Episode(show_id=show.id, ep_no=2, state="downloaded"))
    session.commit()

    monkeypatch.setattr("app.services.pipeline.settings.rss_urls", "https://example.invalid/rss")
    calls = {"fetch": 0, "api": 0}

    def fake_fetch(*args, **kwargs):
        calls["fetch"] += 1
        return []

    def fake_api(*args, **kwargs):
        calls["api"] += 1
        return []

    monkeypatch.setattr("app.services.pipeline.fetch_candidates", fake_fetch)
    monkeypatch.setattr("app.services.pipeline.fetch_bangumi_api_candidates", fake_api)

    out = poll_and_enqueue(session, only_show_ids={show.id})
    assert out["ok"] is True
    assert out["added"] == 0
    assert calls["fetch"] == 0
    assert calls["api"] == 0
