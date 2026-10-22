"""Step 6: alert. A flagged run is posted to Slack (and/or any webhook, e.g. a Sim
webhook-triggered workflow) the same way a failed run would be."""
from __future__ import annotations

import os

import httpx


def slack_text(report: dict) -> str:
    lines = [f":rotating_light: *Crosscheck flagged run* `{report['run_id']}`"
             + (f" ({report['workflow']})" if report.get("workflow") else ""),
             "The run finished green, but its answer contradicts its own tool outputs:"]
    for f in report["flags"][:5]:
        lines.append(f"• answer says *{f['actual']}*, tool says *{f['expected']}* "
                     f"(span `{f['span_id']}`, {f['evidence']})")
    if len(report["flags"]) > 5:
        lines.append(f"…and {len(report['flags']) - 5} more")
    return "\n".join(lines)


def send_alerts(report: dict) -> list[str]:
    """Returns the channels notified. Never raises: alerting must not break the check."""
    if report["verdict"] != "flag":
        return []
    sent = []
    slack = os.getenv("SLACK_WEBHOOK_URL")
    hook = os.getenv("CROSSCHECK_WEBHOOK_URL")
    try:
        if slack:
            httpx.post(slack, json={"text": slack_text(report)}, timeout=10).raise_for_status()
            sent.append("slack")
        if hook:
            httpx.post(hook, json=report, timeout=10).raise_for_status()
            sent.append("webhook")
    except httpx.HTTPError as e:
        sent.append(f"error: {e}")
    return sent
