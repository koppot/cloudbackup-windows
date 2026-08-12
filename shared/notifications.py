import smtplib
from email.message import EmailMessage
import urllib.request
import urllib.error
import json
from typing import Optional

def send_notification(subject: str, body: str, db, logger=None) -> None:
    """Send notifications via Email and Webhook if configured in the database."""
    # Attempt email
    smtp_host = db.get_setting('smtp_host')
    smtp_port = db.get_setting('smtp_port')
    smtp_user = db.get_setting('smtp_user')
    smtp_pass = db.get_setting('smtp_pass')
    smtp_from = db.get_setting('smtp_from')
    smtp_to = db.get_setting('smtp_to')
    
    if smtp_host and smtp_to:
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = subject
            msg['From'] = smtp_from or smtp_user or 'adc-backup@localhost'
            msg['To'] = smtp_to
            
            port = int(smtp_port) if smtp_port else 25
            if port == 465:
                server = smtplib.SMTP_SSL(smtp_host, port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_host, port, timeout=10)
                if port == 587:
                    server.starttls()
                    
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
                
            server.send_message(msg)
            server.quit()
            if logger:
                logger.info(f"Email notification sent to {smtp_to}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to send email notification: {e}")
                
    # Attempt webhook
    webhook_url = db.get_setting('notify_webhook')
    if webhook_url:
        try:
            payload = json.dumps({'text': f"{subject}\n\n{body}"}).encode('utf-8')
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if logger:
                    logger.info(f"Webhook notification sent (status: {response.status})")
        except Exception as e:
            if logger:
                logger.error(f"Failed to send webhook notification: {e}")
