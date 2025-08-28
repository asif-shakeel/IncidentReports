# ================================
# FILE: app/config.py
# ================================
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
FROM_EMAIL = os.getenv("FROM_EMAIL", "request@incidentreportshub.com")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "alert@incidentreportshub.com")
INBOUND_RPS = int(os.getenv("INBOUND_RPS", "5"))
WINDOW_SECS = int(os.getenv("INBOUND_WINDOW_SECS", "10"))

# County email CSV (lazy-loaded)
import csv

COUNTY_EMAIL_MAP = None

def get_county_email_map():
    global COUNTY_EMAIL_MAP
    if COUNTY_EMAIL_MAP is None:
        COUNTY_EMAIL_MAP = {}
        with open('ca_all_counties_fire_records_contacts_template.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                COUNTY_EMAIL_MAP[row['County']] = row['Request Email']
    return COUNTY_EMAIL_MAP