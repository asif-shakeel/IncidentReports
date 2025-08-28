# ================================
# FILE: app/utils.py
# ================================
import re
import time
from collections import deque, defaultdict
from dateutil import parser as dtparser
from fastapi import HTTPException
from app.config import INBOUND_RPS, WINDOW_SECS

_sender_hits = defaultdict(deque)

def rate_limit_sender(sender: str):
    now = time.time()
    dq = _sender_hits[sender]
    while dq and now - dq[0] > WINDOW_SECS:
        dq.popleft()
    if len(dq) >= INBOUND_RPS:
        raise HTTPException(status_code=429, detail="Too many inbound emails from this sender; try again later.")
    dq.append(now)

_def_space = re.compile(r'\s+')
_def_strip = re.compile(r'[^0-9a-zA-Z ]+')

def normalize(s: str) -> str:
    if not s:
        return ''
    s = _def_strip.sub(' ', s)
    s = _def_space.sub(' ', s)
    return s.strip().lower()

def normalize_datetime(s: str) -> str:
    if not s:
        return ''
    try:
        dt = dtparser.parse(s)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return normalize(s)