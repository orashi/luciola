from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.api.routes import jellyfin_status_now
from app.models.entities import Show
from app.services import jellyfin


def _mem_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_jellyfin_status_now_response_shape(monkeypatch):
    session = _mem_session()

    show1 = Show(title_input="A", title_canonical="Show A")
    show2 = Show(title_input="B", title_canonical="Show B")
    session.add(show1)
    session.add(show2)
    session.commit()
    session.refresh(show1)
    session.refresh(show2)

    fake_rows = [
        {
            "show_id": show1.id,
            "title_canonical": "Show A",
            "jellyfin_series_found": True,
            "jellyfin_total_episodes": 12,
            "jellyfin_unknown_season_episodes": 1,
            "last_error": None,
        },
        {
            "show_id": show2.id,
            "title_canonical": "Show B",
            "jellyfin_series_found": False,
            "jellyfin_total_episodes": 0,
            "jellyfin_unknown_season_episodes": 0,
            "last_error": "query failed",
        },
    ]

    monkeypatch.setattr("app.api.routes.collect_jellyfin_status", lambda tracked: fake_rows)

    out = jellyfin_status_now(session)
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["items"] == fake_rows


def test_collect_jellyfin_status_missing_api_key(monkeypatch):
    monkeypatch.setattr(jellyfin.settings, "jellyfin_api_key", "")

    rows = jellyfin.collect_jellyfin_status([jellyfin.TrackedShow(id=1, title_canonical="Demo")])
    assert len(rows) == 1
    assert rows[0] == {
        "show_id": 1,
        "title_canonical": "Demo",
        "jellyfin_series_found": False,
        "jellyfin_total_episodes": 0,
        "jellyfin_unknown_season_episodes": 0,
        "last_error": "JELLYFIN_API_KEY not configured",
    }


def test_collect_jellyfin_status_counts_unknown_season(monkeypatch):
    monkeypatch.setattr(jellyfin.settings, "jellyfin_api_key", "test-key")

    monkeypatch.setattr(
        jellyfin.JellyfinClient,
        "find_series_by_title",
        lambda self, title: {"Id": "series-1", "Name": title},
    )
    monkeypatch.setattr(
        jellyfin.JellyfinClient,
        "get_series_episode_stats",
        lambda self, series_id: (4, 2),
    )

    rows = jellyfin.collect_jellyfin_status([jellyfin.TrackedShow(id=9, title_canonical="Demo")])
    assert rows == [
        {
            "show_id": 9,
            "title_canonical": "Demo",
            "jellyfin_series_found": True,
            "jellyfin_total_episodes": 4,
            "jellyfin_unknown_season_episodes": 2,
            "last_error": None,
        }
    ]
