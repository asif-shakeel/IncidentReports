# ================================
# FILE: app/email_parser.py
# ================================
import os
import re
import json
import logging

logger = logging.getLogger("uvicorn.error").getChild("email_parser")

# behavior control
MODE = os.getenv("PARSER_MODE", "regex_first").lower()  # regex_first (default) | llm_only
USE_LLM = os.getenv("PARSER_USE_LLM", "0") == "1"  # used only if MODE=regex_first
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Prefer IRH_META first (DOTALL; county stops at '<' or end)
RE_META = re.compile(
    r"IRH_META:\s*Address=(.*?)\s*\|\s*DateTime=(.*?)\s*\|\s*County=(.*?)(?:<|$)",
    re.I | re.S,
)
# Label patterns that stop at next label or end
RE_ADDR = re.compile(r"Address\s*:\s*(.+?)(?=\s*(?:Date/Time\s*:|County\s*:|$))", re.I | re.S)
RE_DT   = re.compile(r"(?:Date/Time|Datetime)\s*:\s*(.+?)(?=\s*(?:County\s*:|$))", re.I | re.S)
RE_CNTY = re.compile(r"County\s*:\s*(.+?)\s*$", re.I | re.S)


def _strip_quotes(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        if ln.lstrip().startswith(">"):
            continue
        out.append(ln)
    return "\n".join(out)


def _llm_extract(text: str):
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "Extract Address, DateTime, County from this email body. "
        "Return ONLY strict JSON with keys: address, datetime, county. "
        "Datetime should be 'YYYY-MM-DD HH:MM' 24h if present.\n\n" + (text or "")
    )
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    out = resp.choices[0].message.content or "{}"
    data = json.loads(out)
    return (data.get("address", ""), data.get("datetime", ""), data.get("county", ""))


def parse_inbound_email(text: str, html: str = ""):
    # llm_only mode: skip regex/IRH_META entirely
    if MODE == "llm_only":
        if not OPENAI_API_KEY:
            logger.info("[parser] llm_only but no OPENAI_API_KEY; returning blanks")
            return "", "", ""
        try:
            a, d, c = _llm_extract(text)
            logger.info("[parser] llm_only hit")
            return a, d, c
        except Exception as e:
            logger.warning(f"[parser] llm_only failed: {e}")
            return "", "", ""

    # regex_first mode (default)
    # 1) IRH_META from either part
    for src in (text or "", html or ""):
        m = RE_META.search(src)
        if m:
            a, d, c = (s.strip() for s in m.groups())
            logger.info("[parser] meta_hit")
            return a, d, c

    # 2) Labels on raw text
    body = (text or "").strip()
    a = RE_ADDR.search(body); d = RE_DT.search(body); c = RE_CNTY.search(body)
    if a and d and c:
        logger.info("[parser] regex_hit (raw)")
        return a.group(1).strip(), d.group(1).strip(), c.group(1).strip()

    # 3) Dequote and try again
    cleaned = _strip_quotes(text or "")
    a = RE_ADDR.search(cleaned); d = RE_DT.search(cleaned); c = RE_CNTY.search(cleaned)
    if a and d and c:
        logger.info("[parser] regex_hit (dequoted)")
        return a.group(1).strip(), d.group(1).strip(), c.group(1).strip()

    # 4) Optional LLM fallback
    if USE_LLM and OPENAI_API_KEY:
        try:
            a, d, c = _llm_extract(text)
            logger.info("[parser] llm_fallback hit")
            return a, d, c
        except Exception as e:
            logger.warning(f"[parser] LLM fallback failed: {e}")

    logger.info("[parser] no hit; returning blanks")
    return "", "", ""