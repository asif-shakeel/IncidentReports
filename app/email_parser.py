# ================================
# FILE: app/email_parser.py
# ================================
import re

def parse_inbound_email(text: str, html: str = ""):
    body = text or html or ""
    address = None
    dt = None
    county = None

    m = re.search(r"Address:\s*(.*)", body, re.I)
    if m:
        address = m.group(1).strip()

    m = re.search(r"Date/Time:\s*(.*)", body, re.I)
    if m:
        dt = m.group(1).strip()

    m = re.search(r"County:\s*(.*)", body, re.I)
    if m:
        county = m.group(1).strip()

    return address, dt, county