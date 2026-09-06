"""Pushes agent events to wherever you'll actually see them.

An agent that trades unattended is only trustworthy if it can reach you when
something happens. This posts to a webhook URL you choose - ntfy.sh for phone
push, or a Discord/Slack incoming webhook - so no account or API key of ours is
involved and you can change the destination without a redeploy.

Two rules shape everything here:

Notifying must never break trading. Every failure is swallowed and reported in
the return value instead of raised, because a webhook being down is not a
reason to stop managing positions.

Only send what's worth interrupting someone for. A routine "outside the trading
window" halt happens every day and would train you to ignore the alerts, which
is worse than having none.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import httpx

# Events that justify a notification. Routine stand-downs are deliberately
# absent - see the module docstring.
ALERT_EVENTS = {
    "agent_opened",        # the agent took a position
    "agent_risk_halt",     # a loss limit stopped it
    "agent_error",         # a run failed outright
    "agent_stale_data",    # market data went stale or unavailable
    "test",                # the "send test alert" button
}

TIMEOUT_SECONDS = float(os.getenv("NOTIFY_TIMEOUT_SECONDS", "6"))


def webhook_url(config: Optional[Dict[str, Any]] = None) -> str:
    """Per-user setting wins; the env var is a fallback for all users."""
    from_config = str((config or {}).get("notify_webhook") or "").strip()
    return from_config or os.getenv("NOTIFY_WEBHOOK_URL", "").strip()


def _payload_for(url: str, title: str, message: str) -> Dict[str, Any]:
    """Shape the request for whichever service the URL points at.

    ntfy wants a plain-text body with the title in a header. Discord wants
    'content', Slack wants 'text'. Sending all the common JSON keys at once
    means a generic webhook works without knowing what it is.
    """
    if "ntfy" in url:
        return {
            "content": message.encode("utf-8"),
            "headers": {"Title": title, "Content-Type": "text/plain; charset=utf-8"},
        }
    body = {
        "content": f"**{title}**\n{message}",   # Discord
        "text": f"*{title}*\n{message}",        # Slack
        "message": message,                     # generic
        "title": title,
    }
    return {"content": json.dumps(body).encode("utf-8"),
            "headers": {"Content-Type": "application/json"}}


def send(title: str, message: str, config: Optional[Dict[str, Any]] = None,
         event: str = "test") -> Dict[str, Any]:
    """Best-effort notification. Never raises."""
    if event not in ALERT_EVENTS:
        return {"sent": False, "reason": f"'{event}' is not an alerting event."}

    url = webhook_url(config)
    if not url:
        return {"sent": False, "reason": "No notification webhook configured."}
    if not url.lower().startswith("https://"):
        # Refuse plaintext so a misconfigured URL can't leak trade details.
        return {"sent": False, "reason": "Notification webhook must be an https:// URL."}

    try:
        req = _payload_for(url, title, message)
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            res = client.post(url, content=req["content"], headers=req["headers"])
        if res.status_code >= 400:
            return {"sent": False, "reason": f"Webhook returned {res.status_code}."}
        return {"sent": True, "status": res.status_code}
    except Exception as exc:
        # Deliberately swallowed: a dead webhook must not stop the agent.
        return {"sent": False, "reason": f"Could not reach the webhook: {exc}"}


def summarise_run(run: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Turn a run record into an alert, or None when it isn't worth sending."""
    if run.get("dry_run"):
        return None

    opened = run.get("opened") or []
    if opened:
        lines = [
            f"{o.get('pair')} {str(o.get('direction') or '').upper()} "
            f"@ {o.get('entry')} (stop {o.get('stop_loss')}, target {o.get('take_profit')}) "
            f"- {o.get('strategy')}, {o.get('confidence')}%"
            for o in opened
        ]
        return {
            "event": "agent_opened",
            "title": f"Agent opened {len(opened)} trade{'s' if len(opened) != 1 else ''}",
            "message": "\n".join(lines),
        }

    if run.get("halted"):
        reason = str(run.get("halt_reason") or "")
        if "loss limit" in reason.lower():
            return {"event": "agent_risk_halt", "title": "Agent stopped on a loss limit", "message": reason}
        # Every other halt is routine and stays quiet.
        return None

    stale = [s for s in (run.get("skipped") or [])
             if "market looks closed" in str(s.get("reason", "")).lower()
             or "fallback prices" in str(s.get("reason", "")).lower()]
    if stale and len(stale) == len(run.get("skipped") or []):
        # Only when it blocked the whole run, not one odd pair.
        return {
            "event": "agent_stale_data",
            "title": "Agent could not trade - market data problem",
            "message": stale[0].get("reason", "Market data unavailable."),
        }
    return None
