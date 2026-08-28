"""Notification adapter - Slack incoming webhook, zero dependencies.

The URL is read from SLACK_WEBHOOK_URL; when unset send_slack_message
is a silent no-op so the stack runs without external services.
"""

import json
import os
import urllib.request


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