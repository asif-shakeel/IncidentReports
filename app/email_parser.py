# =============================
# FILE: app/email_parser.py
# =============================
import os, re, json, logging
logger = logging.getLogger("uvicorn.error").getChild("email_parser")

# Optional LLM fallback toggle (keep off unless you have quota)
USE_LLM = os.getenv("PARSER_USE_LLM", "0") == "1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Regexes
_re_addr = re.compile(r"(?:^|\n)Address\s*:\s*(.+)", re.I)
_re_dt   = re.compile(r"(?:^|\n)(?:Date/Time|Datetime)\s*:\s*([\w: \-/]+)", re.I)
_re_cnty = re.compile(r"(?:^|\n)County\s*:\s*(.+)", re.I)
# From our outbound footer
_re_meta = re.compile(r"IRH_META:\s*Address=([^|]+)\|\s*DateTime=([^|]+)\|\s*County=(.+)$", re.I)

def _strip_quotes(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        if ln.strip().startswith(">"):
            continue
        lines.append(ln)
    return "\n".join(lines)

def parse_inbound_email(text: str, html: str = "", attachment_count: int = 0):
    """
    Return (address, datetime, county).
    Accepts an optional attachment_count for future use; safe to ignore.
    Order of attempts:
      1) IRH_META footer in text/html (most reliable)
      2) Regex on top-level body
      3) Regex on de-quoted body
      4) Optional LLM fallback (disabled by default)
    """
    # 1) IRH_META footer in either text or html
    for src in (text or "", html or ""):
        m = _re_meta.search(src)
        if m:
            addr, dt, cnty = (s.strip() for s in m.groups())
            logger.info("[parser] meta_hit from IRH_META")
            return addr, dt, cnty

    body = (text or "").strip()

    # 2) Plain regex
    m1, m2, m3 = _re_addr.search(body), _re_dt.search(body), _re_cnty.search(body)
    if m1 and m2 and m3:
        logger.info("[parser] regex_hit")
        return m1.group(1).strip(), m2.group(1).strip(), m3.group(1).strip()

    # 3) De-quoted (strip '>')
    cleaned = _strip_quotes(text or "")
    m1q, m2q, m3q = _re_addr.search(cleaned), _re_dt.search(cleaned), _re_cnty.search(cleaned)
    if m1q and m2q and m3q:
        logger.info("[parser] quoted_scan hit")
        return m1q.group(1).strip(), m2q.group(1).strip(), m3q.group(1).strip()

    # 4) Optional LLM fallback
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
