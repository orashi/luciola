from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import engine, get_session
from app.models.entities import Episode, Show, ShowAlias, ShowProfile
from app.services.anime_db import sync_authentic_anime_info
from app.services.job_runner import job_runner
from app.services.jellyfin import TrackedShow, collect_jellyfin_status
from app.services.pipeline import poll_and_enqueue
from app.services.qbit_maintenance import cleanup_stalled
from app.services.qbit_client import get_client
from app.services.reconciler import reconcile_library
from app.settings import settings
import subprocess

router = APIRouter()


def _run_poll_show(show_id: int):
    with Session(engine) as session:
        return poll_and_enqueue(session, only_show_ids={show_id})


class AddShowReq(BaseModel):
    title: str
    canonical_title: str | None = None
    total_eps: int | None = None


class IntakeShow(BaseModel):
    title: str
    canonical_title: str | None = None
    total_eps: int | None = None
    aliases: list[str] = []
    preferred_subgroups: list[str] = []
    min_score: int = 70


class IntakeReq(BaseModel):
    shows: list[IntakeShow]


@router.post("/shows")
def add_show(payload: AddShowReq, session: Session = Depends(get_session)):
    canonical = payload.canonical_title or payload.title
    existing = session.exec(select(Show).where(Show.title_canonical == canonical)).first()
    if existing:
        return {"ok": True, "show_id": existing.id, "dedup": True}

    show = Show(
        title_input=payload.title,
        title_canonical=canonical,
        total_eps=payload.total_eps,
        status="airing",
    )
    session.add(show)
    session.commit()
    session.refresh(show)
    return {"ok": True, "show_id": show.id}


@router.get("/shows")
def list_shows(session: Session = Depends(get_session)):
    shows = session.exec(select(Show)).all()
    return {"items": shows}


@router.get("/debug/runtime")
def debug_runtime():
    client = get_client()
    return {
        "ok": True,
        "routes": {
            "poll_show_sync": "/api/jobs/poll-show-now/{show_id}",
            "poll_show_async": "/api/jobs/poll-show-async/{show_id}",
            "task_status": "/api/jobs/task/{job_id}",
        },
        "timeouts": {
            "rss_timeout_sec": settings.rss_timeout_sec,
            "per_show_time_budget_sec": settings.per_show_time_budget_sec,
            "poll_show_async_timeout_sec": 80,
            "scheduler_poll_show_timeout_sec": 80,
            "qbit_requests_args": client.__dict__.get("_REQUESTS_ARGS", {}),
        },
        "limits": {
            "max_search_terms_per_show": settings.max_search_terms_per_show,
            "max_feed_urls_per_show": settings.max_feed_urls_per_show,
            "rss_max_entries_per_feed": settings.rss_max_entries_per_feed,
            "max_add_per_show_per_cycle": settings.max_add_per_show_per_cycle,
            "max_episode_queries_per_show": settings.max_episode_queries_per_show,
        },
    }


@router.post("/intake")
def intake(payload: IntakeReq, session: Session = Depends(get_session)):
    upserted = 0
    for item in payload.shows:
        canonical = item.canonical_title or item.title
        show = session.exec(select(Show).where(Show.title_canonical == canonical)).first()
        if not show:
            show = Show(
                title_input=item.title,
                title_canonical=canonical,
                total_eps=item.total_eps,
                status="airing",
            )
            session.add(show)
            session.commit()
            session.refresh(show)
            upserted += 1
        else:
            if item.total_eps and not show.total_eps:
                show.total_eps = item.total_eps

        aliases = set([item.title, canonical, *item.aliases])
        for a in aliases:
            a = a.strip()
            if not a:
                continue
            ex = session.exec(
                select(ShowAlias).where(ShowAlias.show_id == show.id, ShowAlias.alias == a)
            ).first()
            if not ex:
                session.add(ShowAlias(show_id=show.id, alias=a))

        profile = session.exec(select(ShowProfile).where(ShowProfile.show_id == show.id)).first()
        subgroup_csv = ",".join([x.strip() for x in item.preferred_subgroups if x.strip()])
        if not profile:
            profile = ShowProfile(
                show_id=show.id,
                preferred_subgroups=subgroup_csv or None,
                min_score=item.min_score,
            )
            session.add(profile)
        else:
            if subgroup_csv:
                profile.preferred_subgroups = subgroup_csv
            profile.min_score = item.min_score

    session.commit()
    return {"ok": True, "upserted": upserted, "count": len(payload.shows)}


