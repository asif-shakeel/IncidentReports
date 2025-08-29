
# =============================
# FILE: app/email_parser.py
# =============================
from __future__ import annotations
import os
import re
import logging
import time
import hashlib
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# ---------------- Runtime toggles ----------------
USE_LLM = os.getenv("PARSER_USE_LLM", "0") == "1"  # default OFF
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("PARSER_LLM_MODEL", "gpt-4o-mini")
LLM_MAX_CALLS_PER_MIN = int(os.getenv("LLM_MAX_CALLS_PER_MIN", "2"))

_CALLS = []  # timestamps in last 60s
_SEEN = set()  # hashes of cleaned bodies


def _may_call_llm(cleaned_text: str) -> bool:
    key = hashlib.sha256(cleaned_text.strip().encode("utf-8")).hexdigest()[:16]
    if key in _SEEN:
        logger.info("[parser] LLM skip: duplicate body")
        return False
    now = time.time()
    global _CALLS
    _CALLS = [t for t in _CALLS if now - t < 60]
    if len(_CALLS) >= LLM_MAX_CALLS_PER_MIN:
        logger.info("[parser] LLM skip: rate limited by app guard")
        return False
    _CALLS.append(now)
    _SEEN.add(key)
    return True

# ---------------- HTML -> text ----------------
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None


