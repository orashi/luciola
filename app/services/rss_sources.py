from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote, urlsplit, urlunsplit
import json
import re
import time
import urllib.request

import feedparser


@dataclass
class FeedCandidate:
    title: str
    link: str
    source: str = "rss"


_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.1",
}


def _normalize_url(href: str) -> str:
    if not href or href.startswith("magnet:"):
        return href
    p = urlsplit(href)
    path = quote(p.path, safe="/%")
    query = quote(p.query, safe="=&%")
    return urlunsplit((p.scheme, p.netloc, path, query, p.fragment))


def _pick_link(entry) -> str | None:
    # Prefer magnet link if available
    for l in entry.get("links", []) or []:
        href = l.get("href", "")
        if href.startswith("magnet:"):
            return href

    # Prefer torrent enclosure URL over entry page URL
    for l in entry.get("links", []) or []:
        href = l.get("href", "")
        typ = (l.get("type") or "").lower()
        if href and "x-bittorrent" in typ:
            return _normalize_url(href)

    # fallback to entry.link
    link = entry.get("link", "")
    return _normalize_url(link) if link else None


def _bangumi_id_from_link(link: str) -> str | None:
    for pat in [r"/torrent/([0-9a-f]{24})", r"/download/torrent/([0-9a-f]{24})"]:
        m = re.search(pat, link)
        if m:
            return m.group(1)
    return None


def _resolve_bangumi_magnet(link: str) -> str | None:
    tid = _bangumi_id_from_link(link)
    if not tid:
        return None
    api = f"https://bangumi.moe/api/v2/torrent/{tid}"
    req = urllib.request.Request(api, headers={**_DEFAULT_HEADERS, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            obj = json.loads(r.read().decode())
        mg = obj.get("magnet")
        return mg if isinstance(mg, str) and mg.startswith("magnet:") else None
    except Exception:
        return None


def resolve_download_link(link: str) -> str:
    if link.startswith("magnet:"):
        return link
    if "bangumi.moe" in link:
        mg = _resolve_bangumi_magnet(link)
        if mg:
            return mg
    return link


def _parse_feed_url(url: str, timeout_sec: int = 12):
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        data = resp.read()
    return feedparser.parse(data)


def fetch_candidates(
    feed_urls: Iterable[str],
    max_feeds: int = 120,
    max_entries_per_feed: int = 60,
    timeout_sec: int = 12,
    max_total_time_sec: int | None = None,
) -> list[FeedCandidate]:
    out: list[FeedCandidate] = []
    started = time.monotonic()

    for i, url in enumerate(feed_urls):
        if i >= max_feeds:
            break
        if not url:
            continue

        if max_total_time_sec is not None:
            elapsed = time.monotonic() - started
            remaining = max_total_time_sec - elapsed
            if remaining <= 0:
                break
            per_call_timeout = max(1, min(timeout_sec, int(remaining)))
        else:
            per_call_timeout = timeout_sec

        try:
            parsed = _parse_feed_url(url, timeout_sec=per_call_timeout)
        except Exception:
            continue

        for e in list(parsed.entries or [])[:max_entries_per_feed]:
            link = _pick_link(e)
            if not link:
                continue
            out.append(FeedCandidate(title=e.get("title", ""), link=link, source=url))

    return out


def _norm(s: str) -> str:
    x = s.lower()
    x = re.sub(r"[^\w\u4e00-\u9fff]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def _term_tokens(term: str) -> list[str]:
    toks = [t for t in _norm(term).split(" ") if len(t) >= 2]
    return toks[:6]


def fetch_bangumi_api_candidates(
    search_terms: Iterable[str],
    max_pages: int = 2,
    timeout_sec: int = 12,
    max_results: int = 120,
    max_total_time_sec: int | None = None,
) -> list[FeedCandidate]:
    """
    Fallback source: scan recent bangumi.moe API pages and keep torrents whose
    title overlaps with any search-term token set.
    """
    terms = [t.strip() for t in search_terms if t and t.strip()]
    token_sets = [set(_term_tokens(t)) for t in terms]
    token_sets = [s for s in token_sets if s]

    if not token_sets:
        return []

    out: list[FeedCandidate] = []
    seen_links: set[str] = set()
    started = time.monotonic()

    for page in range(1, max_pages + 1):
        if max_total_time_sec is not None:
            elapsed = time.monotonic() - started
            remaining = max_total_time_sec - elapsed
            if remaining <= 0:
                break
            per_call_timeout = max(1, min(timeout_sec, int(remaining)))
        else:
            per_call_timeout = timeout_sec

        url = f"https://bangumi.moe/api/v2/torrent/page/{page}"
        req = urllib.request.Request(url, headers={**_DEFAULT_HEADERS, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=per_call_timeout) as r:
                obj = json.loads(r.read().decode())
        except Exception:
            continue

        torrents = obj.get("torrents", []) if isinstance(obj, dict) else []
        for t in torrents:
            title = (t.get("title") or "").strip()
            magnet = t.get("magnet") or ""
            tid = t.get("_id")
            if not title:
                continue
            link = magnet if isinstance(magnet, str) and magnet.startswith("magnet:") else ""
            if not link and isinstance(tid, str):
                link = f"https://bangumi.moe/torrent/{tid}"
            if not link or link in seen_links:
                continue

            nt = set(_term_tokens(title))
            if not nt:
                continue

            matched = any(len(nt & ts) >= 2 or ts.issubset(nt) for ts in token_sets)
            if not matched:
                continue

            seen_links.add(link)
            out.append(FeedCandidate(title=title, link=link, source="bangumi_api"))
            if len(out) >= max_results:
                return out

    return out
