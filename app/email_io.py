# =============================
# FILE: app/email_io.py
# =============================
import os
import base64
from typing import List, Tuple
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, Attachment, Disposition, FileContent, FileName, FileType

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "request@repo.incidentreportshub.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "intake@repo.incidentreportshub.com")


def send_request_email(
    to_email: str,
    subject: str,
    content: str,
    *,
    incident_address: str | None = None,
    incident_datetime: str | None = None,
    county: str | None = None,
) -> bool:
    """
    Sends the outbound request email with optional machine-readable headers.
    Adds Reply-To so replies hit your SendGrid Inbound Parse subdomain.
    """
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set")

    sg = SendGridAPIClient(SENDGRID_API_KEY)

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=content,
    )
    message.reply_to = Email(REPLY_TO_EMAIL)

    headers: dict[str, str] = {}
    if incident_address:
        headers["X-IRH-Address"] = incident_address
    if incident_datetime:
        headers["X-IRH-DateTime"] = incident_datetime
    if county:
        headers["X-IRH-County"] = county
    if headers:
        message.headers = headers

    resp = sg.send(message)
    if resp.status_code != 202:
        raise RuntimeError(f"Failed to send email: {resp.status_code} {resp.body}")
    return True


def send_attachments_to_user(
    to_email: str,
    subject: str,
    body_text: str,
    attachments: List[Tuple[str, bytes]],
) -> bool:
    """Send an email to a user with binary attachments."""
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set")
    sg = SendGridAPIClient(SENDGRID_API_KEY)

    m = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=body_text)
    m.reply_to = Email(REPLY_TO_EMAIL)

    for filename, content in attachments:
        b64 = base64.b64encode(content).decode("utf-8")
        att = Attachment(
            FileContent(b64),
            FileName(filename),
            FileType("application/octet-stream"),
            Disposition("attachment"),
        )
        m.add_attachment(att)

    resp = sg.send(m)
    if resp.status_code != 202:
        raise RuntimeError(f"Failed to send email with attachments: {resp.status_code} {resp.body}")
    return True


def send_alert_no_attachments(to_email: str, subject: str, body_text: str) -> bool:
    """Send a notification when no attachments were found."""
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set")
    sg = SendGridAPIClient(SENDGRID_API_KEY)

    m = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=body_text)
    m.reply_to = Email(REPLY_TO_EMAIL)

    resp = sg.send(m)
    if resp.status_code != 202:
        raise RuntimeError(f"Failed to send email: {resp.status_code} {resp.body}")
    return True

# # ================================
# # FILE: app/email_io.py
# # ================================
# from app.config import SENDGRID_API_KEY, FROM_EMAIL, ALERT_EMAIL, REPLY_TO_EMAIL
# import os
# from sendgrid import SendGridAPIClient
# from sendgrid.helpers.mail import Mail, Email  # Email works for reply_to too

# # SendGrid helpers are imported only when needed to keep import cost low

# # def send_request_email(to_email: str, subject: str, content: str):
# #     if not SENDGRID_API_KEY:
# #         return
# #     from sendgrid import SendGridAPIClient
# #     from sendgrid.helpers.mail import Mail
# #     sg = SendGridAPIClient(SENDGRID_API_KEY)
# #     message = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=content)
# #     sg.send(message)



# def send_request_email(to_email: str, subject: str, content: str):
#     if not SENDGRID_API_KEY:
#         raise RuntimeError("SENDGRID_API_KEY is not set")

#     sg = SendGridAPIClient(SENDGRID_API_KEY)

#     message = Mail(
#         from_email=FROM_EMAIL,
#         to_emails=to_email,
#         subject=subject,
#         plain_text_content=content,
#     )
#     # set Reply-To so replies go to your parse subdomain
#     message.reply_to = Email(REPLY_TO_EMAIL)

#     # # If you have these variables in scope when sending:
#     # # incident_address, incident_datetime, county
#     # message.headers = {
#     #     "X-IRH-Address": incident_address,
#     #     "X-IRH-DateTime": incident_datetime,
#     #     "X-IRH-County": county,
#     # }
#     # # send
#     response = sg.send(message)
#     # (optional) sanity log / check
#     if response.status_code != 202:
#         raise RuntimeError(f"Failed to send email: {response.status_code} {response.body}")
#     return True

# def send_attachments_to_user(recipient_email: str, subject: str, body_text: str, attachments):
#     if not SENDGRID_API_KEY or not recipient_email or not attachments:
#         return
#     from sendgrid import SendGridAPIClient
#     from sendgrid.helpers.mail import Mail, Attachment, Disposition
#     import base64

#     message = Mail(from_email=FROM_EMAIL, to_emails=recipient_email, subject=subject, plain_text_content=body_text)
#     for att in attachments:
#         encoded = base64.b64encode(att['content']).decode('utf-8')
#         attach = Attachment()
#         attach.file_content = encoded
#         attach.file_type = att['content_type']
#         attach.file_name = att['filename']
#         attach.disposition = Disposition("attachment")
#         try:
#             message.add_attachment(attach)
#         except Exception:
#             message.attachment = attach
#     sg = SendGridAPIClient(SENDGRID_API_KEY)
#     sg.send(message)

# def send_alert_no_attachments(subject: str, body_text: str):
#     if not SENDGRID_API_KEY:
#         return
#     from sendgrid import SendGridAPIClient
#     from sendgrid.helpers.mail import Mail
#     sg = SendGridAPIClient(SENDGRID_API_KEY)
#     alert = Mail(from_email=FROM_EMAIL, to_emails=ALERT_EMAIL, subject=subject, plain_text_content=body_text)
#     sg.send(alert)