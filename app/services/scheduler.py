from datetime import datetime, timedelta
import subprocess

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from app.db import engine
from app.models.entities import Show
from app.services.anime_db import sync_authentic_anime_info
from app.services.job_runner import job_runner
from app.services.notifier import notify
from app.services.pipeline import poll_and_enqueue
from app.services.qbit_maintenance import cleanup_stalled
from app.services.reconciler import reconcile_library


scheduler = BackgroundScheduler(timezone="Asia/Tokyo")


def poll_releases_job() -> None:
    with Session(engine) as session:
        res = poll_and_enqueue(session)
    notify(f"[bangumi-automation] poll result: {res}")


def poll_single_show_job(show_id: int, title: str) -> None:
    # Submit background task so scheduler tick is non-blocking.
    def _run():
        with Session(engine) as session:
            return poll_and_enqueue(session, only_show_ids={show_id})

    # Timeout should exceed per_show_time_budget_sec (25s) and network jitter windows.
    job_runner.submit(
        kind="poll_show",
        payload={"show_id": show_id, "title": title},
        fn=_run,
        timeout_sec=80,
    )


def reconcile_job() -> None:
    with Session(engine) as session:
        res = reconcile_library(session)
    if res.get("moved", 0) > 0 or res.get("invalid", 0) > 0:
        notify(f"[bangumi-automation] reconcile result: {res}")


def recovery_job() -> None:
    # Fast self-heal loop: sync authoritative episode states, clean invalid files, then refill.
    with Session(engine) as session:
        sync = sync_authentic_anime_info(session)
        rec = reconcile_library(session)
        poll = poll_and_enqueue(session)
    if rec.get("invalid", 0) > 0 or poll.get("added", 0) > 0:
        notify(f"[bangumi-automation] recovery result: sync={sync} reconcile={rec} poll={poll}")


def metadata_sync_job() -> None:
    with Session(engine) as session:
        res = sync_authentic_anime_info(session)
    if res.get("updated", 0) > 0:
        notify(f"[bangumi-automation] metadata sync result: {res}")


def qbit_maintenance_job() -> None:
    res = cleanup_stalled(max_age_minutes=20)
    if res.get("removed_torrents", 0) > 0:
        notify(f"[bangumi-automation] removed stalled/error torrents: {res}")


def poster_job() -> None:
    subprocess.run(
        ["/home/orashi/.openclaw/workspace/bangumi-automation/scripts/generate_local_posters.sh"],
        check=False,
    )


def start_scheduler() -> None:
    if not scheduler.running:
        # Per-show poll jobs (staggered) so one slow source doesn't block all shows.
        with Session(engine) as session:
            shows = session.exec(select(Show)).all()

        if shows:
            base = datetime.now()
            for i, show in enumerate(shows):
                scheduler.add_job(
                    poll_single_show_job,
                    "interval",
                    minutes=15,
                    id=f"poll_show_{show.id}",
                    replace_existing=True,
                    next_run_time=base + timedelta(seconds=i * 20),
                    kwargs={"show_id": show.id, "title": show.title_canonical},
                )
        else:
            scheduler.add_job(poll_releases_job, "interval", minutes=15, id="poll_releases", replace_existing=True)

        scheduler.add_job(reconcile_job, "interval", minutes=10, id="reconcile_library", replace_existing=True)
        scheduler.add_job(qbit_maintenance_job, "interval", minutes=30, id="qbit_maintenance", replace_existing=True)
        scheduler.add_job(poster_job, "interval", minutes=120, id="poster_job", replace_existing=True)
        scheduler.add_job(metadata_sync_job, "interval", hours=6, id="metadata_sync", replace_existing=True)
        scheduler.add_job(recovery_job, "interval", minutes=20, id="recovery_job", replace_existing=True)
        scheduler.start()
