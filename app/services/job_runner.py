from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    timeout_sec: int | None = None
    status: str = "queued"  # queued|running|done|failed|cancelled
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    cancelled: bool = False


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        fn: Callable[[], Any],
        timeout_sec: int | None = None,
    ) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, payload=payload, timeout_sec=timeout_sec)
        with self._lock:
            self._jobs[job.id] = job

        t = threading.Thread(target=self._execute, args=(job, fn, timeout_sec), daemon=True)
        t.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            # Watchdog for stale "running" jobs in case worker thread gets stranded.
            if (
                job.status == "running"
                and job.started_at
                and job.timeout_sec
                and (time.time() - job.started_at) > (job.timeout_sec + 5)
            ):
                job.status = "failed"
                job.error = f"job watchdog timeout after {job.timeout_sec}s"
                job.finished_at = time.time()
            return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in {"done", "failed", "cancelled"}:
                return False
            job.cancelled = True
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = time.time()
            return True

    def _execute(self, job: Job, fn: Callable[[], Any], timeout_sec: int | None) -> None:
        if job.cancelled:
            job.status = "cancelled"
            job.finished_at = time.time()
            return

        job.status = "running"
        job.started_at = time.time()
        try:
            if timeout_sec and timeout_sec > 0:
                box: dict[str, Any] = {}

                def _target():
                    try:
                        box["result"] = fn()
                    except Exception as e:
                        box["error"] = e

                t = threading.Thread(target=_target, daemon=True)
                t.start()
                t.join(timeout_sec)
                if t.is_alive():
                    raise TimeoutError(f"job timeout after {timeout_sec}s")
                if "error" in box:
                    raise box["error"]
                job.result = box.get("result")
            else:
                job.result = fn()
            job.status = "done"
        except Exception as e:
            job.error = str(e)
            job.status = "failed"
        finally:
            job.finished_at = time.time()


job_runner = JobRunner()
