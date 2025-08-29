# =============================
# FILE: app/routes_inbound.py
# =============================
import logging, re
from typing import List, Tuple
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.email_parser import parse_inbound_email
from app.email_io import send_attachments_to_user, send_alert_no_attachments

router = APIRouter(tags=["inbound"])
log = logging.getLogger("uvicorn.error").getChild("inbound")

# ---------- helpers ----------
def _nonfile_items(form):
    out = []
    for k, v in form.multi_items():
        if hasattr(v, "filename") and hasattr(v, "file"):
            continue
        out.append((k, str(v)))
    return out

def _collect_attachments(form) -> List[Tuple[str, bytes]]:
    files: List[Tuple[str, bytes]] = []
    # SendGrid provides "attachments" count and fields attachment1..N
    try:
        n = int(form.get("attachments") or 0)
    except Exception:
        n = 0
    if n:
        for i in range(1, n + 1):
            key = f"attachment{i}"
            uf = form.get(key)
            if hasattr(uf, "file"):
                files.append((uf.filename or f"file{i}", uf.file.read()))
    else:
        # Fallback: scan any UploadFile in form
        for k, v in form.multi_items():
            if hasattr(v, "file"):
                files.append((v.filename or k, v.file.read()))
    return files

def _persist_inbound(db: Session, **kw) -> models.InboundEmail:
    cols = {c.name for c in models.InboundEmail.__table__.columns}
    safe = {k: v for k, v in kw.items() if k in cols}
    row = models.InboundEmail(**safe)
    db.add(row); db.commit(); db.refresh(row)
    return row

def _resolve_recipient_email(db: Session, req: models.IncidentRequest) -> str | None:
    if getattr(req, "requester_email", None):
        return req.requester_email
    if getattr(req, "created_by", None):
        user = db.query(models.User).filter(models.User.username == req.created_by).first()
        if user and getattr(user, "email", None):
            return user.email
    return None

# normalization for forgiving matches
def _norm_text(s: str) -> str:
    s = (s or "").lower().strip()
    return " ".join(s.split())

def _norm_addr(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)     # strip punctuation
    s = " ".join(s.split())
    s = re.sub(r"\b(st|rd|ave|blvd|dr|ct|ln|hwy|pkwy|ter)\.$", r"\1", s)
    return s.strip()

# ---------- route ----------
@router.post("/inbound")
async def inbound(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    log.info("[inbound] received form keys: %s", list(form.keys()))
    log.info("[inbound] NONFILE parts: %s", _nonfile_items(form))

    sender  = form.get("from") or form.get("sender") or ""
    subject = form.get("subject") or ""
    text    = form.get("text") or ""
    html    = form.get("html") or ""

    files = _collect_attachments(form)
    log.info("[inbound] attachment_count=%d", len(files))

    # parse (regex first; IRH_META supported inside email_parser)
    address, dt_str, county = parse_inbound_email(text, html, len(files))  # third arg optional
    log.info("[inbound] parsed addr=%r dt=%r county=%r", address, dt_str, county)

    # persist inbound row
    inbound_row = _persist_inbound(
        db,
        sender=sender,
        subject=subject,
        body=(text or html or "")[:10000],
        parsed_address=address or None,
        parsed_datetime=dt_str or None,
        parsed_county=county or None,
        has_attachments=bool(files),
        attachment_count=len(files),
    )

    # try to match the request
    forwarded = False
    recipient = None
    match_id  = None
    try:
        log.info("[match] trying addr=%r dt=%r county=%r", address, dt_str, county)
        addr_n = _norm_addr(address)
        dt_n   = _norm_text(dt_str)
        cnty_n = _norm_text(county)

        # narrow by county first
        candidates = db.query(models.IncidentRequest)\
            .filter(models.IncidentRequest.county.ilike(f"%{county}%"))\
            .order_by(models.IncidentRequest.id.desc())\
            .all()

        match = None
        for r in candidates:
            if _norm_addr(r.incident_address) == addr_n and _norm_text(r.incident_datetime) == dt_n:
                match = r
                break

        if match:
            match_id = match.id
            recipient = _resolve_recipient_email(db, match)
            log.info("[match] found id=%s recipient=%r", match_id, recipient)
            subj = f"Incident Report Received: {getattr(match, 'incident_datetime', dt_str)}"
            if recipient:
                if files:
                    send_attachments_to_user(recipient, subj, "Attached are the files received.", files)
                else:
                    send_alert_no_attachments(recipient, subj, "A reply was received but contained no attachments.")
                forwarded = True
                log.info("[forward] dispatched to %s (with_files=%s)", recipient, bool(files))
            else:
                log.warning("[forward] recipient not found for id=%s", match_id)
        else:
            log.info("[match] no request matched for normalized triple")

    except Exception as e:
        log.warning("[forward] failed: %s", e)

    return JSONResponse({
        "status": "received",
        "sender": sender,
        "parsed": {"address": address, "datetime": dt_str, "county": county},
        "match": match_id,
        "attachments": [n for n, _ in files],
        "forwarded": forwarded,
        "inbound_id": getattr(inbound_row, "id", None),
        "recipient": recipient,
    })
