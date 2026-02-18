from __future__ import annotations

import json

from sqlmodel import Session, select

from app.db import engine
from app.models.entities import Episode, Show
from app.services.anime_db import sync_authentic_anime_info


if __name__ == "__main__":
    with Session(engine) as session:
        sync = sync_authentic_anime_info(session)

    with Session(engine) as session:
        shows = session.exec(select(Show).order_by(Show.id)).all()
        rows = []
        for show in shows:
            eps = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
            aired = sorted(e.ep_no for e in eps if e.state == "aired")
            planned = sorted(e.ep_no for e in eps if e.state == "planned")
            downloaded = sorted(e.ep_no for e in eps if e.state == "downloaded")
            rows.append(
                {
                    "show_id": show.id,
                    "title": show.title_canonical,
                    "anilist_id": show.bangumi_id,
                    "status": show.status,
                    "total_eps": show.total_eps,
                    "aired_upto": max(aired) if aired else 0,
                    "aired_count": len(aired),
                    "planned_count": len(planned),
                    "downloaded_count": len(downloaded),
                }
            )

    print(json.dumps({"sync": sync, "shows": rows}, ensure_ascii=False, indent=2))
