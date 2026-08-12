"""
linux/notifier.py — Email SMTP and webhook notification dispatcher.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

import requests

log = logging.getLogger(__name__)


def notify(subject: str, body: str, settings: Optional[dict] = None) -> None:
    """Send notifications via all configured channels."""
    s = settings or {}
    _send_webhook(subject, body, s)
    _send_email(subject, body, s)


def _send_webhook(subject: str, body: str, settings: dict) -> None:
    url = settings.get("notify_webhook_url", "").strip()
    if not url:
        return
    try:
        payload = {"text": f"*{subject}*\n{body}"}
        # Support Slack/Discord: Discord uses 'content', Slack uses 'text'
        if "discord" in url:
            payload = {"content": f"**{subject}**\n{body}"}
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Webhook notification sent to %s", url[:50])
    except Exception as exc:
        log.warning("Webhook notification failed: %s", exc)


def _send_email(subject: str, body: str, settings: dict) -> None:
    smtp_host = settings.get("notify_email_smtp_host", "").strip()
    if not smtp_host:
        return
    smtp_port = int(settings.get("notify_email_smtp_port", "587") or "587")
    smtp_user = settings.get("notify_email_smtp_user", "").strip()
    smtp_pass = settings.get("notify_email_smtp_pass", "").strip()
    from_addr = settings.get("notify_email_from", smtp_user).strip()
    to_addr = settings.get("notify_email_to", "").strip()
    if not to_addr:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(body)
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log.info("Email notification sent to %s", to_addr)
    except Exception as exc:
        log.warning("Email notification failed: %s", exc)
