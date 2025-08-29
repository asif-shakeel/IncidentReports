# ================================
# FILE: app/email_io.py
# ================================
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment
from app.config import SENDGRID_API_KEY, FROM_EMAIL, REPLY_TO_EMAIL
import base64

sg = SendGridAPIClient(SENDGRID_API_KEY) if SENDGRID_API_KEY else None

def send_request_email(to_email: str, subject: str, content: str):
    if not sg:
        return
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=content,
    )
    message.reply_to = Email(REPLY_TO_EMAIL)
    sg.send(message)

def send_attachments_to_user(user_email: str, subject: str, body: str, files: list):
    if not sg:
        return
    message = Mail(from_email=FROM_EMAIL, to_emails=user_email, subject=subject, plain_text_content=body)
    for file in files:
        with open(file, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        attachment = Attachment()
        attachment.file_content = encoded
        attachment.file_type = "application/pdf"
        attachment.file_name = file
        attachment.disposition = "attachment"
        message.add_attachment(attachment)
    sg.send(message)

def send_alert_no_attachments(user_email: str, subject: str, body: str):
    if not sg:
        return
    message = Mail(from_email=FROM_EMAIL, to_emails=user_email, subject=subject, plain_text_content=body)
    sg.send(message)