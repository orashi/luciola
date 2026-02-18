from __future__ import annotations

import re
import time
from urllib.parse import quote

from sqlmodel import Session, select

from app.models.entities import Episode, Release, Show, ShowAlias, ShowProfile
from app.services.matcher import (
    extract_episode_no,
    extract_episode_range,
    extract_season_no,
    is_bad_release,
    score_release,
)
from app.services.qbit_client import add_magnet
from app.services.rss_sources import (
    fetch_bangumi_api_candidates,
    fetch_candidates,
    resolve_download_link,
)
from app.settings import settings


def _preferred_subgroups() -> list[str]:
    return [x.strip() for x in settings.preferred_subgroups.split(",") if x.strip()]


def _feed_urls() -> list[str]:
    return [x.strip() for x in settings.rss_urls.split(",") if x.strip()]


def _downloaded_eps(session: Session, show_id: int) -> list[int]:
    eps = session.exec(select(Episode).where(Episode.show_id == show_id)).all()
    return sorted([e.ep_no for e in eps if e.state == "downloaded"])


def _build_search_terms(aliases: list[str], wanted_eps: list[int]) -> list[str]:
    # Keep a diverse alias set and prioritize Latin-script aliases first so
    # Nyaa searches don't get starved by only non-Latin terms.
    cleaned: list[str] = []
    for a in aliases:
        a = a.strip()
        if a and len(a) >= 2:
            cleaned.append(a)

    deduped = list(dict.fromkeys(cleaned))
    if not deduped:
        return []

    def _alias_priority(x: str) -> tuple[int, int, int, str]:
        has_latin = bool(re.search(r"[A-Za-z]", x))
        has_cjk = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", x))
        # Latin first, then CJK, then shorter terms.
        return (0 if has_latin else 1, 0 if has_cjk else 1, len(x), x.lower())

    # Use at most 6 aliases to keep per-show polling bounded.
    base_terms = sorted(deduped, key=_alias_priority)[:6]

    target_eps = wanted_eps[: settings.max_episode_queries_per_show] if wanted_eps else []
    variants = [
        lambda t, e: f"{t} E{e:02d}",
        lambda t, e: f"{t} EP{e:02d}",
        lambda t, e: f"{t} - {e:02d}",
        lambda t, e: f"{t} [{e:02d}]",
        lambda t, e: f"{t} Episode {e}",
        lambda t, e: f"{t} 第{e}话",
        lambda t, e: f"{t} 第{e}集",
    ]

    # Round-robin expansion: seed all aliases first, then grow episode variants.
    search_terms: list[str] = []
    search_terms.extend(base_terms)

    for ep in target_eps:
        for make in variants:
            for term in base_terms:
                search_terms.append(make(term, ep))
                if len(dict.fromkeys(search_terms)) >= settings.max_search_terms_per_show:
                    return list(dict.fromkeys(search_terms))[: settings.max_search_terms_per_show]

    return list(dict.fromkeys(search_terms))[: settings.max_search_terms_per_show]