@router.get("/shows/{show_id}/status")
def show_status(show_id: int, session: Session = Depends(get_session)):
    show = session.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=404, detail="show not found")

    eps = session.exec(select(Episode).where(Episode.show_id == show_id)).all()
    downloaded_eps = sorted({e.ep_no for e in eps if e.state == "downloaded"})
    downloaded_count = len(downloaded_eps)
    latest = downloaded_eps[-1] if downloaded_eps else None

    total_eps = show.total_eps
    complete = bool(total_eps and downloaded_count >= total_eps)
    missing_count = max(total_eps - downloaded_count, 0) if total_eps else None

    return {
        "show": show,
        "latest_downloaded_ep": latest,
        "downloaded_count": downloaded_count,
        "total_eps": total_eps,
        "missing_count": missing_count,
        "complete": complete,
    }


@router.post("/jobs/poll-now")
def poll_now(session: Session = Depends(get_session)):
    return poll_and_enqueue(session)


@router.post("/jobs/poll-show-now/{show_id}")
def poll_show_now(show_id: int, session: Session = Depends(get_session)):
    return poll_and_enqueue(session, only_show_ids={show_id})


@router.post("/jobs/poll-show-async/{show_id}")
def poll_show_async(show_id: int):
    job = job_runner.submit(
        kind="poll_show",
        payload={"show_id": show_id},
        fn=lambda: _run_poll_show(show_id),
        timeout_sec=80,
    )
    return {"ok": True, "job_id": job.id, "status": job.status}


@router.get("/jobs/task/{job_id}")
def task_status(job_id: str):
    job = job_runner.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "ok": True,
        "job": {
            "id": job.id,
            "kind": job.kind,
            "payload": job.payload,
            "status": job.status,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "result": job.result,
            "error": job.error,
        },
    }


@router.post("/jobs/task/{job_id}/cancel")
def task_cancel(job_id: str):
    ok = job_runner.cancel(job_id)
    return {"ok": ok}


@router.post("/jobs/reconcile-now")
def reconcile_now(session: Session = Depends(get_session)):
    return reconcile_library(session)


@router.post("/jobs/sync-metadata-now")
def sync_metadata_now(session: Session = Depends(get_session)):
    sync = sync_authentic_anime_info(session)
    return {"ok": True, "sync": sync}


@router.post("/jobs/sync-now")
def sync_now(session: Session = Depends(get_session)):
    sync = sync_authentic_anime_info(session)
    poll = poll_and_enqueue(session)
    rec = reconcile_library(session)
    return {"ok": True, "sync": sync, "poll": poll, "reconcile": rec}


@router.post("/jobs/qbit-maintenance-now")
def qbit_maintenance_now():
    return cleanup_stalled(max_age_minutes=20)


@router.post("/jobs/posters-now")
def posters_now():
    subprocess.run(
        ["/home/orashi/.openclaw/workspace/bangumi-automation/scripts/generate_local_posters.sh"],
        check=False,
    )
    return {"ok": True}


@router.post("/jobs/recovery-now")
def recovery_now(session: Session = Depends(get_session)):
    sync = sync_authentic_anime_info(session)
    rec = reconcile_library(session)  # also deletes invalid files
    poll = poll_and_enqueue(session)  # immediately refill replacements
    return {"ok": True, "sync": sync, "reconcile": rec, "poll": poll}


@router.get("/jobs/jellyfin-status-now")
def jellyfin_status_now(session: Session = Depends(get_session)):
    shows = session.exec(select(Show).order_by(Show.id)).all()
    tracked = [TrackedShow(id=int(show.id or 0), title_canonical=show.title_canonical) for show in shows]
    items = collect_jellyfin_status(tracked)
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/jobs/jellyfin-refresh-now")
def jellyfin_refresh_now():
    import urllib.request
    import urllib.error

    host = settings.jellyfin_host or "127.0.0.1"
    port = settings.jellyfin_port or 8096
    base_url = f"http://{host}:{port}/Library/Refresh"

    attempts = []

    # Preferred: explicit API key from environment
    if settings.jellyfin_api_key:
        attempts.append((f"{base_url}?api_key={settings.jellyfin_api_key}", {}))
        attempts.append((base_url, {"X-Emby-Token": settings.jellyfin_api_key}))

    # Optional local no-auth fallback for self-hosted trusted loopback setups
    if host in {"127.0.0.1", "localhost"}:
        attempts.append((base_url, {}))

    if not attempts:
        return {
            "ok": False,
            "error": "Jellyfin credentials not configured. Set JELLYFIN_API_KEY (or run local no-auth on loopback).",
        }

    last_error = None
    for url, headers in attempts:
        try:
            req = urllib.request.Request(url, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=30)
            return {"ok": True, "message": "Jellyfin library refresh triggered"}
        except urllib.error.URLError as e:
            last_error = str(e)
            continue

    return {"ok": False, "error": f"Jellyfin refresh failed: {last_error or 'unknown error'}"}
