"""Background scheduler loops (Fase 1 'alerts' + Fase 2.1 'digital twin').

Both are opt-in asyncio loops started by the FastAPI lifespan. Runs
in-process, so they assume a single uvicorn worker (the packaged command
is `uvicorn api.main:app` without --workers).

Alert loop knobs (env):
    ALERT_SCHEDULER_ENABLED  1/true to start the loop (default off)
    ALERT_POLL_SECONDS       polling period in seconds (default 300)

Twin calibration loop knobs (env):
    TWIN_CALIBRATION_ENABLED  1/true to start the loop (default off)
    TWIN_CALIBRATION_SECONDS  retrain period in seconds (default 3600)
"""

import asyncio
import os


def poll_seconds() -> int:
    return max(int(os.environ.get("ALERT_POLL_SECONDS", "300")), 10)


def calibration_seconds() -> int:
    return max(int(os.environ.get("TWIN_CALIBRATION_SECONDS", "3600")), 60)


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


async def twin_calibration_loop(stop: asyncio.Event):
    """Retrain each well with enough new measured-Pwf history.

    Idempotent by design (see ml_service.train_twin): wells without new
    data are skipped in constant time; new data yields a new version.
    """
    from api import models, ml_service
    from api.database import SessionLocal

    while not stop.is_set():
        db = SessionLocal()
        try:
            wells = db.query(models.Well)\
                .order_by(models.Well.id).all()
            for well in wells:
                try:
                    ml_service.train_twin(db, well, source="scheduler")
                except ValueError:
                    continue  # not enough measured Pwf yet
                except Exception:
                    import traceback
                    traceback.print_exc()
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            db.close()
        try:
            await asyncio.wait_for(stop.wait(),
                                   timeout=calibration_seconds())
        except asyncio.TimeoutError:
            continue


def scheduler_enabled() -> bool:
    return os.environ.get("ALERT_SCHEDULER_ENABLED", "0") \
        in ("1", "true", "True", "yes", "on")


def twin_calibration_enabled() -> bool:
    return os.environ.get("TWIN_CALIBRATION_ENABLED", "0") \
        in ("1", "true", "True", "yes", "on")