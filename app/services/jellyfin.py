from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib import error, parse, request

from app.settings import settings


@dataclass
class TrackedShow:
    id: int
    title_canonical: str


def _normalize_series_title(title: str) -> str:
    x = title.casefold().strip()
    x = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    x = re.sub(r"\s+\d{1,2}(?:st|nd|rd|th)\s+season$", "", x)
    x = re.sub(r"\s+(?:season|s)\s*0*([1-9]\d?)$", "", x)
    x = re.sub(r"\s+第\s*0*([1-9]\d?)\s*[季期]$", "", x)
    return x.strip()


def infer_season_number(title: str) -> int:
    m = re.search(r"(?:season|s)\s*([1-9]\d?)", title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"第\s*([1-9]\d?)\s*[季期]", title)
    if m:
        return int(m.group(1))
    return 1


class JellyfinClient:
    def __init__(self, host: str, port: int, api_key: str):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.base_url = f"http://{host}:{port}"

    def _request_attempts(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        include_no_auth_loopback: bool = False,
    ) -> list[tuple[str, dict[str, str]]]:
        params = params or {}
        attempts: list[tuple[str, dict[str, str]]] = []

        if self.api_key:
            query_params = {**params, "api_key": self.api_key}
            attempts.append((self._build_url(path, query_params), {}))
            attempts.append((self._build_url(path, params), {"X-Emby-Token": self.api_key}))

        if include_no_auth_loopback and self.host in {"127.0.0.1", "localhost"}:
            attempts.append((self._build_url(path, params), {}))

        return attempts

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        attempts = self._request_attempts(path, params)
        if not attempts:
            raise RuntimeError("JELLYFIN_API_KEY not configured")

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

    def _post(self, path: str, params: dict[str, Any] | None = None) -> None:
        attempts = self._request_attempts(path, params, include_no_auth_loopback=True)
        if not attempts:
            raise RuntimeError("JELLYFIN_API_KEY not configured")

        last_error: str | None = None
        for url, headers in attempts:
            try:
                req = request.Request(url, headers=headers, method="POST")
                request.urlopen(req, timeout=30)
                return
            except (error.URLError, OSError) as exc:
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

        normalized_query = _normalize_series_title(title)
        normalized = [
            item
            for item in items
            if isinstance(item, dict)
            and _normalize_series_title(str(item.get("Name", ""))) == normalized_query
        ]
        if normalized:
            return normalized[0]

        for item in items:
            if isinstance(item, dict):
                break
        return None

    def get_series_episode_stats(self, series_id: str) -> tuple[int, int]:
        items = self.get_series_episodes(series_id)

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

    def get_series_episodes(self, series_id: str) -> list[dict[str, Any]]:
        data = self._get_json(f"/Shows/{series_id}/Episodes")
        items = data.get("Items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def get_season_null_index_numbers(self, series_name: str, season_number: int) -> dict[str, Any]:
        series = self.find_series_by_title(series_name)
        if not series:
            return {
                "series_found": False,
                "series_id": None,
                "null_index_count": 0,
                "null_index_item_ids": [],
            }

        series_id = str(series.get("Id") or "").strip()
        if not series_id:
            raise RuntimeError("Jellyfin series missing Id")

        null_ids: list[str] = []
        for item in self.get_series_episodes(series_id):
            season_value = item.get("SeasonNumber")
            if season_value is None and "ParentIndexNumber" in item:
                season_value = item.get("ParentIndexNumber")

            try:
                season_value_int = int(season_value)
            except (TypeError, ValueError):
                continue

            if season_value_int != season_number:
                continue

            if item.get("IndexNumber") is None:
                item_id = str(item.get("Id") or "").strip()
                if item_id:
                    null_ids.append(item_id)

        return {
            "series_found": True,
            "series_id": series_id,
            "null_index_count": len(null_ids),
            "null_index_item_ids": null_ids,
        }

    def trigger_series_refresh(self, series_id: str) -> None:
        self._post(f"/Items/{series_id}/Refresh")

    def trigger_library_refresh(self) -> None:
        self._post("/Library/Refresh")


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


def heal_jellyfin_season_order(
    shows: list[TrackedShow],
    season_by_show_id: dict[int, int],
) -> list[dict[str, Any]]:
    api_key = (settings.jellyfin_api_key or "").strip()
    if not api_key:
        msg = "JELLYFIN_API_KEY not configured"
        return [
            {
                "show_id": show.id,
                "title_canonical": show.title_canonical,
                "season": season_by_show_id.get(show.id, infer_season_number(show.title_canonical)),
                "before_null_index": 0,
                "after_null_index": 0,
                "healed": False,
                "error": msg,
            }
            for show in shows
        ]

    host = settings.jellyfin_host or "127.0.0.1"
    port = settings.jellyfin_port or 8096
    client = JellyfinClient(host=host, port=port, api_key=api_key)

    out: list[dict[str, Any]] = []
    for show in shows:
        season = season_by_show_id.get(show.id, infer_season_number(show.title_canonical))
        row = {
            "show_id": show.id,
            "title_canonical": show.title_canonical,
            "season": season,
            "before_null_index": 0,
            "after_null_index": 0,
            "healed": False,
            "error": None,
        }
        try:
            before = client.get_season_null_index_numbers(show.title_canonical, season)
            before_count = int(before.get("null_index_count") or 0)
            row["before_null_index"] = before_count
            row["after_null_index"] = before_count

            if not before.get("series_found"):
                out.append(row)
                continue

            if before_count <= 0:
                out.append(row)
                continue

            series_id = str(before.get("series_id") or "").strip()
            if not series_id:
                raise RuntimeError("Jellyfin series missing Id")

            client.trigger_series_refresh(series_id)
            after_series_refresh = client.get_season_null_index_numbers(show.title_canonical, season)
            after_count = int(after_series_refresh.get("null_index_count") or 0)

            if after_count > 0:
                client.trigger_library_refresh()
                after_library_refresh = client.get_season_null_index_numbers(show.title_canonical, season)
                after_count = int(after_library_refresh.get("null_index_count") or 0)

            row["after_null_index"] = after_count
            row["healed"] = after_count < before_count
        except Exception as exc:  # pragma: no cover - defensive catch for API edge cases
            row["error"] = str(exc)

        out.append(row)

    return out
