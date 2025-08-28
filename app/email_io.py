# ================================
# FILE: app/email_io.py
# ================================
from app.config import SENDGRID_API_KEY, FROM_EMAIL, ALERT_EMAIL

# SendGrid helpers are imported only when needed to keep import cost low

def send_request_email(to_email: str, subject: str, content: str):
    if not SENDGRID_API_KEY:
        return
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    message = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=content)
    sg.send(message)

def send_attachments_to_user(recipient_email: str, subject: str, body_text: str, attachments):
    if not SENDGRID_API_KEY or not recipient_email or not attachments:
        return
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Attachment, Disposition
    import base64

    message = Mail(from_email=FROM_EMAIL, to_emails=recipient_email, subject=subject, plain_text_content=body_text)
    for att in attachments:
        encoded = base64.b64encode(att['content']).decode('utf-8')
        attach = Attachment()
        attach.file_content = encoded
        attach.file_type = att['content_type']
        attach.file_name = att['filename']
        attach.disposition = Disposition("attachment")
        try:
            message.add_attachment(attach)
        except Exception:
            message.attachment = attach
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)

def send_alert_no_attachments(subject: str, body_text: str):
    if not SENDGRID_API_KEY:
        return
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    alert = Mail(from_email=FROM_EMAIL, to_emails=ALERT_EMAIL, subject=subject, plain_text_content=body_text)
    sg.send(alert)