"""Background portfolio batch runner.

Fase 3 rollout: portfolio evaluation is heavy (per-well economics over a
forecast loop), so the dashboard triggers a *run* instead of blocking on
the API. A short-lived thread pool executes runs; every run is persisted
as ``PortfolioRun`` + ``PortfolioRunItem`` so results survive restarts and
can be re-served to the frontend without recomputing.

The executor is created lazily at the module level and reused by the app.
Workers create their own ``SessionLocal`` (the bound engine allows
cross-thread use with ``check_same_thread=False`` for sqlite).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import time

from api.database import SessionLocal
from api.models import PortfolioRun, PortfolioRunItem
from api import portfolio_eval

_executor = ThreadPoolExecutor(max_workers=2,
                               thread_name_prefix="portfolio-run")


def _default_workers() -> int:
    try:
        return max(1, min(int(os.environ.get("PORTFOLIO_WORKERS", "4")), 32))
    except ValueError:
        return 4


PORTFOLIO_WORKERS = _default_workers()  # per-well parallel evaluation threads

POLL_BACKOFF_SECONDS = 0.25
QUEUE_LIMIT = 200  # keep the table lean: drop older runs of the same key


def _utcnow():
    return datetime.now(timezone.utc)


def _execute(run_id: int) -> None:
    """Full lifecycle of one run; always switches the run to a terminal
    status (done | failed) so the frontend poll never spins forever."""
    db = SessionLocal()
    try:
        run = db.query(PortfolioRun).filter(PortfolioRun.id == run_id).one()
        run.status = "running"
        db.commit()

        reports = portfolio_eval.portfolio_reports_parallel(
            db, run.owner_key_id,
            gas_price_usd_mcf=run.gas_price_usd_mcf,
            max_steps=run.max_steps, workers=PORTFOLIO_WORKERS)
        summ = portfolio_eval.summary_of(reports)

        run.summary_json = dict(summ)
        run.wells_total = int(summ["wells_total"])
        run.wells_actionable = int(summ["wells_actionable"])
        run.error = None
        for report in reports:
            flat = portfolio_eval.rank_row_schema(report)
            item = PortfolioRunItem(run=run, **portfolio_eval.flat_to_item(flat))
            db.add(item)
        run.status = "done"
        run.finished_at = _utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - persist any failure
        db.rollback()
        db.query(PortfolioRun).filter(PortfolioRun.id == run_id).update({
            "status": "failed",
            "error": str(exc)[:2000],
            "finished_at": _utcnow(),
        })
        db.commit()
    finally:
        db.close()


def submit_portfolio_run(owner_key_id: int, gas_price_usd_mcf: float,
                         max_steps: int) -> int:
    """:returns: run_id (already running in background)."""
    db = SessionLocal()
    try:
        try:
            _prune(db, owner_key_id)
        except Exception:
            db.rollback()
        run = PortfolioRun(owner_key_id=owner_key_id, status="queued",
                           gas_price_usd_mcf=gas_price_usd_mcf,
                           max_steps=max_steps)
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()
    _executor.submit(_execute, run_id)
    return run_id


def _prune(db, owner_key_id: int) -> None:
    """Keep the last QUEUE_LIMIT runs per key."""
    old = (db.query(PortfolioRun)
             .filter(PortfolioRun.owner_key_id == owner_key_id)
             .order_by(PortfolioRun.id.desc())
             .offset(QUEUE_LIMIT)
             .all())
    for r in old:
        db.delete(r)
    if old:
        db.commit()


def current_status(run_id: int) -> str:
    db = SessionLocal()
    try:
        row = (db.query(PortfolioRun)
                 .filter(PortfolioRun.id == run_id).one_or_none())
        return row.status if row else "missing"
    finally:
        db.close()


def wait_for_run(run_id: int, timeout_seconds: float = 180.0) -> str:
    """Blocking poll used only by tests/scripts; returns final status."""
    db = SessionLocal()
    try:
        deadline = time.monotonic() + timeout_seconds
        status = "running"
        while time.monotonic() < deadline:
            status = (db.query(PortfolioRun)
                        .filter(PortfolioRun.id == run_id)
                        .one().status)
            if status in ("done", "failed"):
                return status
            time.sleep(POLL_BACKOFF_SECONDS)
        return status
    finally:
        db.close()