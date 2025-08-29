# =============================
# FILE: app/email_io.py
# =============================
import os, base64, logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment
from app.config import FROM_EMAIL, REPLY_TO_EMAIL

log = logging.getLogger("uvicorn.error").getChild("email_io")

def _sg():
    key = os.getenv("SENDGRID_API_KEY")
    if not key:
        raise RuntimeError("Missing SENDGRID_API_KEY")
    return SendGridAPIClient(key)

def send_request_email(to_email: str, subject: str, content: str,
                       incident_address: str = "", incident_datetime: str = "", county: str = ""):
    """
    Sends the initial county request and appends IRH_META so replies can be parsed reliably.
    """
    meta = f"\n\nIRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}"
    body = (content or "").rstrip() + meta

    msg = Mail(
        from_email=Email(FROM_EMAIL),
        to_emails=[To(to_email)],
        subject=subject,
        plain_text_content=Content("text/plain", body),
    )
    if REPLY_TO_EMAIL:
        msg.reply_to = Email(REPLY_TO_EMAIL)

    _sg().send(msg)
    log.info("[email] sent request to %s (reply_to=%s)", to_email, REPLY_TO_EMAIL)

def send_attachments_to_user(to_email: str, subject: str, body: str, files: list[tuple[str, bytes]]):
    """
    Forward inbound attachments to the requester. `files` is a list of (name, bytes).
    """
    msg = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=body)
    for name, data in files:
        att = Attachment()
        att.file_content = base64.b64encode(data).decode()
        att.file_type = "application/pdf" if name.lower().endswith(".pdf") else "application/octet-stream"
        att.file_name = name
        att.disposition = "attachment"
        msg.add_attachment(att)
    _sg().send(msg)
    log.info("[email] forwarded %d attachment(s) to %s", len(files), to_email)

def send_alert_no_attachments(to_email: str, subject: str, body: str):
    msg = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=body)
    _sg().send(msg)
    log.info("[email] sent no-attachment alert to %s", to_email)
