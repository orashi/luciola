from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.entities import Episode, Show, ShowAlias
from app.services import anime_db


def _mem_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_sync_prefers_expected_season_and_generates_aired_rows(monkeypatch):
    session = _mem_session()
    show = Show(title_input="Sousou no Frieren Season 2", title_canonical="Sousou no Frieren Season 2")
    session.add(show)
    session.commit()
    session.refresh(show)
    session.add(ShowAlias(show_id=show.id, alias="葬送的芙莉莲 第2季"))
    session.commit()

    def fake_post(query: str, variables: dict):
        if "Page(page: 1, perPage: $perPage)" in query:
            # Candidate 100 is S1, 200 is S2. Expect S2 chosen.
            return {
                "data": {
                    "Page": {
                        "media": [
                            {
                                "id": 100,
                                "format": "TV",
                                "status": "FINISHED",
                                "episodes": 28,
                                "title": {"romaji": "Sousou no Frieren", "english": None, "native": None},
                                "synonyms": [],
                                "nextAiringEpisode": None,
                                "relations": {"edges": []},
                            },
                            {
                                "id": 200,
                                "format": "TV",
                                "status": "RELEASING",
                                "episodes": 24,
                                "title": {
                                    "romaji": "Sousou no Frieren 2nd Season",
                                    "english": None,
                                    "native": None,
                                },
                                "synonyms": ["Frieren Season 2"],
                                "nextAiringEpisode": {"episode": 7, "airingAt": 1890000000},
                                "relations": {
                                    "edges": [
                                        {
                                            "relationType": "PREQUEL",
                                            "node": {
                                                "id": 100,
                                                "format": "TV",
                                                "title": {
                                                    "romaji": "Sousou no Frieren",
                                                    "english": None,
                                                    "native": None,
                                                },
                                            },
                                        }
                                    ]
                                },
                            },
                        ]
                    }
                }
            }

        if "airingSchedules(mediaId: $mediaId" in query:
            if variables["mediaId"] == 200:
                return {
                    "data": {
                        "Page": {
                            "pageInfo": {"hasNextPage": False},
                            "airingSchedules": [
                                {"episode": 1, "airingAt": 1880000000},
                                {"episode": 2, "airingAt": 1880600000},
                                {"episode": 3, "airingAt": 1881200000},
                                {"episode": 4, "airingAt": 1881800000},
                                {"episode": 5, "airingAt": 1882400000},
                                {"episode": 6, "airingAt": 1883000000},
                            ],
                        }
                    }
                }

        if "Media(id: $id" in query:
            return None
        return None

    monkeypatch.setattr(anime_db, "_post_graphql", fake_post)

    out = anime_db.sync_authentic_anime_info(session)
    assert out["ok"]
    assert out["updated"] == 1

    refreshed = session.get(Show, show.id)
    assert refreshed is not None
    assert refreshed.bangumi_id == 200
    assert refreshed.total_eps == 24
    assert refreshed.status == "airing"

    eps = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
    by_no = {e.ep_no: e.state for e in eps}
    assert by_no[1] == "aired"
    assert by_no[6] == "aired"
    assert by_no[7] == "planned"
    assert by_no[24] == "planned"