def _infer_expected_season(aliases: list[str]) -> int | None:
    vals = [extract_season_no(a) for a in aliases]
    vals = [v for v in vals if isinstance(v, int) and v >= 1]
    if not vals:
        return None
    freq: dict[int, int] = {}
    for v in vals:
        freq[v] = freq.get(v, 0) + 1
    return sorted(freq.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[0][0]


def poll_and_enqueue(session: Session, only_show_ids: set[int] | None = None) -> dict:
    feed_urls = _feed_urls()
    if not feed_urls:
        return {"ok": False, "reason": "no_rss_urls"}

    default_subgroups = _preferred_subgroups()
    shows = session.exec(select(Show)).all()
    if only_show_ids is not None:
        shows = [s for s in shows if s.id in only_show_ids]

    added = 0
    scanned = 0
    total_candidates = 0

    for show in shows:
        show_start = time.monotonic()
        downloaded = _downloaded_eps(session, show.id)
        next_ep = (max(downloaded) + 1) if downloaded else 1
        first_sync = len(downloaded) == 0

        episode_rows = session.exec(select(Episode).where(Episode.show_id == show.id)).all()
        wanted_eps = sorted(
            {
                e.ep_no
                for e in episode_rows
                if e.state in {"aired", "missing"} and e.ep_no not in set(downloaded)
            }
        )

        # Initial bootstrap only: if we have no downloaded history yet, allow
        # full backfill up to declared total episodes.
        if not wanted_eps and first_sync and show.total_eps:
            wanted_eps = [ep for ep in range(1, int(show.total_eps) + 1) if ep not in set(downloaded)]

        # Skip shows that are already complete unless we have explicit
        # backlog states (aired/missing) that need refill.
        is_complete = bool(show.total_eps and len(downloaded) >= int(show.total_eps))
        if is_complete and not wanted_eps:
            continue

        alias_rows = session.exec(select(ShowAlias).where(ShowAlias.show_id == show.id)).all()
        aliases = [show.title_input, show.title_canonical, *[a.alias for a in alias_rows]]
        expected_season = _infer_expected_season(aliases)

        profile = session.exec(select(ShowProfile).where(ShowProfile.show_id == show.id)).first()
        base_min_score = profile.min_score if profile else 70
        min_score = max(55, base_min_score - 10) if first_sync else base_min_score
        show_subgroups = (
            [x.strip() for x in (profile.preferred_subgroups or "").split(",") if x.strip()]
            if profile
            else []
        )
        effective_subgroups = show_subgroups or default_subgroups

        search_terms = _build_search_terms(aliases, wanted_eps)

        show_feed_urls = list(feed_urls)
        for term in search_terms:
            q = quote(term, safe="")
            show_feed_urls.append(f"https://bangumi.moe/rss/search/{q}")
            # Nyaa fallback categories: translated / non-english / raw anime
            show_feed_urls.append(f"https://nyaa.si/?page=rss&q={q}&c=1_2&f=0")
            show_feed_urls.append(f"https://nyaa.si/?page=rss&q={q}&c=1_3&f=0")
            show_feed_urls.append(f"https://nyaa.si/?page=rss&q={q}&c=1_4&f=0")

        show_feed_urls = show_feed_urls[: settings.max_feed_urls_per_show]

        elapsed = time.monotonic() - show_start
        remaining_budget = max(0, int(settings.per_show_time_budget_sec - elapsed))

        raw_candidates = fetch_candidates(
            show_feed_urls,
            max_feeds=settings.max_feed_urls_per_show,
            max_entries_per_feed=settings.rss_max_entries_per_feed,
            timeout_sec=settings.rss_timeout_sec,
            max_total_time_sec=remaining_budget if remaining_budget > 0 else 0,
        )

        elapsed = time.monotonic() - show_start
        timed_out = elapsed >= settings.per_show_time_budget_sec

        # API fallback: only use when still within budget
        api_candidates = []
        if not timed_out:
            remaining_budget = max(0, int(settings.per_show_time_budget_sec - elapsed))
            if remaining_budget > 0:
                api_candidates = fetch_bangumi_api_candidates(
                    search_terms,
                    max_pages=settings.fallback_bangumi_api_pages,
                    timeout_sec=settings.rss_timeout_sec,
                    max_results=settings.fallback_api_results_per_show,
                    max_total_time_sec=remaining_budget,
                )

        dedup: dict[str, object] = {}
        for c in [*raw_candidates, *api_candidates]:
            if c.link not in dedup:
                dedup[c.link] = c
        candidates = list(dedup.values())[: settings.max_candidates_per_show]
        total_candidates += len(candidates)

        ranked: list[tuple[int, int, object]] = []
        by_ep: dict[int, list[tuple[int, object]]] = {}

        downloaded_set = set(downloaded)
        if len(wanted_eps) >= 5:
            min_score = max(45, min_score - 10)

        ep_offset = getattr(show, "ep_offset", 0) or 0

        for c in candidates:
            scanned += 1
            if is_bad_release(c.title):
                continue
            raw_ep = extract_episode_no(c.title)
            batch_range = extract_episode_range(c.title)
            parsed_season = extract_season_no(c.title)
            if expected_season and parsed_season and parsed_season != expected_season:
                continue

            # Batch packs like "01-13" should still be actionable for backfill.
            parsed_ep = raw_ep
            if batch_range and wanted_eps:
                lo, hi = batch_range
                overlap = [ep for ep in wanted_eps if lo <= ep <= hi]
                if overlap:
                    parsed_ep = overlap[0]

            # Apply episode offset: convert absolute fansub numbering to
            # season-relative.  e.g. torrent "EP 51" with ep_offset=48 → EP 3.
            # Only apply when raw ep is above the show's episode range —
            # some fansubs already use per-season numbering.
            if parsed_ep and ep_offset > 0 and show.total_eps:
                max_season_ep = int(show.total_eps)
                if parsed_ep > max_season_ep:
                    adjusted = parsed_ep - ep_offset
                    if 1 <= adjusted <= max_season_ep:
                        parsed_ep = adjusted
                    else:
                        # Falls outside both ranges — wrong season, skip.
                        continue

            if parsed_ep and wanted_eps and parsed_ep not in wanted_eps:
                continue
            expected_ep = parsed_ep or (wanted_eps[0] if wanted_eps else next_ep)
            s = score_release(c.title, aliases, expected_ep, effective_subgroups)
            if parsed_ep in downloaded_set:
                s -= 30
            ranked.append((s, parsed_ep or 0, c))
            if parsed_ep:
                by_ep.setdefault(parsed_ep, []).append((s, c))

        for ep_no in by_ep:
            by_ep[ep_no].sort(key=lambda x: x[0], reverse=True)

        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        per_show_added = 0
        enqueue_attempts = 0
        max_enqueue_attempts = max(6, settings.max_add_per_show_per_cycle * 4)

        existing_releases = session.exec(select(Release).where(Release.show_id == show.id)).all()
        eps_with_release = {r.ep_no for r in existing_releases}
        # Avoid duplicate torrents for episodes that already have pending releases.
        seen_eps: set[int] = set(downloaded) | eps_with_release

        def _try_enqueue(ep_no: int, s: int, cand: object) -> bool:
            nonlocal added, per_show_added, enqueue_attempts
            if ep_no in seen_eps:
                return False
            if enqueue_attempts >= max_enqueue_attempts:
                return False
            enqueue_attempts += 1

            existing = session.exec(
                select(Release).where(
                    Release.show_id == show.id,
                    Release.ep_no == ep_no,
                    Release.magnet_or_torrent == cand.link,
                )
            ).first()
            if existing:
                return False

            final_link = resolve_download_link(cand.link)
            qsave = f"{settings.qbit_save_root}/{show.title_canonical}"
            try:
                add_magnet(final_link, save_path=qsave)
            except Exception:
                return False

            rel = Release(
                show_id=show.id,
                ep_no=ep_no,
                source=cand.source,
                title=cand.title,
                magnet_or_torrent=final_link,
                score=s,
            )
            session.add(rel)

            ep = session.exec(
                select(Episode).where(Episode.show_id == show.id, Episode.ep_no == ep_no)
            ).first()
            if not ep:
                ep = Episode(show_id=show.id, ep_no=ep_no, state="aired")
                session.add(ep)

            added += 1
            per_show_added += 1
            seen_eps.add(ep_no)
            return True

        # Pass 1: deterministic earliest-missing attempts.
        for target_ep in wanted_eps:
            if per_show_added >= settings.max_add_per_show_per_cycle:
                break
            if enqueue_attempts >= max_enqueue_attempts:
                break
            if (time.monotonic() - show_start) >= settings.per_show_time_budget_sec:
                break
            if target_ep in eps_with_release:
                continue
            for s, cand in by_ep.get(target_ep, [])[:2]:
                if s < min_score:
                    continue
                if _try_enqueue(target_ep, s, cand):
                    break

        # Pass 2: global ranked fallback
        for s, parsed_ep, cand in ranked:
            if per_show_added >= settings.max_add_per_show_per_cycle:
                break
            if enqueue_attempts >= max_enqueue_attempts:
                break
            if (time.monotonic() - show_start) >= settings.per_show_time_budget_sec:
                break
            if s < min_score:
                continue
            ep_no = parsed_ep or (wanted_eps[0] if wanted_eps else next_ep)
            _try_enqueue(ep_no, s, cand)

        # persist per-show progress so a later slow source won't block prior enqueue results
        session.commit()

    session.commit()
    return {"ok": True, "shows": len(shows), "candidates": total_candidates, "scanned": scanned, "added": added}
