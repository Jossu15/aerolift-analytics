"""Alert engine - compute, persist and fan-out (Fase 1 'alertas activas').

`compute_portfolio_alerts` evaluates every well at its nominal rate,
stores a timestamped WellAlert snapshot (keeping history) and, when a
well escalates to a worse severity than the last one notified, posts a
Slack message and/or email. `last_notified_severity` on the snapshot
gates fan-out so a well only pings once per severity level reached.
"""

import datetime as _dt

from sqlalchemy.orm import Session

from api import crud, engines, models
from api.notifications import send_email_message, send_slack_message

SEVERITY_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


def _notified_rank(alert: dict, last_row) -> int:
    if last_row is None:
        return -1
    prev = last_row.last_notified_severity or last_row.severity
    return SEVERITY_RANK.get(prev, -1)


def _slack_text(alert: dict) -> str:
    margin = alert.get("margin_pct")
    m = "" if margin is None else " (margen {:.1f}%)".format(margin)
    return "*AeroLift* - {tag} escalo a *{severity}* ({status}): {message}{m}" \
        .format(tag=alert["tag"], severity=alert["severity"].upper(),
                status=alert["status"], message=alert["message"], m=m)


def _notify(alert: dict) -> None:
    """Fan-out an escalation to every configured channel (Slack, email).

    Each adapter is its own no-op when unconfigured and never raises,
    so a failure here must not break snapshot persistence.
    """
    text = _slack_text(alert)
    send_slack_message(text)
    send_email_message(
        "AeroLift - {tag} escalo a {severity}".format(
            tag=alert["tag"], severity=alert["severity"].upper()),
        text.replace("*", ""))


def compute_portfolio_alerts(db: Session, wells=None, source="manual"):
    """Evaluate, store and (on escalation) notify the given wells.

    wells=None evaluates the whole portfolio (scheduler path); otherwise
    pass the already-filtered list (e.g. owned wells for a manual
    recompute). Returns the freshly created snapshots as dicts.
    """
    query_wells = (wells if wells is not None
                   else db.query(models.Well).order_by(models.Well.id).all())
    created = []
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    for w in query_wells:
        alert = engines.portfolio_alert(w, db=db)
        if alert is None:
            continue
        last = crud.latest_well_alert(db, w.id)
        notify = SEVERITY_RANK[alert["severity"]] > _notified_rank(alert, last)
        row = models.WellAlert(
            well_id=w.id,
            computed_at=now,
            source=source,
            severity=alert["severity"],
            status=alert["status"],
            message=alert["message"],
            margin_pct=alert.get("margin_pct"),
            days_to_risk=alert.get("days_to_risk"),
            v_actual_ft_s=alert.get("v_actual_ft_s"),
            v_crit_ft_s=alert.get("v_crit_ft_s"),
            q_crit_mscfd=alert.get("q_crit_mscfd"),
            metastable_regime=alert.get("metastable_regime"),
            q_min_stable_mscfd=alert.get("q_min_stable_mscfd"),
            last_notified_severity=alert["severity"] if notify
            else (last.last_notified_severity if last else None))
        db.add(row)
        if notify:
            _notify(alert)
        out = dict(alert, computed_at=now)
        created.append(out)
    db.commit()
    return created


def has_owned_snapshots(db: Session, key) -> bool:
    return crud.latest_alerts(db, key, limit=1) != []


def latest_alert_dicts(db: Session, key, limit=200):
    """Latest snapshot per owned well, newest first, as plain dicts."""
    rows = crud.latest_alerts(db, key, limit=limit)
    return [_row_to_dict(r, w) for r, w in rows]


def _row_to_dict(row: models.WellAlert, well) -> dict:
    margin = row.margin_pct
    return {
        "well_id": row.well_id,
        "tag": well.tag,
        "severity": row.severity,
        "status": row.status,
        "message": row.message,
        "margin_pct": margin,
        "days_to_risk": row.days_to_risk,
        "v_actual_ft_s": row.v_actual_ft_s,
        "v_crit_ft_s": row.v_crit_ft_s,
        "q_crit_mscfd": row.q_crit_mscfd,
        "metastable_regime": row.metastable_regime,
        "q_min_stable_mscfd": row.q_min_stable_mscfd,
        "computed_at": row.computed_at,
    }