"""
AeroLift Analytics REST API.

Run locally:
    venv\\Scripts\\uvicorn api.main:app --reload --port 8000
Interactive docs:
    http://localhost:8000/docs

Database: DATABASE_URL env var (default sqlite:///./aerolift.db;
for PostgreSQL install psycopg2-binary and point the URL there).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import __version__
from api.database import init_db
from api.routers import analysis, scada, wells


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AeroLift Analytics API",
        description="Liquid-loading intelligence for gas wells - "
                    "Lee & Wattenbarger physics (DAK/Sutton/LGE, "
                    "Beggs & Brill, Turner/Coleman) behind a REST "
                    "contract for dashboards and SCADA historians.",
        version=__version__,
        lifespan=lifespan)
    app.include_router(wells.router)
    app.include_router(analysis.router)
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
