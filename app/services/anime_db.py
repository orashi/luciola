from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Any

from sqlmodel import Session, select

from app.models.entities import Episode, Show, ShowAlias

ANILIST_URL = "https://graphql.anilist.co"


def _post_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
    data = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        ANILIST_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "bangumi-automation/1.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _status_map(anilist_status: str | None) -> str:
    m = {
        "RELEASING": "airing",
        "FINISHED": "finished",
        "NOT_YET_RELEASED": "planned",
    }
    return m.get((anilist_status or "").upper(), "airing")


def _extract_season_hint(text: str | None) -> int | None:
    if not text:
        return None
    s = text.lower()

    patterns = [
        r"\bs(?:eason)?\s*([1-9]\d?)\b",
        r"\b([1-9]\d?)(?:st|nd|rd|th)\s+season\b",
        r"第\s*([1-9]\d?)\s*[季期]",
    ]
    for pat in patterns:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                continue

    # fallback: trailing part number like "Title 3"
    m2 = re.search(r"\b([2-9])\b", s)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            return None
    return None


def _infer_expected_season(show: Show, aliases: list[str]) -> int | None:
    candidates = [
        _extract_season_hint(show.title_canonical),
        _extract_season_hint(show.title_input),
        *[_extract_season_hint(a) for a in aliases],
    ]
    vals = [x for x in candidates if x and x >= 1]
    if not vals:
        return None
    # choose the most common signal, fallback to max
    freq: dict[int, int] = {}
    for v in vals:
        freq[v] = freq.get(v, 0) + 1
    return sorted(freq.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[0][0]


def _candidate_season_score(media: dict[str, Any], expected_season: int | None) -> int:
    score = 0
    rels = media.get("relations") or {}
    edges = rels.get("edges") or []

    prequels = [e for e in edges if (e.get("relationType") or "").upper() == "PREQUEL"]
    sequels = [e for e in edges if (e.get("relationType") or "").upper() == "SEQUEL"]

    # rough season order by relation depth proxy: number of prequels + 1
    inferred = len(prequels) + 1

    if expected_season is not None:
        if inferred == expected_season:
            score += 80
        else:
            score -= 25 * abs(inferred - expected_season)

    # Prefer TV/TV_SHORT/ONA over specials/movies for episodic tracking.
    fmt = (media.get("format") or "").upper()
    if fmt in {"TV", "TV_SHORT", "ONA"}:
        score += 20
    else:
        score -= 20

    # Small confidence bump when known sequel/prequel context exists.
    if prequels:
        score += 5
    if sequels:
        score += 2

    return score


def _search_media(search: str, per_page: int = 10) -> list[dict[str, Any]]:
    query = """
    query ($search: String, $perPage: Int) {
      Page(page: 1, perPage: $perPage) {
        media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
          id
          format
          status
          episodes
          title { romaji english native }
          synonyms
          nextAiringEpisode { episode airingAt }
          relations {
            edges {
              relationType
              node { id format title { romaji english native } }
            }
          }
        }
      }
    }
    """
    obj = _post_graphql(query, {"search": search, "perPage": per_page})
    if not obj:
        return []
    return (((obj.get("data") or {}).get("Page") or {}).get("media") or [])


def _media_by_id(media_id: int) -> dict[str, Any] | None:
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        format
        status
        episodes
        title { romaji english native }
        nextAiringEpisode { episode airingAt }
      }
    }
    """
    obj = _post_graphql(query, {"id": media_id})
    return ((obj or {}).get("data") or {}).get("Media")


def _strip_season_tokens(text: str) -> str:
    s = text
    s = re.sub(r"\b([1-9]\d?)(?:st|nd|rd|th)?\s*season\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bs(?:eason)?\s*[1-9]\d?\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"第\s*[1-9]\d?\s*[季期]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -_:/")
    return s.strip()


def _pick_best_media(show: Show, aliases: list[str]) -> dict[str, Any] | None:
    expected_season = _infer_expected_season(show, aliases)

    # broaden term pool: original aliases + season-stripped aliases
    terms: list[str] = []
    for a in aliases[:10]:
        if a and a.strip():
            terms.append(a.strip())
            stripped = _strip_season_tokens(a.strip())
            if stripped and stripped.lower() != a.strip().lower():
                terms.append(stripped)
    terms = list(dict.fromkeys(terms))[:12]

    pool: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for a in terms:
        for m in _search_media(a, per_page=8):
            mid = int(m.get("id") or 0)
            if mid and mid not in seen_ids:
                pool.append(m)
                seen_ids.add(mid)

    if not pool:
        return None

    def _name_blob(media: dict[str, Any]) -> str:
        t = media.get("title") or {}
        names = [t.get("romaji"), t.get("english"), t.get("native"), *(media.get("synonyms") or [])]
        return " ".join([x for x in names if x]).lower()

    norm_aliases = [a.lower() for a in aliases if a]

    ranked: list[tuple[int, dict[str, Any]]] = []
    for m in pool:
        score = _candidate_season_score(m, expected_season)
        blob = _name_blob(m)
        if any(a in blob for a in norm_aliases):
            score += 10
        if (m.get("status") or "").upper() == "RELEASING":
            score += 6
        ranked.append((score, m))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1] if ranked else None


def _fetch_aired_upto(media_id: int, status: str, total_eps: int | None, next_air_ep: int | None) -> int:
    # Prefer authoritative schedule when available.
    query = """
    query ($mediaId: Int, $page: Int) {
      Page(page: $page, perPage: 50) {
        pageInfo { hasNextPage }
        airingSchedules(mediaId: $mediaId, sort: EPISODE) {
          episode
          airingAt
        }
      }
    }
    """

    aired_max = 0
    now_ts = int(time.time())
    page = 1
    while True:
        obj = _post_graphql(query, {"mediaId": media_id, "page": page})
        if not obj:
            break
        page_obj = ((obj.get("data") or {}).get("Page") or {})
        schedules = page_obj.get("airingSchedules") or []
        if not schedules:
            break
        for sc in schedules:
            ep = int(sc.get("episode") or 0)
            at = int(sc.get("airingAt") or 0)
            # Keep only already-aired schedule entries.
            if ep > 0 and at > 0 and at <= now_ts:
                aired_max = max(aired_max, ep)

        if not ((page_obj.get("pageInfo") or {}).get("hasNextPage")):
            break
        page += 1

    if aired_max > 0:
        return aired_max

    # Fallbacks.
    if next_air_ep and next_air_ep > 0:
        return max(0, next_air_ep - 1)
    if status == "finished" and total_eps:
        return int(total_eps)
    return 0


def _cleanup_overflow_rows(session: Session, show: Show) -> int:
    if not show.total_eps:
        return 0
    cutoff = int(show.total_eps)
    rows = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
    removed = 0
    for r in rows:
        if r.ep_no > cutoff and r.state != "downloaded":
            session.delete(r)
            removed += 1
    return removed


def _sync_episode_rows(session: Session, show: Show, aired_upto: int) -> dict[str, int]:
    rows = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
    by_no = {r.ep_no: r for r in rows}

    created = 0
    updated = 0

    max_ep = int(show.total_eps) if show.total_eps else aired_upto
    if max_ep < aired_upto:
        max_ep = aired_upto

    for ep_no in range(1, max_ep + 1):
        desired = "aired" if ep_no <= aired_upto else "planned"
        row = by_no.get(ep_no)
        if not row:
            session.add(Episode(show_id=show.id, ep_no=ep_no, state=desired))
            created += 1
            continue

        # Never downgrade downloaded.
        if row.state == "downloaded":
            continue

        if row.state != desired:
            row.state = desired
            updated += 1

    removed = _cleanup_overflow_rows(session, show)

    return {"created": created, "updated": updated, "removed": removed}


def sync_authentic_anime_info(session: Session) -> dict[str, Any]:
    shows = session.exec(select(Show)).all()

    updated = 0
    no_match = 0
    details: list[dict[str, Any]] = []

    for show in shows:
        aliases = [show.title_canonical, show.title_input]
        alias_rows = session.exec(select(ShowAlias).where(ShowAlias.show_id == show.id)).all()
        aliases.extend([a.alias for a in alias_rows])
        aliases = [a.strip() for a in aliases if a and a.strip()]

        media = None
        # Reuse stable mapping if already resolved.
        if show.bangumi_id:
            media = _media_by_id(int(show.bangumi_id))

        if not media:
            media = _pick_best_media(show, aliases)
            if media and media.get("id"):
                show.bangumi_id = int(media["id"])

        if not media:
            # transient upstream/API failures should not destroy locked mappings
            overflow_removed = _cleanup_overflow_rows(session, show)
            if show.bangumi_id:
                details.append(
                    {
                        "show_id": show.id,
                        "title": show.title_canonical,
                        "matched": False,
                        "locked_anilist_id": int(show.bangumi_id),
                        "transient_fetch_failure": True,
                        "episode_rows": {"created": 0, "updated": 0, "removed": overflow_removed},
                    }
                )
            else:
                no_match += 1
                details.append(
                    {
                        "show_id": show.id,
                        "title": show.title_canonical,
                        "matched": False,
                        "episode_rows": {"created": 0, "updated": 0, "removed": overflow_removed},
                    }
                )
            continue

        status = _status_map(media.get("status"))
        show.status = status
        if media.get("episodes"):
            show.total_eps = int(media["episodes"])

        next_air = media.get("nextAiringEpisode") or {}
        next_air_ep = int(next_air.get("episode") or 0) or None

        aired_upto = _fetch_aired_upto(
            media_id=int(media.get("id")),
            status=status,
            total_eps=show.total_eps,
            next_air_ep=next_air_ep,
        )

        ep_changes = _sync_episode_rows(session, show, aired_upto)

        updated += 1
        details.append(
            {
                "show_id": show.id,
                "title": show.title_canonical,
                "matched": True,
                "anilist_id": int(media.get("id")),
                "status": show.status,
                "total_eps": show.total_eps,
                "aired_upto": aired_upto,
                "episode_rows": ep_changes,
            }
        )

    session.commit()
    return {
        "ok": True,
        "shows": len(shows),
        "updated": updated,
        "no_match": no_match,
        "details": details,
    }
