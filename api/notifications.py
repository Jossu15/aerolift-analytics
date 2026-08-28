"""Notification adapters - Slack incoming webhook + SMTP email, no deps.

Slack: URL read from SLACK_WEBHOOK_URL; unset -> no-op.
Email: SMTP settings read from EMAIL_* env vars; unset -> no-op.
Both return False (never raise): alert persistence must not break on
fan-out.
"""

import json
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText


def slack_webhook_url():
    return os.environ.get("SLACK_WEBHOOK_URL", "").strip()


def send_slack_message(text: str) -> bool:
    """POST a plain-text message to the configured Slack webhook.

    Returns False (without raising) when no webhook is configured or
    the call fails - alert persistence must never break on fan-out.
    """
    url = slack_webhook_url()
    if not url:
        return False
    payload = json.dumps({"text": text, "mrkdwn": True,
                          "username": "AeroLift Alerts"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def smtp_settings():
    """SMTP config dict from EMAIL_*, or None when disabled.

    EMAIL_SMTP_HOST, EMAIL_SMTP_PORT (587), EMAIL_SMTP_USER,
    EMAIL_SMTP_PASSWORD, EMAIL_FROM and EMAIL_TO (comma-separated)
    turn the adapter on; EMAIL_TLS=1 forces STARTTLS. Without a host
    or recipients the adapter stays a no-op, same as Slack.
    """
    host = os.environ.get("EMAIL_SMTP_HOST", "").strip()
    if not host:
        return None
    to_addrs = [a.strip() for a in
                os.environ.get("EMAIL_TO", "").split(",") if a.strip()]
    from_addr = os.environ.get("EMAIL_FROM", "").strip()
    if not from_addr or not to_addrs:
        return None
    tls = os.environ.get("EMAIL_TLS", "1").lower() not in ("0", "false", "no")
    return {
        "host": host,
        "port": int(os.environ.get("EMAIL_SMTP_PORT", "587")),
        "user": os.environ.get("EMAIL_SMTP_USER", "").strip(),
        "password": os.environ.get("EMAIL_SMTP_PASSWORD", ""),
        "from_addr": from_addr,
        "to_addrs": to_addrs,
        "tls": tls,
    }


def send_email_message(subject: str, body: str) -> bool:
    """Send a plain-text email through the configured SMTP server.

    Returns False (without raising) when email is not configured or the
    call fails - alert persistence must never break on fan-out.
    """
    cfg = smtp_settings()
    if not cfg:
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = ", ".join(cfg["to_addrs"])
    try:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
        try:
            if cfg["tls"]:
                server.starttls()
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_addr"], cfg["to_addrs"],
                            msg.as_string())
        finally:
            server.quit()
        return True
    except Exception:
        return False