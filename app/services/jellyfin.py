from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from app.settings import settings


@dataclass
class TrackedShow:
    id: int
    title_canonical: str


class JellyfinClient:
    def __init__(self, host: str, port: int, api_key: str):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.base_url = f"http://{host}:{port}"

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}

        attempts: list[tuple[str, dict[str, str]]] = []
        query_params = {**params, "api_key": self.api_key}
        attempts.append((self._build_url(path, query_params), {}))
        attempts.append((self._build_url(path, params), {"X-Emby-Token": self.api_key}))

        last_error: str | None = None
        for url, headers in attempts:
            try:
                req = request.Request(url, headers=headers, method="GET")
                with request.urlopen(req, timeout=15) as resp:
                    payload = resp.read().decode("utf-8")
                import json

                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise ValueError("Unexpected Jellyfin response payload")
                return data
            except (error.URLError, ValueError, OSError) as exc:
                last_error = str(exc)
                continue

        raise RuntimeError(last_error or "Jellyfin request failed")

    def _build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        query = parse.urlencode(params or {})
        if query:
            return f"{self.base_url}{path}?{query}"
        return f"{self.base_url}{path}"

    def find_series_by_title(self, title: str) -> dict[str, Any] | None:
        data = self._get_json(
            "/Items",
            {
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "SearchTerm": title,
                "Limit": "10",
                "Fields": "SortName",
            },
        )
        items = data.get("Items")
        if not isinstance(items, list):
            return None

        exact = [
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("Name", "")).strip().casefold() == title.strip().casefold()
        ]
        if exact:
            return exact[0]

        for item in items:
            if isinstance(item, dict):
                return item
        return None

    def get_series_episode_stats(self, series_id: str) -> tuple[int, int]:
        data = self._get_json(f"/Shows/{series_id}/Episodes")
        items = data.get("Items")
        if not isinstance(items, list):
            return 0, 0

        total_eps = 0
        unknown_season_eps = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            total_eps += 1

            season_number = item.get("SeasonNumber")
            if season_number is None and "ParentIndexNumber" in item:
                season_number = item.get("ParentIndexNumber")

            if season_number is None:
                unknown_season_eps += 1

        return total_eps, unknown_season_eps


def collect_jellyfin_status(shows: list[TrackedShow]) -> list[dict[str, Any]]:
    api_key = (settings.jellyfin_api_key or "").strip()
    if not api_key:
        msg = "JELLYFIN_API_KEY not configured"
        return [
            {
                "show_id": show.id,
                "title_canonical": show.title_canonical,
                "jellyfin_series_found": False,
                "jellyfin_total_episodes": 0,
                "jellyfin_unknown_season_episodes": 0,
                "last_error": msg,
            }
            for show in shows
        ]

    host = settings.jellyfin_host or "127.0.0.1"
    port = settings.jellyfin_port or 8096
    client = JellyfinClient(host=host, port=port, api_key=api_key)

    out: list[dict[str, Any]] = []
    for show in shows:
        row = {
            "show_id": show.id,
            "title_canonical": show.title_canonical,
            "jellyfin_series_found": False,
            "jellyfin_total_episodes": 0,
            "jellyfin_unknown_season_episodes": 0,
            "last_error": None,
        }
        try:
            series = client.find_series_by_title(show.title_canonical)
            if not series:
                out.append(row)
                continue

            row["jellyfin_series_found"] = True
            series_id = str(series.get("Id") or "").strip()
            if not series_id:
                row["last_error"] = "Jellyfin series missing Id"
                out.append(row)
                continue

            total_eps, unknown_season_eps = client.get_series_episode_stats(series_id)
            row["jellyfin_total_episodes"] = total_eps
            row["jellyfin_unknown_season_episodes"] = unknown_season_eps
        except Exception as exc:  # pragma: no cover - defensive catch for API edge cases
            row["last_error"] = str(exc)

        out.append(row)

    return out
