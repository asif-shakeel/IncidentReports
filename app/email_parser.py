import os
import re
import logging
from html import unescape
import requests

try:
    from bs4 import BeautifulSoup  # ensure beautifulsoup4 is in requirements.txt
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Cleaning helpers ---
RE_QUOTE_SPLIT = re.compile(
    r"^\s*(On .* wrote:|From:\s.*|-----Original Message-----)\s*$",
    re.IGNORECASE | re.MULTILINE
)

RE_ADDR = re.compile(r"^\s*>?\s*Address\s*[:\-]\s*(.+)$", re.IGNORECASE)
RE_DT   = re.compile(r"^\s*>?\s*(Date/Time|Date\s*Time)\s*[:\-]\s*(.+)$", re.IGNORECASE)
RE_CNTY = re.compile(r"^\s*>?\s*County\s*[:\-]\s*(.+)$", re.IGNORECASE)

def html_to_text(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is None:
        return re.sub(r"<[^>]+>", " ", html)
    return BeautifulSoup(html, "html.parser").get_text(" ")

def clean_reply_body(body_text: str = "", body_html: str = "") -> str:
    raw = body_text or html_to_text(body_html) or ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # cut quoted section
    m = RE_QUOTE_SPLIT.search(raw)
    if m:
        raw = raw[:m.start()]

    # drop quoted lines and signatures
    lines = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        if s in ("--", "__"):
            break
        lines.append(s)
    return "\n".join(lines).strip()

# --- Regex extraction ---
def extract_fields_from_body(cleaned: str):
    addr = dt = county = None
    for line in cleaned.split("\n"):
        if not addr:
            ma = RE_ADDR.match(line)
            if ma: addr = ma.group(1).strip()
        if not dt:
            md = RE_DT.match(line)
            if md: dt = md.group(2).strip()
        if not county:
            mc = RE_CNTY.match(line)
            if mc: county = mc.group(1).strip()
    return addr, dt, county

# --- LLM fallback ---
def call_openai_parser(body: str):
    prompt = f"""
    Extract Address, Date/Time, and County from the following email. Ignore quoted text and signatures.
    Respond as JSON with keys: address, datetime, county.

    Email:\n{body}
    """

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4o-mini",  # adjust to model you’re using
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }
    try:
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=20)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # naive JSON parse (could add json.loads with try/except)
        import json
        return json.loads(content)
    except Exception as e:
        logger.error(f"LLM parse failed: {e}")
        return {}

# --- Main entrypoint ---
def parse_inbound_email(body_text: str, body_html: str = ""):
    cleaned = clean_reply_body(body_text, body_html)
    address, dt_str, county = extract_fields_from_body(cleaned)

    if not (address and dt_str and county) and OPENAI_API_KEY:
        logger.info("[parser] falling back to LLM")
        fields = call_openai_parser(body_text or body_html)
        address = address or fields.get("address")
        dt_str = dt_str or fields.get("datetime")
        county = county or fields.get("county")

    return address, dt_str, county
