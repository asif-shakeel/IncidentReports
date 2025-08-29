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

# ---------- County outbound (request) ----------

def send_request_email(to_email: str, subject: str, content: str,
                       incident_address: str = "", incident_datetime: str = "", county: str = ""):
    meta = f"\n\nIRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}"
    body_text = (content or "").rstrip() + meta

    body_html = f"""<!doctype html>
<html>
  <body style=\"font-family:Arial,Helvetica,sans-serif; line-height:1.4; color:#222; font-size:14px;\">
    <p>Please provide the incident report for the following details:</p>
    <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"border-collapse:collapse; margin-top:8px;\">
      <tr><td style=\"padding:2px 8px 2px 0; font-weight:bold;\">Address:</td><td>{incident_address}</td></tr>
      <tr><td style=\"padding:2px 8px 2px 0; font-weight:bold;\">Date/Time:</td><td>{incident_datetime}</td></tr>
      <tr><td style=\"padding:2px 8px 2px 0; font-weight:bold;\">County:</td><td>{county}</td></tr>
    </table>
    <p style=\"margin-top:16px;\">Thank you,</p>
    <p>Incident Report Hub</p>
    <div style=\"display:none; visibility:hidden; mso-hide:all;\">
      IRH_META: Address={incident_address} | DateTime={incident_datetime} | County={county}
    </div>
  </body>
</html>"""

    msg = Mail(from_email=Email(FROM_EMAIL), to_emails=[To(to_email)], subject=subject)
    msg.add_content(Content("text/plain", body_text))
    msg.add_content(Content("text/html", body_html))
    if REPLY_TO_EMAIL:
        msg.reply_to = Email(REPLY_TO_EMAIL)

    _sg().send(msg)
    log.info("[email] sent request to %s (reply_to=%s)", to_email, REPLY_TO_EMAIL)

# ---------- Forward inbound to requester (with attachments) ----------

def send_attachments_to_user(user_email: str, subject: str, body: str, files: list[tuple[str, bytes]]):
    names = ", ".join([n for n, _ in files]) if files else "(none)"
    text_part = (body or "Attached are the files we received.") + f"\n\nAttachments: {names}"

    rows = "".join([f"<li>{n}</li>" for n, _ in files])
    html_part = f"""<!doctype html>
<html>
  <body style=\"font-family:Arial,Helvetica,sans-serif; line-height:1.5; color:#222; font-size:14px;\">
    <p>We received a reply to your incident report request. The files are attached below.</p>
    <ul style=\"margin:8px 0 16px 20px;\">{rows}</ul>
    <p>If anything looks off, just reply to this email.</p>
  </body>
</html>"""

    msg = Mail(from_email=FROM_EMAIL, to_emails=user_email, subject=subject)
    msg.add_content(Content("text/plain", text_part))
    msg.add_content(Content("text/html", html_part))

    for name, data in files:
        att = Attachment()
        att.file_content = base64.b64encode(data).decode()
        att.file_type = "application/pdf" if name.lower().endswith(".pdf") else "application/octet-stream"
        att.file_name = name
        att.disposition = "attachment"
        msg.add_attachment(att)

    _sg().send(msg)
    log.info("[email] forwarded %d attachment(s) to %s", len(files), user_email)

# ---------- Notify requester when no attachments were found ----------

def send_alert_no_attachments(user_email: str, subject: str, body: str):
    text_part = body or "A reply was received but contained no attachments."
    html_part = f"""<!doctype html>
<html>
  <body style=\"font-family:Arial,Helvetica,sans-serif; line-height:1.5; color:#222; font-size:14px;\">
    <p>A reply was received but contained <strong>no attachments</strong>.</p>
    <p>{text_part}</p>
  </body>
</html>"""

    msg = Mail(from_email=FROM_EMAIL, to_emails=user_email, subject=subject)
    msg.add_content(Content("text/plain", text_part))
    msg.add_content(Content("text/html", html_part))
    _sg().send(msg)
    log.info("[email] sent no-attachment alert to %s", user_email)