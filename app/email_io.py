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
    """Send the county request. One field per line (text & HTML) + IRH_META (hidden unless DEBUG_META=1)."""
    plain_text = (
        "Please provide the incident report for the following details:\n"
        f"Address: {incident_address}\n"
        f"Date/Time: {incident_datetime}\n"
        f"County: {county}\n"
        f"\nIRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}"
    )

    debug_meta = os.getenv("DEBUG_META", "0") == "1"
    meta_html_style = "" if debug_meta else "display:none; visibility:hidden; mso-hide:all;"

    html_content = f"""<!doctype html>
<html>
  <body style=\"font-family:Arial,Helvetica,sans-serif; line-height:1.4; color:#222; font-size:14px;\">
    <p>Please provide the incident report for the following details:</p>
    <p><strong>Address:</strong> {incident_address}</p>
    <p><strong>Date/Time:</strong> {incident_datetime}</p>
    <p><strong>County:</strong> {county}</p>
    <div style=\"{meta_html_style}\">IRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}</div>
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


# (unchanged) send_attachments_to_user + send_alert_no_attachments below...