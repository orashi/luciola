from fastapi import FastAPI

from app.api.routes import router
from app.db import init_db
from app.services.scheduler import start_scheduler

app = FastAPI(title="Bangumi Automation")
app.include_router(router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    start_scheduler()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/status")
def status() -> dict:
    return {"service": "bangumi-automation", "state": "running"}
