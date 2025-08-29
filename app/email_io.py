# ================================
# FILE: app/email_io.py
# ================================
import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "request@repo.incidentreportshub.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "intake@repo.incidentreportshub.com")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "alert@repo.incidentreportshub.com")

log = logging.getLogger(__name__)


def send_request_email(
    to_email: str,
    subject: str,
    content: str,
    incident_address: str = "",
    incident_datetime: str = "",
    county: str = "",
):
    if not SENDGRID_API_KEY:
        log.error("[email] SENDGRID_API_KEY missing; cannot send")
        return

    plain_text = content
    html_content = f"""
    <p>Please provide the incident report for the following details:</p>
    <ul>
        <li><strong>Address:</strong> {incident_address}</li>
        <li><strong>Date/Time:</strong> {incident_datetime}</li>
        <li><strong>County:</strong> {county}</li>
    </ul>
    <hr>
    <p style="font-size:10px;color:#888;">IRH_META {incident_address}|{incident_datetime}|{county}</p>
    """

    message = Mail(
        from_email=Email(FROM_EMAIL),
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", plain_text),
        html_content=Content("text/html", html_content),
    )

    if REPLY_TO_EMAIL:
        message.reply_to = Email(REPLY_TO_EMAIL)

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        log.info("[email] sent request to %s, status=%s", to_email, response.status_code)
    except Exception as e:
        log.exception("[email] failed to send request: %s", str(e))


def send_attachments_to_user(user_email: str, attachments: list):
    if not SENDGRID_API_KEY:
        log.error("[email] SENDGRID_API_KEY missing; cannot send")
        return
    if not attachments:
        log.warning("[email] no attachments to send to %s", user_email)
        return

    message = Mail(
        from_email=Email(FROM_EMAIL),
        to_emails=To(user_email),
        subject="Incident Report Response",
        plain_text_content="Incident report(s) attached.",
    )

    for att in attachments:
        message.add_attachment(att)

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        log.info("[email] forwarded %d attachment(s) to %s, status=%s", len(attachments), user_email, response.status_code)
    except Exception as e:
        log.exception("[email] failed to forward attachments: %s", str(e))


def send_alert_no_attachments(user_email: str, incident_id: int):
    if not SENDGRID_API_KEY:
        log.error("[email] SENDGRID_API_KEY missing; cannot send")
        return

    subject = f"Incident Report Response (No Attachments) — Request #{incident_id}"
    plain_text = "A county replied but did not include any attachments."

    message = Mail(
        from_email=Email(FROM_EMAIL),
        to_emails=To(user_email),
        subject=subject,
        plain_text_content=plain_text,
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        log.info("[email] alert sent to %s, status=%s", user_email, response.status_code)
    except Exception as e:
        log.exception("[email] failed to send no-attachments alert: %s", str(e))