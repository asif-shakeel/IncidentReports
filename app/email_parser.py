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
# --- LLM fallback (final resort) ---
    if USE_LLM and OPENAI_API_KEY:
        import time, json
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        timeout_sec = int(os.getenv("LLM_TIMEOUT_SECS", "8"))
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")

        prompt = (
            "Extract three fields from the email reply body. "
            "Return ONLY strict JSON with keys exactly: address, datetime, county. "
            "Datetime should be in 'YYYY-MM-DD HH:MM' 24h format if present.\n\n"
            f"EMAIL BODY:\n{text or ''}"
        )

        for attempt in range(max_retries + 1):
            try:
                # prefer meta-stripped body to reduce confusion
                body_for_llm = (text or "")
                # call
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                    timeout=timeout_sec,
                )
                content = resp.choices[0].message.content or "{}"
                data = json.loads(content)
                a = (data.get("address") or "").strip()
                d = (data.get("datetime") or "").strip()
                c = (data.get("county")  or "").strip()
                logger.info("[parser] llm_hit model=%s", model)
                return a, d, c
            except Exception as e:
                # 429 or transient => small backoff; anything else, bail
                msg = str(e)
                if "429" in msg and attempt < max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.info("[parser] llm 429; retrying in %.2fs (attempt %d/%d)", delay, attempt+1, max_retries)
                    time.sleep(delay)
                    continue
                logger.warning("[parser] llm_fallback_failed: %s", e)


    logger.info("[parser] no hit; returning blanks")
    return "", "", ""
