# =============================
# FILE: app/config.py
# =============================
import os, json, csv, logging
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger("uvicorn.error").getChild("config")

# Load .env from repo root (helpful locally)
root_env = Path(__file__).resolve().parent.parent / ".env"
if root_env.exists():
    load_dotenv(dotenv_path=root_env, override=True)

# --- Core keys ---
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
ADMIN_TOKEN      = os.getenv("ADMIN_TOKEN")

# --- Email ---
FROM_EMAIL     = os.getenv("FROM_EMAIL", "request@repo.incidentreportshub.com")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "intake@repo.incidentreportshub.com")
ALERT_EMAIL    = os.getenv("ALERT_EMAIL", "alert@repo.incidentreportshub.com")

# --- Inbound rate limiting ---
INBOUND_RPS  = int(os.getenv("INBOUND_RPS", "5"))
WINDOW_SECS  = int(os.getenv("INBOUND_WINDOW_SECS", "10"))

# --- JWT/Auth ---
SECRET_KEY    = os.getenv("SECRET_KEY", "changeme")
ALGORITHM     = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# --- County contact sources ---
# 1) CSV (primary; your original flow). Set COUNTY_CSV_PATH to an absolute or app-relative path.
#    Example: /opt/render/project/src/ca_all_counties_fire_records_contacts.csv
COUNTY_CSV_PATH   = os.getenv("COUNTY_CSV_PATH", "ca_all_counties_fire_records_contacts_template.csv")

# 2) Env JSON fallback (optional)
COUNTY_EMAIL_MAP_JSON = os.getenv("COUNTY_EMAIL_MAP", "")

# Cache to avoid re-parsing on every request
__COUNTY_MAP_CACHE: dict[str, str] | None = None

def _read_env_json() -> dict[str, str]:
    if not COUNTY_EMAIL_MAP_JSON:
        return {}
    try:
        data = json.loads(COUNTY_EMAIL_MAP_JSON)
        return {str(k).strip(): str(v).strip() for k, v in data.items() if str(v).strip()}
    except Exception as e:
        log.warning(f"[county-map] bad COUNTY_EMAIL_MAP JSON: {e}")
        return {}

def _read_csv(path: str) -> dict[str, str]:
    """
    Flexible CSV reader. We try common header names and pick the first non-empty email-like value.
    Expected to include a 'county' column (case-insensitive). Email column may be one of:
    'email', 'records_email', 'contact_email', 'fire_records_email', etc.
    """
    p = Path(path)
    if not p.exists():
        log.warning(f"[county-map] CSV not found at {p.resolve()}")
        return {}

    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return {}

        # normalize headers once
        headers_norm = {h: h.lower().strip() for h in reader.fieldnames}
        # find county-like header
        county_key = None
        for h, hl in headers_norm.items():
            if hl in {"county", "county_name"}:
                county_key = h
                break
        if not county_key:
            log.warning("[county-map] No 'county' column found in CSV headers: %s", reader.fieldnames)
            return {}

        # possible email headers, by priority
        email_candidates = [
            "email", "records_email", "contact_email", "fire_records_email",
            "public_records_email", "foia_email", "pio_email"
        ]
        # map of lowercase header -> original header
        inv = {}
        for h in reader.fieldnames:
            inv[h.lower().strip()] = h

        # pick existing email columns in order
        available_email_cols = [inv[c] for c in email_candidates if c in inv]

        result: dict[str, str] = {}
        for row in reader:
            county_val = str(row.get(county_key, "")).strip()
            if not county_val:
                continue
            email_val = ""
            # prefer first non-empty from available candidates
            for col in available_email_cols:
                v = str(row.get(col, "")).strip()
                if v:
                    email_val = v
                    break
            # as a last resort, scan for anything that looks like an email
            if not email_val:
                for k, v in row.items():
                    s = str(v).strip()
                    if "@" in s and "." in s:
                        email_val = s
                        break
            if email_val:
                result[county_val] = email_val
        return result

def get_county_email_map() -> dict[str, str]:
    """Primary = CSV; Fallback = env JSON. Cached after first load."""
    global __COUNTY_MAP_CACHE
    if __COUNTY_MAP_CACHE is not None:
        return __COUNTY_MAP_CACHE

    csv_map = _read_csv(COUNTY_CSV_PATH) if COUNTY_CSV_PATH else {}
    env_map = _read_env_json()

    # CSV wins; env fills gaps
    merged = dict(env_map)
    merged.update(csv_map)  # CSV overrides/env fills missing
    __COUNTY_MAP_CACHE = merged
    log.info("[county-map] loaded: %d entries (csv=%d, env=%d)", len(merged), len(csv_map), len(env_map))
    return merged

def get_county_email(county_name: str) -> str | None:
    """Convenience lookup with light normalization."""
    m = get_county_email_map()
    if not county_name:
        return None
    # try exact
    if county_name in m:
        return m[county_name]
    # try case-insensitive match
    lc = county_name.lower().strip()
    for k, v in m.items():
        if k.lower().strip() == lc:
            return v
    return None

def refresh_county_cache() -> int:
    """Clear and reload cache; return number of entries."""
    global __COUNTY_MAP_CACHE
    __COUNTY_MAP_CACHE = None
    return len(get_county_email_map())
