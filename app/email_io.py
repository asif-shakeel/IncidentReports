# ================================
# FILE: app/email_io.py
# ================================
import os, base64, logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment

FROM_EMAIL     = os.getenv("FROM_EMAIL", "request@repo.incidentreportshub.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "intake@repo.incidentreportshub.com")

log = logging.getLogger("uvicorn.error").getChild("email_io")

def _sg():
    key = os.getenv("SENDGRID_API_KEY")
    if not key:
        raise RuntimeError("Missing SENDGRID_API_KEY")
    return SendGridAPIClient(key)

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
    incident_address: str = "",
    incident_datetime: str = "",
    county: str = "",
):
    if not SENDGRID_API_KEY:
        log.error("[email] SENDGRID_API_KEY missing; cannot send")
        return

    plain_text = (
        "Please provide the incident report for the following details:\n"
        f"Address: {incident_address}\n"
        f"Date/Time: {incident_datetime}\n"
        f"County: {county}\n"
    )

    html_content = f"""
    <p>Please provide the incident report for the following details:</p>
    <p><strong>Address:</strong> {incident_address}</p>
    <p><strong>Date/Time:</strong> {incident_datetime}</p>
    <p><strong>County:</strong> {county}</p>
    <hr>
    <p style=\"font-size:10px;color:#888;\">IRH_META Address={incident_address} | DateTime={incident_datetime} | County={county}</p>
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



def send_attachments_to_user(user_email: str, subject: str, body: str, files: list[tuple[str, bytes]]):
    names = ", ".join([n for n, _ in files]) if files else "(none)"
    text_part = (body or "Attached are the files we received.") + f"\n\nAttachments: {names}"

    rows = "".join([f"<li>{n}</li>" for n, _ in files])
    html_part = f"""<!doctype html>
<html>
  <body style="font-family:Arial,Helvetica,sans-serif; line-height:1.5; color:#222; font-size:14px;">
    <p>We received a reply to your incident report request. The files are attached below.</p>
    <ul style="margin:8px 0 16px 20px;">{rows}</ul>
    <p>If anything looks off, just reply to this email.</p>
  </body>
</html>"""

    msg = Mail(from_email=FROM_EMAIL, to_emails=user_email, subject=subject)
    msg.add_content(Content("text/plain", text_part))
    msg.add_content(Content("text/html",  html_part))

    for name, data in files:
        att = Attachment()
        att.file_content = base64.b64encode(data).decode()
        att.file_type = "application/pdf" if name.lower().endswith(".pdf") else "application/octet-stream"
        att.file_name = name
        att.disposition = "attachment"
        msg.add_attachment(att)

    resp = _sg().send(msg)
    log.info("[email] forwarded %d attachment(s) to %s status=%s",
             len(files), user_email, getattr(resp, "status_code", "?"))

def send_alert_no_attachments(user_email: str, subject: str, body: str):
    text_part = body or "A reply was received but contained no attachments."
    html_part = f"""<!doctype html>
<html>
  <body style="font-family:Arial,Helvetica,sans-serif; line-height:1.5; color:#222; font-size:14px;">
    <p>A reply was received but contained <strong>no attachments</strong>.</p>
    <p>{text_part}</p>
  </body>
</html>"""

    msg = Mail(from_email=FROM_EMAIL, to_emails=user_email, subject=subject)
    msg.add_content(Content("text/plain", text_part))
    msg.add_content(Content("text/html",  html_part))
    resp = _sg().send(msg)
    log.info("[email] sent no-attachment alert to %s status=%s",
             user_email, getattr(resp, "status_code", "?"))
