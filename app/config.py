# ================================
# FILE: app/config.py
# ================================
import os, json
from pathlib import Path
from dotenv import load_dotenv

root_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=root_env, override=True)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
FROM_EMAIL = os.getenv("FROM_EMAIL", "request@repo.incidentreportshub.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "intake@repo.incidentreportshub.com")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "alert@repo.incidentreportshub.com")
INBOUND_RPS = int(os.getenv("INBOUND_RPS", "5"))
WINDOW_SECS = int(os.getenv("INBOUND_WINDOW_SECS", "10"))

SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

COUNTY_EMAIL_MAP = os.getenv("COUNTY_EMAIL_MAP")

def get_county_email_map():
    if COUNTY_EMAIL_MAP:
        try:
            return json.loads(COUNTY_EMAIL_MAP)
        except Exception:
            pass
    return {}