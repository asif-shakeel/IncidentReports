# ================================
# FILE: app/email_io.py
# ================================
import os
import base64
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "request@repo.incidentreportshub.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "intake@repo.incidentreportshub.com")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "alert@repo.incidentreportshub.com")

log = logging.getLogger("uvicorn.error").getChild("email_io")


def _sg():
    if not SENDGRID_API_KEY:
        raise RuntimeError("Missing SENDGRID_API_KEY")
    return SendGridAPIClient(SENDGRID_API_KEY)


def send_request_email(
    to_email: str,
    subject: str,
    incident_address: str,
    incident_datetime: str,
    county: str,
):
    """Send the county request. One field per line (text & HTML) + hidden IRH_META."""
    plain_text = (
        "Please provide the incident report for the following details:\n"
        f"Address: {incident_address}\n"
        f"Date/Time: {incident_datetime}\n"
        f"County: {county}\n"
        f"\nIRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}"
    )

    html_content = f"""<!doctype html>
<html>
  <body style=\"font-family:Arial,Helvetica,sans-serif; line-height:1.4; color:#222; font-size:14px;\">
    <p>Please provide the incident report for the following details:</p>
    <p><strong>Address:</strong> {incident_address}</p>
    <p><strong>Date/Time:</strong> {incident_datetime}</p>
    <p><strong>County:</strong> {county}</p>
    <div style=\"display:none; visibility:hidden; mso-hide:all;\">IRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}</div>
  </body>
</html>"""

    msg = Mail(
        from_email=Email(FROM_EMAIL),
        to_emails=[To(to_email)],
        subject=subject,
        plain_text_content=Content("text/plain", plain_text),
        html_content=Content("text/html", html_content),
    )
    if REPLY_TO_EMAIL:
        msg.reply_to = Email(REPLY_TO_EMAIL)

    resp = _sg().send(msg)
    log.info("[email] sent request to %s status=%s", to_email, getattr(resp, "status_code", "?"))


def send_attachments_to_user(to_email: str, subject: str, body: str, files: list[dict]):
    """Forward attachments to the requester. files = [{path, filename, type}]"""
    msg = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject)
    msg.add_content(Content("text/plain", body or "Attached are the files we received."))

    if REPLY_TO_EMAIL:
        msg.reply_to = Email(REPLY_TO_EMAIL)

    for f in files:
        data = open(f["path"], "rb").read()
        encoded = base64.b64encode(data).decode()
        att = Attachment()
        att.file_content = encoded
        att.file_name = f["filename"]
        att.file_type = f.get("type", "application/octet-stream")
        att.disposition = "attachment"
        msg.add_attachment(att)

    resp = _sg().send(msg)
    log.info("[email] forwarded %d attachment(s) to %s status=%s", len(files), to_email, getattr(resp, "status_code", "?"))


def send_alert_no_attachments(to_email: str, subject: str, incident_address: str, incident_datetime: str, county: str):
    msg = Mail(from_email=FROM_EMAIL, to_emails=to_email or ALERT_EMAIL, subject=subject)
    plain = (
        "A reply was received but contained no attachments.\n\n"
        f"Address: {incident_address}\nDate/Time: {incident_datetime}\nCounty: {county}\n"
    )
    html = f"""<!doctype html>
<html><body style=\"font-family:Arial,Helvetica,sans-serif; line-height:1.5; color:#222; font-size:14px;\">
<p>A reply was received but contained <strong>no attachments</strong>.</p>
<p><strong>Address:</strong> {incident_address}<br>
<strong>Date/Time:</strong> {incident_datetime}<br>
<strong>County:</strong> {county}</p>
</body></html>"""
    msg.add_content(Content("text/plain", plain))
    msg.add_content(Content("text/html", html))
    if REPLY_TO_EMAIL:
        msg.reply_to = Email(REPLY_TO_EMAIL)
    resp = _sg().send(msg)
    log.info("[email] sent no-attachment alert to %s status=%s", to_email or ALERT_EMAIL, getattr(resp, "status_code", "?"))