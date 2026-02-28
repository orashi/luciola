from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.api.routes import jellyfin_heal_order_now, jellyfin_status_now, reconcile_now
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


def test_find_series_by_title_matches_with_normalized_titles(monkeypatch):
    client = jellyfin.JellyfinClient(host="127.0.0.1", port=8096, api_key="test-key")
    cases = [
        ("Fate/strange Fake", "Fate - strange Fake"),
        ("Sousou no Frieren Season 2", "Sousou no Frieren"),
        ("New PANTY & STOCKING with GARTERBELT Season 2", "New PANTY & STOCKING with GARTERBELT"),
    ]

    for query, jellyfin_name in cases:
        monkeypatch.setattr(
            jellyfin.JellyfinClient,
            "_get_json",
            lambda self, _path, _params, jellyfin_name=jellyfin_name: {
                "Items": [{"Id": "series-1", "Name": jellyfin_name}]
            },
        )
        found = client.find_series_by_title(query)
        assert found is not None
        assert found["Name"] == jellyfin_name


def test_find_series_by_title_does_not_match_different_show(monkeypatch):
    client = jellyfin.JellyfinClient(host="127.0.0.1", port=8096, api_key="test-key")
    monkeypatch.setattr(
        jellyfin.JellyfinClient,
        "_get_json",
        lambda self, _path, _params: {"Items": [{"Id": "series-1", "Name": "Fate Zero"}]},
    )

    found = client.find_series_by_title("Fate/strange Fake")
    assert found is None


def test_get_season_null_index_numbers_filters_by_season(monkeypatch):
    client = jellyfin.JellyfinClient(host="127.0.0.1", port=8096, api_key="test-key")

    monkeypatch.setattr(
        jellyfin.JellyfinClient,
        "find_series_by_title",
        lambda self, title: {"Id": "series-1", "Name": title},
    )
    monkeypatch.setattr(
        jellyfin.JellyfinClient,
        "get_series_episodes",
        lambda self, series_id: [
            {"Id": "ep-1", "SeasonNumber": 2, "IndexNumber": None},
            {"Id": "ep-2", "SeasonNumber": 2, "IndexNumber": 2},
            {"Id": "ep-3", "SeasonNumber": 1, "IndexNumber": None},
            {"Id": "ep-4", "ParentIndexNumber": 2, "IndexNumber": None},
        ],
    )

    out = client.get_season_null_index_numbers("Show S2", 2)
    assert out == {
        "series_found": True,
        "series_id": "series-1",
        "null_index_count": 2,
        "null_index_item_ids": ["ep-1", "ep-4"],
    }


def test_jellyfin_heal_order_now_response_shape(monkeypatch):
    session = _mem_session()

    show1 = Show(title_input="A", title_canonical="Show A")
    show2 = Show(title_input="B", title_canonical="Show B Season 2")
    session.add(show1)
    session.add(show2)
    session.commit()
    session.refresh(show1)
    session.refresh(show2)

    captured = {}

    def _fake_heal(tracked, seasons):
        captured["tracked"] = tracked
        captured["seasons"] = seasons
        return [
            {
                "show_id": int(show1.id or 0),
                "title_canonical": "Show A",
                "season": 1,
                "before_null_index": 1,
                "after_null_index": 0,
                "healed": True,
                "error": None,
            },
            {
                "show_id": int(show2.id or 0),
                "title_canonical": "Show B Season 2",
                "season": 2,
                "before_null_index": 0,
                "after_null_index": 0,
                "healed": False,
                "error": None,
            },
        ]

    monkeypatch.setattr("app.api.routes.heal_jellyfin_season_order", _fake_heal)

    out = jellyfin_heal_order_now(session)
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["items"][0]["before_null_index"] == 1
    assert out["items"][0]["after_null_index"] == 0
    assert out["items"][0]["healed"] is True
    assert out["items"][0]["error"] is None
    assert captured["seasons"] == {
        int(show1.id or 0): 1,
        int(show2.id or 0): 2,
    }


def test_reconcile_now_includes_jellyfin_heal_summary(monkeypatch):
    session = _mem_session()

    monkeypatch.setattr(
        "app.api.routes.reconcile_library",
        lambda _session: {"ok": True, "moved": 2, "scanned": 10},
    )
    monkeypatch.setattr(
        "app.api.routes._run_jellyfin_heal_order",
        lambda _session: {
            "ok": True,
            "items": [
                {"healed": True, "after_null_index": 0},
                {"healed": False, "after_null_index": 2},
            ],
            "count": 2,
        },
    )

    out = reconcile_now(session)
    assert out["ok"] is True
    assert out["jellyfin_heal"] == {
        "checked": 2,
        "healed_shows": 1,
        "remaining_null_index": 2,
    }
