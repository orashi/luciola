from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.api.routes import show_status
from app.models.entities import Episode, Show


def _mem_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_show_status_not_complete_when_latest_hits_total_but_count_is_short():
    session = _mem_session()

    show = Show(title_input="Gap Show", title_canonical="Gap Show", total_eps=13)
    session.add(show)
    session.commit()
    session.refresh(show)

    # Regression scenario: only episode 13 is downloaded while earlier episodes are missing.
    session.add(Episode(show_id=show.id, ep_no=13, state="downloaded"))
    session.commit()

    out = show_status(show.id, session)

    assert out["latest_downloaded_ep"] == 13
    assert out["downloaded_count"] == 1
    assert out["total_eps"] == 13
    assert out["missing_count"] == 12
    assert out["complete"] is False
