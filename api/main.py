"""
AeroLift Analytics REST API.

Run locally:
    venv\\Scripts\\uvicorn api.main:app --reload --port 8000
Interactive docs:
    http://localhost:8000/docs

Database: DATABASE_URL env var (default sqlite:///./aerolift.db;
for PostgreSQL install psycopg2-binary and point the URL there).

Auth: every /api/* endpoint requires X-API-Key (mint keys with
scripts/mint_key.py). /health and / stay open for liveness probes.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import __version__
from api.database import init_db
from api.routers import analysis, auth, bulk, ml, portfolio, scada, wells
from api.scheduler import scheduler_enabled, twin_calibration_enabled


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    background = []
    if scheduler_enabled():
        from api.scheduler import alert_loop
        stop = asyncio.Event()
        alert_task = asyncio.create_task(alert_loop(stop))
        background.append((stop, alert_task))
    if twin_calibration_enabled():
        from api.scheduler import twin_calibration_loop
        stop = asyncio.Event()
        calib_task = asyncio.create_task(twin_calibration_loop(stop))
        background.append((stop, calib_task))
    yield
    for stop, task in background:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="AeroLift Analytics API",
        description="Liquid-loading intelligence for gas wells - "
                    "Lee & Wattenbarger physics (DAK/Sutton/LGE, "
                    "Beggs & Brill, Turner/Coleman) behind a REST "
                    "contract for dashboards and SCADA historians.",
        version=__version__,
        lifespan=lifespan)
    _cors_origins = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"])
    app.include_router(auth.router)
    app.include_router(wells.router)
    app.include_router(bulk.router)
    app.include_router(analysis.router)
    app.include_router(ml.router)
    app.include_router(portfolio.router)
    app.include_router(scada.router)

    @app.get("/", tags=["meta"])
    def root():
        return {"service": "AeroLift Analytics API",
                "version": __version__,
                "docs": "/docs"}

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
