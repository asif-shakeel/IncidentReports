# ================================
# FILE: app/email_parser.py
# ================================
import os, re, json, logging
logger = logging.getLogger("uvicorn.error").getChild("email_parser")

USE_LLM = os.getenv("PARSER_USE_LLM", "0") == "1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Strict IRH_META (with colon after IRH_META)
_re_meta = re.compile(
    r"IRH_META:\s*Address=(.*?)\s*\|\s*DateTime=(.*?)\s*\|\s*County=(.*)",
    re.I
)

# Label patterns — stop each field at the next known label or end
_re_addr = re.compile(r"Address\s*:\s*(.+?)(?=\s*(?:Date/Time\s*:|County\s*:|$))", re.I | re.S)
_re_dt   = re.compile(r"(?:Date/Time|Datetime)\s*:\s*(.+?)(?=\s*(?:County\s*:|$))", re.I | re.S)
_re_cnty = re.compile(r"County\s*:\s*(.+?)\s*$", re.I | re.S)

def _strip_quotes(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        if ln.strip().startswith(">"):
            continue
        lines.append(ln)
    return "\n".join(lines)

def parse_inbound_email(text: str, html: str = ""):
    # 1) IRH_META wins
    for src in (text or "", html or ""):
        m = _re_meta.search(src)
        if m:
            a, d, c = (s.strip() for s in m.groups())
            logger.info("[parser] meta_hit")
            return a, d, c

    # 2) Try labels on raw text (handles single-line flattening)
    body = (text or "").strip()
    a = _re_addr.search(body)
    d = _re_dt.search(body)
    c = _re_cnty.search(body)
    if a and d and c:
        logger.info("[parser] regex_hit (raw)")
        return a.group(1).strip(), d.group(1).strip(), c.group(1).strip()

    # 3) Dequoted (strip '>') if the client quoted our original
    cleaned = _strip_quotes(text or "")
    a = _re_addr.search(cleaned)
    d = _re_dt.search(cleaned)
    c = _re_cnty.search(cleaned)
    if a and d and c:
        logger.info("[parser] regex_hit (dequoted)")
        return a.group(1).strip(), d.group(1).strip(), c.group(1).strip()

    # 4) Optional LLM fallback (disabled by default)
    if USE_LLM and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            prompt = (
                "Extract Address, DateTime, County from this email body. "
                "Return strict JSON with keys: address, datetime, county.\n\n" + (text or "")
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            out = resp.choices[0].message.content
            data = json.loads(out)
            return data.get("address",""), data.get("datetime",""), data.get("county","")
        except Exception as e:
            logger.warning(f"[parser] LLM fallback failed: {e}")

    logger.info("[parser] no hit; returning blanks")
    return "", "", ""
