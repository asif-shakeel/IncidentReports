# ================================
# FILE: app/utils.py
# ================================
import re, time
from collections import defaultdict

_sender_hits = defaultdict(list)

def normalize(text: str) -> str:
    return text.strip().lower() if text else ""

def normalize_datetime(dt_str: str) -> str:
    return dt_str.strip() if dt_str else ""

def rate_limit_sender(sender: str, rps: int, window: int) -> bool:
    now = time.time()
    hits = _sender_hits[sender]
    _sender_hits[sender] = [t for t in hits if now - t < window]
    if len(_sender_hits[sender]) >= rps:
        return False
    _sender_hits[sender].append(now)
    return True