"""Background alert scheduler (Fase 1 'ingesta continua').

Opt-in asyncio loop started by the FastAPI lifespan. Every poll it
re-evaluates the whole portfolio and persists WellAlert snapshots; any
escalation fans out to Slack when SLACK_WEBHOOK_URL is set.

Control knobs (env):
    ALERT_SCHEDULER_ENABLED  1/true to start the loop (default off)
    ALERT_POLL_SECONDS       polling period in seconds (default 300)

Runs in-process, so it assumes a single uvicorn worker (the packaged
command is `uvicorn api.main:app` without --workers).
"""

import asyncio
import os


def poll_seconds() -> int:
    return max(int(os.environ.get("ALERT_POLL_SECONDS", "300")), 10)


async def alert_loop(stop: asyncio.Event):
    from api.alerts_engine import compute_portfolio_alerts
    from api.database import SessionLocal

    while not stop.is_set():
        db = SessionLocal()
        try:
            compute_portfolio_alerts(db, source="scheduler")
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            db.close()
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds())
        except asyncio.TimeoutError:
            continue


def scheduler_enabled() -> bool:
    return os.environ.get("ALERT_SCHEDULER_ENABLED", "0") \
        in ("1", "true", "True", "yes", "on")