from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os
from dotenv import load_dotenv

load_dotenv()
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

message = Mail(
    from_email="request@incidentreporthub.com",
    to_emails="your_email@example.com",
    subject="Test Email",
    plain_text_content="Hello from SendGrid!"
)

try:
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    response = sg.send(message)
    print(response.status_code, response.body, response.headers)
except Exception as e:
    print("Error:", e)