def html_to_text(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is None:
        txt = re.sub(r"<[^>]+>", " ", html)
    else:
        txt = BeautifulSoup(html, "html.parser").get_text(" ")
    try:
        from html import unescape
        txt = unescape(txt)
    except Exception:
        pass
    return txt

# ---------------- Cleaning ----------------
RE_QUOTE_SPLIT = re.compile(
    r"^\s*(On .* wrote:|From:\s.*|-----Original Message-----)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def clean_reply_body(body_text: str = "", body_html: str = "") -> str:
    raw = body_text or html_to_text(body_html) or ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    m = RE_QUOTE_SPLIT.search(raw)
    if m:
        raw = raw[: m.start()]

    lines = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith(">"):
            continue
        if s in ("--", "__"):
            break
        lines.append(s)
    cleaned = "\n".join(lines).strip()

    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    logger.info(f"[parser] body_clean[:200]={cleaned[:200]!r}")
    return cleaned

# ---------------- Extraction (regex first) ----------------
RE_ADDR = re.compile(r"^\s*>?\s*(Address|Location|Incident\s*Address)\s*[:\-]\s*(.+)$", re.IGNORECASE)
RE_DT   = re.compile(r"^\s*>?\s*(Date/Time|Date\s*Time|When|Incident\s*(Date|Time))\s*[:\-]\s*(.+)$", re.IGNORECASE)
RE_CNTY = re.compile(r"^\s*>?\s*(County|Jurisdiction|Agency)\s*[:\-]\s*(.+)$", re.IGNORECASE)


def extract_fields_from_body(cleaned: str) -> Tuple[str, str, str]:
    address = dt_str = county = None
    for line in cleaned.split("\n"):
        if address is None:
            ma = RE_ADDR.match(line)
            if ma:
                address = ma.group(2).strip()
        if dt_str is None:
            md = RE_DT.match(line)
            if md:
                dt_str = (md.group(md.lastindex) or "").strip()
        if county is None:
            mc = RE_CNTY.match(line)
            if mc:
                county = mc.group(2).strip()
    if not (address and dt_str and county):
        logger.info(f"[parser] regex_miss; cleaned[:200]={cleaned[:200]!r}")
    else:
        logger.info(f"[parser] regex_hit addr={address!r} dt={dt_str!r} county={county!r}")
    return address or "", dt_str or "", county or ""

# ---------------- Optional LLM fallback ----------------

def llm_extract_fields_once(cleaned_text: str) -> Tuple[str, str, str]:
    if not (USE_LLM and OPENAI_API_KEY):
        logger.info("[parser] LLM disabled or no API key; skipping")
        return "", "", ""
    try:
        import json
        import openai  # type: ignore
        openai.api_key = OPENAI_API_KEY
        prompt = (
            "Extract Address, Date/Time, and County from the email reply. "
            "Ignore quoted text and signatures. Respond ONLY as JSON with keys: address, datetime, county.\n\n"
            f"Email:\n{cleaned_text[:12000]}"
        )
        logger.info("[parser] invoking LLM fallback")
        resp = openai.ChatCompletion.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = resp["choices"][0]["message"]["content"].strip()
        data = json.loads(content)
        return data.get("address", ""), data.get("datetime", ""), data.get("county", "")
    except Exception as e:
        msg = str(e)
        if "429" in msg:
            logger.warning("[parser] LLM 429; skipping")
        else:
            logger.warning(f"[parser] LLM parse failed: {e}")
        return "", "", ""

# ---------------- Public entry ----------------

def parse_inbound_email(text: str, html: str, attachment_count: Optional[int] = None) -> Tuple[str, str, str]:
    """Return (address, dt_str, county). Regex first; optional LLM if missing."""
    body_clean = clean_reply_body(text, html)
    address, dt_str, county = extract_fields_from_body(body_clean)

    if not (address and dt_str and county) and _may_call_llm(body_clean):
        la, ld, lc = llm_extract_fields_once(body_clean)
        address = address or la
        dt_str = dt_str or ld
        county = county or lc

    return address or "", dt_str or "", county or ""

# # app/email_parser.py — enhanced parser (regex-first, optional LLM)
# # Exports: parse_inbound_email(text: str, html: str, attachment_count: int | None = None) -> tuple[str, str, str]
# # Notes: LLM is disabled by default via PARSER_USE_LLM=0. Enable when ready.

# from __future__ import annotations
# import os
# import re
# import logging
# import time
# import hashlib
# from typing import Tuple, Optional

# logger = logging.getLogger(__name__)

# # ---------------- Runtime toggles ----------------
# USE_LLM = os.getenv("PARSER_USE_LLM", "0") == "1"  # default OFF
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# LLM_MODEL = os.getenv("PARSER_LLM_MODEL", "gpt-4o-mini")
# LLM_MAX_CALLS_PER_MIN = int(os.getenv("LLM_MAX_CALLS_PER_MIN", "2"))

# # simple in-process throttle + dedupe
# _CALLS = []  # timestamps
# _SEEN = set()  # hashes of cleaned bodies


# def _may_call_llm(cleaned_text: str) -> bool:
#     key = hashlib.sha256(cleaned_text.strip().encode("utf-8")).hexdigest()[:16]
#     if key in _SEEN:
#         logger.info("[parser] LLM skip: duplicate body")
#         return False
#     now = time.time()
#     # drop entries older than 60s
#     global _CALLS
#     _CALLS = [t for t in _CALLS if now - t < 60]
#     if len(_CALLS) >= LLM_MAX_CALLS_PER_MIN:
#         logger.info("[parser] LLM skip: rate limited by app guard")
#         return False
#     _CALLS.append(now)
#     _SEEN.add(key)
#     return True


# # ---------------- HTML -> text ----------------
# try:
#     from bs4 import BeautifulSoup  # type: ignore
# except Exception:  # pragma: no cover
#     BeautifulSoup = None


# def html_to_text(html: str) -> str:
#     if not html:
#         return ""
#     if BeautifulSoup is None:
#         txt = re.sub(r"<[^>]+>", " ", html)
#     else:
#         txt = BeautifulSoup(html, "html.parser").get_text(" ")
#     try:
#         from html import unescape
#         txt = unescape(txt)
#     except Exception:
#         pass
#     return txt


# # ---------------- Cleaning ----------------
# RE_QUOTE_SPLIT = re.compile(
#     r"^\s*(On .* wrote:|From:\s.*|-----Original Message-----)\s*$",
#     re.IGNORECASE | re.MULTILINE,
# )


# def clean_reply_body(body_text: str = "", body_html: str = "") -> str:
#     raw = body_text or html_to_text(body_html) or ""
#     raw = raw.replace("\r\n", "\n").replace("\r", "\n")

#     # cut at first quote intro
#     m = RE_QUOTE_SPLIT.search(raw)
#     if m:
#         raw = raw[: m.start()]

#     lines = []
#     for line in raw.split("\n"):
#         s = line.strip()
#         if not s:
#             continue
#         if s.startswith(">"):
#             continue
#         if s in ("--", "__"):
#             break
#         lines.append(s)
#     cleaned = "\n".join(lines).strip()

#     # tidy bullets/whitespace
#     cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned, flags=re.MULTILINE)
#     cleaned = re.sub(r"[ \t]+", " ", cleaned)

#     logger.info(f"[parser] body_clean[:200]={cleaned[:200]!r}")
#     return cleaned


# # ---------------- Extraction (regex first) ----------------
# RE_ADDR = re.compile(r"^\s*>?\s*(Address|Location|Incident\s*Address)\s*[:\-]\s*(.+)$", re.IGNORECASE)
# RE_DT   = re.compile(r"^\s*>?\s*(Date/Time|Date\s*Time|When|Incident\s*(Date|Time))\s*[:\-]\s*(.+)$", re.IGNORECASE)
# RE_CNTY = re.compile(r"^\s*>?\s*(County|Jurisdiction|Agency)\s*[:\-]\s*(.+)$", re.IGNORECASE)


# def extract_fields_from_body(cleaned: str) -> Tuple[str, str, str]:
#     address = dt_str = county = None
#     for line in cleaned.split("\n"):
#         if address is None:
#             ma = RE_ADDR.match(line)
#             if ma:
#                 address = ma.group(2).strip()
#         if dt_str is None:
#             md = RE_DT.match(line)
#             if md:
#                 dt_str = (md.group(md.lastindex) or "").strip()
#         if county is None:
#             mc = RE_CNTY.match(line)
#             if mc:
#                 county = mc.group(2).strip()
#     if not (address and dt_str and county):
#         logger.info(f"[parser] regex_miss; cleaned[:200]={cleaned[:200]!r}")
#     else:
#         logger.info(f"[parser] regex_hit addr={address!r} dt={dt_str!r} county={county!r}")
#     return address or "", dt_str or "", county or ""


# # ---------------- Optional LLM fallback ----------------

# def llm_extract_fields_once(cleaned_text: str) -> Tuple[str, str, str]:
#     if not (USE_LLM and OPENAI_API_KEY):
#         logger.info("[parser] LLM disabled or no API key; skipping")
#         return "", "", ""
#     try:
#         import json
#         import openai  # type: ignore
#         openai.api_key = OPENAI_API_KEY
#         prompt = (
#             "Extract Address, Date/Time, and County from the email reply. "
#             "Ignore quoted text and signatures. Respond ONLY as JSON with keys: address, datetime, county.\n\n"
#             f"Email:\n{cleaned_text[:12000]}"
#         )
#         logger.info("[parser] invoking LLM fallback")
#         resp = openai.ChatCompletion.create(
#             model=LLM_MODEL,
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#         )
#         content = resp["choices"][0]["message"]["content"].strip()
#         data = json.loads(content)
#         return data.get("address", ""), data.get("datetime", ""), data.get("county", "")
#     except Exception as e:
#         msg = str(e)
#         if "429" in msg:
#             logger.warning("[parser] LLM 429; skipping")
#         else:
#             logger.warning(f"[parser] LLM parse failed: {e}")
#         return "", "", ""


# # ---------------- Public entry ----------------

# def parse_inbound_email(text: str, html: str, attachment_count: Optional[int] = None) -> Tuple[str, str, str]:
#     """Return (address, dt_str, county). Regex first; optional LLM if missing."""
#     body_clean = clean_reply_body(text, html)
#     address, dt_str, county = extract_fields_from_body(body_clean)

#     if not (address and dt_str and county) and _may_call_llm(body_clean):
#         la, ld, lc = llm_extract_fields_once(body_clean)
#         address = address or la
#         dt_str = dt_str or ld
#         county = county or lc

#     return address or "", dt_str or "", county or ""


# # Drop‑in parser module used by routes_inbound.py
# # Consistent variable names: returns (address, dt_str, county)
# # Includes optional LLM fallback guarded by PARSER_USE_LLM env var

# from __future__ import annotations
# import os
# import re
# import logging
# from typing import Tuple

# logger = logging.getLogger(__name__)

# # --- Runtime toggles ---
# # Default OFF in production; set PARSER_USE_LLM=1 to enable
# USE_LLM = os.getenv("PARSER_USE_LLM", "0") == "1"
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# LLM_MODEL = os.getenv("PARSER_LLM_MODEL", "gpt-4o-mini")

# # --- Quoted reply stripping ---
# RE_QUOTE_SPLIT = re.compile(
#     r"^\s*(On .* wrote:|From:\s.*|-----Original Message-----)\s*$",
#     re.IGNORECASE | re.MULTILINE,
# )

# try:
#     from bs4 import BeautifulSoup  # optional; we fall back if missing
# except Exception:  # pragma: no cover
#     BeautifulSoup = None


# def html_to_text(html: str) -> str:
#     if not html:
#         return ""
#     if BeautifulSoup is None:
#         # basic fallback: strip tags
#         txt = re.sub(r"<[^>]+>", " ", html)
#     else:
#         txt = BeautifulSoup(html, "html.parser").get_text(" ")
#     try:
#         from html import unescape
#         txt = unescape(txt)
#     except Exception:
#         pass
#     return txt


# def clean_reply_body(body_text: str = "", body_html: str = "") -> str:
#     raw = body_text or html_to_text(body_html) or ""
#     raw = raw.replace("\r\n", "\n").replace("\r", "\n")

#     # Cut anything after the first quote-intro line
#     m = RE_QUOTE_SPLIT.search(raw)
#     if m:
#         raw = raw[: m.start()]

#     lines = []
#     for line in raw.split("\n"):
#         s = line.strip()
#         if not s:
#             continue
#         if s.startswith(">"):
#             continue  # drop quoted lines
#         if s in ("--", "__"):
#             break  # signature separator
#         lines.append(s)
#     cleaned = "\n".join(lines).strip()
#     logger.info(f"[parser] body_clean[:200]={cleaned[:200]!r}")
#     return cleaned


# # --- Field extraction regex ---
# RE_ADDR = re.compile(r"^\s*>?\s*Address\s*[:\-]\s*(.+)$", re.IGNORECASE)
# RE_DT   = re.compile(r"^\s*>?\s*(Date/Time|Date\s*Time)\s*[:\-]\s*(.+)$", re.IGNORECASE)
# RE_CNTY = re.compile(r"^\s*>?\s*County\s*[:\-]\s*(.+)$", re.IGNORECASE)


# def extract_fields_from_body(cleaned: str) -> Tuple[str, str, str]:
#     address = dt_str = county = None
#     for line in cleaned.split("\n"):
#         if address is None:
#             ma = RE_ADDR.match(line)
#             if ma:
#                 address = ma.group(1).strip()
#         if dt_str is None:
#             md = RE_DT.match(line)
#             if md:
#                 dt_str = md.group(2).strip()
#         if county is None:
#             mc = RE_CNTY.match(line)
#             if mc:
#                 county = mc.group(1).strip()
#     if not (address and dt_str and county):
#         logger.info(f"[parser] regex_miss; cleaned[:200]={cleaned[:200]!r}")
#     else:
#         logger.info(f"[parser] regex_hit addr={address!r} dt={dt_str!r} county={county!r}")
#     return address or "", dt_str or "", county or ""


# # --- Optional LLM fallback (disabled by default) ---

# def llm_extract_fields_once(cleaned_text: str) -> Tuple[str, str, str]:
#     if not (USE_LLM and OPENAI_API_KEY):
#         logger.info("[parser] LLM disabled or no API key; skipping")
#         return "", "", ""
#     try:
#         # Lazy import so module loads without SDK present
#         import json
#         import openai  # type: ignore
#         openai.api_key = OPENAI_API_KEY
#         prompt = (
#             "Extract Address, Date/Time, and County from the email reply. "
#             "Ignore quoted text and signatures. Respond ONLY as JSON with keys: address, datetime, county.\n\n"
#             f"Email:\n{cleaned_text[:12000]}"
#         )
#         logger.info("[parser] invoking LLM fallback")
#         resp = openai.ChatCompletion.create(
#             model=LLM_MODEL,
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#         )
#         content = resp["choices"][0]["message"]["content"].strip()
#         data = json.loads(content)
#         return data.get("address", ""), data.get("datetime", ""), data.get("county", "")
#     except Exception as e:  # catches 429 and any SDK issues
#         logger.warning(f"[parser] LLM parse failed: {e}")
#         return "", "", ""


# # --- One public entry point used by routes_inbound.py ---

# def parse_inbound_email(text: str, html: str) -> Tuple[str, str, str]:
#     """Return (address, dt_str, county). Uses regex first; optional LLM on miss."""
#     body_clean = clean_reply_body(text, html)
#     address, dt_str, county = extract_fields_from_body(body_clean)

#     if not (address and dt_str and county):
#         # Try LLM if enabled
#         la, ld, lc = llm_extract_fields_once(body_clean)
#         address = address or la
#         dt_str = dt_str or ld
#         county = county or lc
#     return address or "", dt_str or "", county or ""


# import os
# import re
# import logging
# from html import unescape
# import requests

# try:
#     from bs4 import BeautifulSoup  # ensure beautifulsoup4 is in requirements.txt
# except ImportError:
#     BeautifulSoup = None

# logger = logging.getLogger(__name__)

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# # --- Cleaning helpers ---
# RE_QUOTE_SPLIT = re.compile(
#     r"^\s*(On .* wrote:|From:\s.*|-----Original Message-----)\s*$",
#     re.IGNORECASE | re.MULTILINE
# )

# RE_ADDR = re.compile(r"^\s*>?\s*Address\s*[:\-]\s*(.+)$", re.IGNORECASE)
# RE_DT   = re.compile(r"^\s*>?\s*(Date/Time|Date\s*Time)\s*[:\-]\s*(.+)$", re.IGNORECASE)
# RE_CNTY = re.compile(r"^\s*>?\s*County\s*[:\-]\s*(.+)$", re.IGNORECASE)

# def html_to_text(html: str) -> str:
#     if not html:
#         return ""
#     if BeautifulSoup is None:
#         return re.sub(r"<[^>]+>", " ", html)
#     return BeautifulSoup(html, "html.parser").get_text(" ")

# def clean_reply_body(body_text: str = "", body_html: str = "") -> str:
#     raw = body_text or html_to_text(body_html) or ""
#     raw = raw.replace("\r\n", "\n").replace("\r", "\n")

#     # cut quoted section
#     m = RE_QUOTE_SPLIT.search(raw)
#     if m:
#         raw = raw[:m.start()]

#     # drop quoted lines and signatures
#     lines = []
#     for line in raw.split("\n"):
#         s = line.strip()
#         if not s or s.startswith(">"):
#             continue
#         if s in ("--", "__"):
#             break
#         lines.append(s)
#     return "\n".join(lines).strip()

# # --- Regex extraction ---
# def extract_fields_from_body(cleaned: str):
#     addr = dt = county = None
#     for line in cleaned.split("\n"):
#         if not addr:
#             ma = RE_ADDR.match(line)
#             if ma: addr = ma.group(1).strip()
#         if not dt:
#             md = RE_DT.match(line)
#             if md: dt = md.group(2).strip()
#         if not county:
#             mc = RE_CNTY.match(line)
#             if mc: county = mc.group(1).strip()
#     return addr, dt, county

# # --- LLM fallback ---
# def call_openai_parser(body: str):
#     prompt = f"""
#     Extract Address, Date/Time, and County from the following email. Ignore quoted text and signatures.
#     Respond as JSON with keys: address, datetime, county.

#     Email:\n{body}
#     """

#     headers = {
#         "Authorization": f"Bearer {OPENAI_API_KEY}",
#         "Content-Type": "application/json"
#     }
#     data = {
#         "model": "gpt-4o-mini",  # adjust to model you’re using
#         "messages": [{"role": "user", "content": prompt}],
#         "temperature": 0
#     }
#     try:
#         resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=20)
#         resp.raise_for_status()
#         content = resp.json()["choices"][0]["message"]["content"]
#         # naive JSON parse (could add json.loads with try/except)
#         import json
#         return json.loads(content)
#     except Exception as e:
#         logger.error(f"LLM parse failed: {e}")
#         return {}

# # --- Main entrypoint ---
# def parse_inbound_email(body_text: str, body_html: str = ""):
#     cleaned = clean_reply_body(body_text, body_html)
#     address, dt_str, county = extract_fields_from_body(cleaned)

#     if not (address and dt_str and county) and OPENAI_API_KEY:
#         logger.info("[parser] falling back to LLM")
#         fields = call_openai_parser(body_text or body_html)
#         address = address or fields.get("address")
#         dt_str = dt_str or fields.get("datetime")
#         county = county or fields.get("county")

#     return address, dt_str, county
