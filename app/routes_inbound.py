# =============================
# FILE: app/routes_inbound.py
# Purpose: Handle SendGrid Inbound Parse webhook
#  - Capture fields & attachments from multipart/form-data
#  - Parse address/datetime/county using email_parser (META → regex → quoted-scan → optional LLM)
#  - Persist into inbound_emails (robust to column name differences)
#  - Attempt to match an IncidentRequest and forward attachments (no JWT requirement)
# =============================
from __future__ import annotations
import logging
from typing import List, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from fastapi import APIRouter, Request, Depends  # add Depends

from app.database import get_db
from app import models
from app.email_parser import parse_inbound_email
from app.email_io import (
    send_attachments_to_user,
    send_alert_no_attachments,
)

router = APIRouter(tags=["inbound"])
log = logging.getLogger("app.routes_inbound")


# ---------- helpers ----------

def _nonfile_items(form) -> list[tuple[str, str]]:
    out = []
    for k, v in form.multi_items():
        # starlette FormData returns UploadFile for files
        if hasattr(v, "filename") and hasattr(v, "file"):
            continue
        out.append((k, str(v)))
    return out


def _collect_attachments(form) -> List[Tuple[str, bytes]]:
    files: List[Tuple[str, bytes]] = []
    # 1) SendGrid may send "attachments" count and keys attachment1..N
    count_raw = form.get("attachments")
    try:
        n = int(count_raw) if count_raw is not None else 0
    except Exception:
        n = 0

    if n:
        for i in range(1, n + 1):
            key = f"attachment{i}"
            uf = form.get(key)
            if hasattr(uf, "filename") and hasattr(uf, "read"):
                data = uf.file.read()
                files.append((uf.filename or f"file{i}", data))
    else:
        # 2) Some posts omit the count; scan all keys and pick UploadFile values
        for k, v in form.multi_items():
            if hasattr(v, "filename") and hasattr(v, "read"):
                data = v.file.read()
                files.append((v.filename or k, data))
    return files


def _first_str(form, key: str) -> str:
    v = form.get(key)
    return v if isinstance(v, str) else ""


def _persist_inbound(db: Session, sender: str, subject: str, body: str,
                     parsed_address: str, parsed_datetime: str, parsed_county: str,
                     has_attachments: bool, attachment_count: int) -> models.InboundEmail:
    cols = {c.name for c in models.InboundEmail.__table__.columns}

    base_kwargs = {
        "sender": sender,
        "subject": subject,
        "body": body[:10000],
    }
    field_map = {}
    if "parsed_address" in cols:
        field_map["parsed_address"] = parsed_address or None
    elif "address" in cols:
        field_map["address"] = parsed_address or None

    if "parsed_datetime" in cols:
        field_map["parsed_datetime"] = parsed_datetime or None
    elif "datetime" in cols:
        field_map["datetime"] = parsed_datetime or None

    if "parsed_county" in cols:
        field_map["parsed_county"] = parsed_county or None
    elif "county" in cols:
        field_map["county"] = parsed_county or None

    if "has_attachments" in cols:
        field_map["has_attachments"] = bool(has_attachments)
    if "attachment_count" in cols:
        field_map["attachment_count"] = int(attachment_count)

    row_kwargs = {k: v for k, v in {**base_kwargs, **field_map}.items() if k in cols}
    inbound_row = models.InboundEmail(**row_kwargs)
    db.add(inbound_row)
    db.commit()
    db.refresh(inbound_row)
    return inbound_row


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _match_incident_request(db: Session, addr: str, dt_str: str, county: str) -> models.IncidentRequest | None:
    addr_n, dt_n, cty_n = map(_normalize, (addr, dt_str, county))
    if not (addr_n and dt_n and cty_n):
        return None
    try:
        q = db.query(models.IncidentRequest).filter(
            models.IncidentRequest.incident_address.ilike(addr),
            models.IncidentRequest.incident_datetime == dt_str,
            models.IncidentRequest.county.ilike(county),
        )
        # Prefer newest
        if hasattr(models.IncidentRequest, "created_at"):
            q = q.order_by(models.IncidentRequest.created_at.desc())
        else:
            q = q.order_by(models.IncidentRequest.id.desc())
        return q.first()
    except Exception as e:
        log.warning(f"[inbound] match lookup failed: {e}")
        return None


def _resolve_recipient_email(db: Session, req: models.IncidentRequest) -> str | None:
    # 1) direct requester_email on the request
    if hasattr(req, "requester_email") and req.requester_email:
        return req.requester_email

    # 2) created_by → User.email
    if hasattr(req, "created_by") and req.created_by:
        user = db.query(models.User).filter(models.User.username == req.created_by).first()
        if user and getattr(user, "email", None):
            return user.email

    # No other fallbacks
    return None



# ---------- routes ----------

@router.post("/inbound")
async def inbound(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    keys = list(form.keys())
    log.info("[inbound] received form keys: %s", keys)
    log.info("[inbound] NONFILE parts: %s", _nonfile_items(form))

    # Grab form basics
    sender = _first_str(form, "from") or _first_str(form, "sender")
    subject = _first_str(form, "subject")
    text = _first_str(form, "text")
    html = _first_str(form, "html")

    # Files
    files = _collect_attachments(form)
    has_files = bool(files)
    log.info("[inbound] attachment_count=%d", len(files))

    # Parse fields (regex/meta/quoted-scan/llm in email_parser)
    address, dt_str, county = parse_inbound_email(text, html, len(files))
    log.info("[inbound] parsed addr=%r dt=%r county=%r", address, dt_str, county)

    # Persist inbound row
    try:
        inbound_row = _persist_inbound(
            db,
            sender=sender,
            subject=subject,
            body=(text or html or ""),
            parsed_address=address,
            parsed_datetime=dt_str,
            parsed_county=county,
            has_attachments=has_files,
            attachment_count=len(files),
        )
    except Exception as e:
        log.warning("[inbound] persist failed: %s", e)
        inbound_row = None

    # Attempt match & forwarding
    forwarded = False
    recipient = None
    try:
        matched = _match_incident_request(db, address, dt_str, county)
        if matched:
            recipient = _resolve_recipient_email(db, matched)
            if recipient:
                subj = f"Incident Report Received: {getattr(matched, 'incident_datetime', dt_str)}"
                if has_files:
                    send_attachments_to_user(
                        recipient,
                        subj,
                        "Attached are the files received in response to your request.",
                        files,
                    )
                else:
                    send_alert_no_attachments(
                        recipient,
                        subj,
                        "A reply was received but contained no attachments.",
                    )
                forwarded = True
            else:
                log.warning("[forward] no recipient email available for matched id=%s", matched.id)
        else:
            log.info("[inbound] no request match; nothing forwarded")
    except Exception as e:
        log.warning("[forward] failed: %s", e)

    return JSONResponse(
        {
            "status": "received",
            "sender": sender,
            "parsed": {"address": address, "datetime": dt_str, "county": county},
            "match": bool(forwarded and recipient),
            "attachments": [name for name, _ in files],
            "forwarded": forwarded,
            "inbound_id": getattr(inbound_row, "id", None),
        }
    )



# import logging
# import os
# import jwt
# from fastapi import APIRouter, Request, Depends, UploadFile
# from sqlalchemy.orm import Session
# from app.database import get_db
# from app import models
# from app.email_parser import parse_inbound_email
# from app.email_io import send_attachments_to_user, send_alert_no_attachments

# # SECRET_KEY/ALGORITHM may live in app.config or root-level auth
# try:
#     from app.config import SECRET_KEY, ALGORITHM
# except ImportError:
#     from auth import SECRET_KEY, ALGORITHM

# logger = logging.getLogger("uvicorn.error").getChild("inbound")

# logger = logging.getLogger(__name__)
# router = APIRouter()

# # Optional GET probe so browser/health checks don't 405
# @router.get("/inbound")
# def inbound_probe():
#     logger.info("[probe] GET /inbound called (health check)")
#     return {"ok": True, "hint": "SendGrid should POST multipart/form-data here."}

# @router.post("/inbound")
# async def inbound(request: Request, db: Session = Depends(get_db)):
#     form = await request.form()
#     logger.info(f"[inbound] received form keys: {list(form.keys())}")

#     sender = (form.get("from") or form.get("sender") or "").strip()
#     subject = (form.get("subject") or "").strip()
#     text = form.get("text") or ""
#     html = form.get("html") or ""

#     # --- Attachment debug: list all multipart fields and detect files (robust) ---
#     attachments = []
#     nonfile_log = []

#     # 1) First pass: anything with a filename/read attrib is treated as a file
#     for key, value in form.multi_items():
#         is_file_like = hasattr(value, "filename") and hasattr(value, "read")
#         if is_file_like and (getattr(value, "filename", "") or "").strip():
#             content = await value.read()
#             attachments.append((value.filename, content))
#             logger.info(f"[inbound] FILE part key={key!r} filename={value.filename!r} size={len(content)}")
#         else:
#             val = str(value)
#             nonfile_log.append((key, (val[:80] + "…") if len(val) > 80 else val))

#     # 2) Fallback: if SendGrid says there are N attachments but none captured,
#     #    fetch them explicitly by known keys: attachment1..attachmentN
#     try:
#         declared = int(str(form.get("attachments") or "0").strip() or "0")
#     except Exception:
#         declared = 0

#     if declared > 0 and not attachments:
#         logger.info(f"[inbound] fallback: declared attachments={declared}, collecting attachment1..{declared}")
#         for i in range(1, declared + 1):
#             part = form.get(f"attachment{i}")
#             if part and hasattr(part, "filename") and hasattr(part, "read"):
#                 content = await part.read()
#                 attachments.append((part.filename, content))
#                 logger.info(f"[inbound] FILE part (fallback) key='attachment{i}' filename={part.filename!r} size={len(content)}")

#     if nonfile_log:
#         logger.info(f"[inbound] NONFILE parts: {nonfile_log}")

#     attachment_count = len(attachments)
#     has_attachments = attachment_count > 0
#     logger.info(f"[inbound] attachment_count={attachment_count}")


#     # --- Parse email body ---
#     # address, dt_str, county = parse_inbound_email(text, html)
#     # logger.info(f"[inbound] parsed addr={address!r} dt={dt_str!r} county={county!r}")

#     # --- Parse email body (regex-first; optional LLM via PARSER_USE_LLM) ---
#     address, dt_str, county = parse_inbound_email(text, html)

#     # Fallback: recover fields from our own outbound headers if present
#     if not (address and dt_str and county):
#         raw_headers = (form.get("headers") or "")
#         try:
#             for line in str(raw_headers).splitlines():
#                 low = line.lower()
#                 if low.startswith("x-irh-address:"):
#                     address = address or line.split(":", 1)[1].strip()
#                 elif low.startswith("x-irh-datetime:"):
#                     dt_str = dt_str or line.split(":", 1)[1].strip()
#                 elif low.startswith("x-irh-county:"):
#                     county = county or line.split(":", 1)[1].strip()
#         except Exception:
#             pass

#     logger.info(f"[inbound] parsed addr={address!r} dt={dt_str!r} county={county!r}")


#     # --- Persist inbound email ---
#     inbound_id = None
#     try:
#         inbound_row = models.InboundEmail(
#             sender=sender,
#             subject=subject,
#             body=(text or html or "")[:10000],
#             parsed_address=address or None,
#             parsed_datetime=dt_str or None,
#             parsed_county=county or None,
#             has_attachments=has_attachments,
#             attachment_count=attachment_count,
#         )
#         db.add(inbound_row)
#         db.commit()
#         db.refresh(inbound_row)
#         inbound_id = inbound_row.id
#     except Exception as e:
#         logger.warning(f"[inbound] persist failed: {e}")

#     # --- Match against IncidentRequests ---
#     matched_request = None
#     try:
#         q = db.query(models.IncidentRequest)
#         if county:
#             q = q.filter(models.IncidentRequest.county.ilike(f"%{county}%"))
#         if hasattr(models.IncidentRequest, "created_at"):
#             q = q.order_by(models.IncidentRequest.created_at.desc())
#         else:
#             q = q.order_by(models.IncidentRequest.id.desc())
#         candidates = q.limit(200).all()
#         for r in candidates:
#             if (r.incident_address or "").strip().lower() == (address or "").strip().lower() and \
#                (r.incident_datetime or "").strip() == (dt_str or "").strip():
#                 matched_request = r
#                 break
#     except Exception as e:
#         logger.warning(f"[inbound] match lookup failed: {e}")

#     # --- Forward if matched ---
#     forwarded = False
#     if matched_request and getattr(matched_request, "user_token", None):
#         try:
#             payload = jwt.decode(matched_request.user_token, SECRET_KEY, algorithms=[ALGORITHM])
#             username = payload.get("sub") or payload.get("username")
#             if username:
#                 user = db.query(models.User).filter(models.User.username == username).first()
#                 if user and user.email:
#                     logger.info(
#                         f"[forward] to={user.email} files={attachment_count} req_id={getattr(matched_request,'id',None)} inbound_id={inbound_id}"
#                     )
#                     subj_out = f"Incident Report: {subject or 'reply'}"
#                     body_out = text or html or ""
#                     if has_attachments:
#                         ok = send_attachments_to_user(user.email, subj_out, body_out, attachments)
#                     else:
#                         ok = send_alert_no_attachments(user.email, subj_out, body_out)
#                     forwarded = bool(ok)
#         except Exception as e:
#             logger.warning(f"[forward] failed: {e}")

#     return {
#         "status": "received",
#         "sender": sender,
#         "parsed": {"address": address, "datetime": dt_str, "county": county},
#         "match": getattr(matched_request, "id", None),
#         "attachments": [fn for fn, _ in attachments],
#         "forwarded": forwarded,
#         "inbound_id": inbound_id,
#     }


# from fastapi import APIRouter, Request, Depends, UploadFile
# from sqlalchemy.orm import Session
# import logging
# import os
# import jwt

# from app.database import get_db
# from app import models
# from app.utils import normalize, normalize_datetime, rate_limit_sender
# from auth import SECRET_KEY, ALGORITHM
# from app.email_io import send_attachments_to_user, send_alert_no_attachments
# from app.email_parser import parse_inbound_email

# logger = logging.getLogger(__name__)
# router = APIRouter()

# @router.post("/inbound")
# async def inbound(request: Request, db: Session = Depends(get_db)):
#     # 1) rate limit per client IP
#     ip = request.client.host if request.client else "unknown"
#     rate_limit_sender(f"inbound:{ip}")

#     # 2) read multipart form
#     form = await request.form()
#     sender = (form.get("from") or form.get("sender") or "").strip()
#     subject = (form.get("subject") or "").strip()
#     text = form.get("text") or ""
#     html = form.get("html") or ""

#     # --- Attachment debug: list all multipart fields and detect files ---
#     attachments = []
#     nonfile_log = []
#     for key, value in form.multi_items():
#         # UploadFile => actual binary attachment; str => normal field
#         if hasattr(value, "filename") and value.filename:
#             content = await value.read()
#             attachments.append((value.filename, content))
#             logger.info(f"[inbound] FILE part key={key!r} filename={value.filename!r} size={len(content)}")
#         else:
#             # Keep a short sample of non-file fields to see what SendGrid actually sent
#             val = str(value)
#             nonfile_log.append((key, (val[:80] + "…") if len(val) > 80 else val))

#     if nonfile_log:
#         logger.info(f"[inbound] NONFILE parts: {nonfile_log}")

#     attachment_count = len(attachments)
#     has_attachments = attachment_count > 0
#     logger.info(f"[inbound] attachment_count={attachment_count}")

#     # collect attachments (any part with a filename)
#     attachments = []
#     for _, value in form.multi_items():
#         if isinstance(value, UploadFile) and (value.filename or "").strip():
#             content = await value.read()
#             attachments.append((value.filename, content))

#     attachment_count = len(attachments)
#     has_attachments = attachment_count > 0
#     logger.info(f"[inbound] sender={sender} subject={subject!r} atts={attachment_count}")

#     # 3) collect attachments (any part with a filename)
#     attachments = []
#     for _, value in form.multi_items():
#         if isinstance(value, UploadFile) and (value.filename or "").strip():
#             content = await value.read()
#             attachments.append((value.filename, content))

#     # 4) parse (your cleaner/LLM lives inside parse_inbound_email)
#     address, dt_str, county = parse_inbound_email(text, html)

#     # 5) normalize for matching
#     n_addr = normalize(address or "")
#     n_dt   = normalize_datetime(dt_str or "")
#     n_cnty = normalize(county or "")


#     # persist inbound email (direct columns)
#     inbound_id = None
#     try:
#         inbound_row = models.InboundEmail(
#             sender=sender,
#             subject=subject,
#             body=(text or html or "")[:10000],
#             parsed_address=address or None,
#             parsed_datetime=dt_str or None,
#             parsed_county=county or None,
#             has_attachments=has_attachments,
#             attachment_count=attachment_count,
#             # created_at is filled by DB default now()
#         )
#         db.add(inbound_row)
#         db.commit()
#         db.refresh(inbound_row)
#         inbound_id = inbound_row.id
#     except Exception as e:
#         logger.warning(f"[inbound] persist failed: {e}")


#     # 7) find a matching IncidentRequest (county filter + exact normalized address & datetime)
#     # 7) find a matching IncidentRequest
#     matched_request = None
#     try:
#         q = db.query(models.IncidentRequest)
#         if n_cnty:
#             q = q.filter(models.IncidentRequest.county.ilike(f"%{county}%"))

#         # Prefer created_at if your IncidentRequest has it; else fall back to id
#         if hasattr(models.IncidentRequest, "created_at"):
#             q = q.order_by(models.IncidentRequest.created_at.desc())
#         else:
#             q = q.order_by(models.IncidentRequest.id.desc())

#         candidates = q.limit(200).all()
#         for r in candidates:
#             if normalize(r.incident_address) == n_addr and normalize_datetime(r.incident_datetime) == n_dt:
#                 matched_request = r
#                 break
#     except Exception as e:
#         logger.warning(f"[inbound] match lookup failed: {e}")


#     # 8) resolve recipient from stored JWT and forward
#     forwarded = False
#     if matched_request and getattr(matched_request, "user_token", None):
#         try:
#             payload = jwt.decode(matched_request.user_token, SECRET_KEY, algorithms=[ALGORITHM])
#             username = payload.get("sub") or payload.get("username")
#             if username:
#                 user = db.query(models.User).filter(models.User.username == username).first()
#                 if user and user.email:
#                     logger.info(
#                         f"[forward] to={user.email} files={attachment_count} "
#                         f"req_id={getattr(matched_request,'id',None)} inbound_id={inbound_id}"
#                     )
#                     subj_out = f"Incident Report: {subject or 'reply'}"
#                     body_out = text or html or ""
#                     if has_attachments:
#                         ok = send_attachments_to_user(user.email, subj_out, body_out, attachments)
#                     else:
#                         ok = send_alert_no_attachments(user.email, subj_out, body_out)
#                     forwarded = bool(ok)
#         except Exception as e:
#             logger.warning(f"[forward] failed: {e}")


#     return {
#         "status": "received",
#         "sender": sender,
#         "parsed": {"address": address, "datetime": dt_str, "county": county},
#         "match": getattr(matched_request, "id", None),
#         "attachments": [name for name, _ in attachments],
#         "forwarded": forwarded,
#         "inbound_id": inbound_id,
#     }



# form_data = dict(form)
# address, dt_str, county = parse_inbound_email(
#     form_data.get("text", ""),
#     form_data.get("html", "")
# )

# # ================================
# # FILE: app/routes_inbound.py
# # ================================
# from fastapi import APIRouter, Depends, HTTPException, Request
# from sqlalchemy.orm import Session
# # from app.database import get_db
# # from app.models import IncidentRequest, InboundEmail, User
# # from app.utils import normalize, normalize_datetime, rate_limit_sender
# # from app.config import OPENAI_API_KEY
# # from app.email_io import send_attachments_to_user, send_alert_no_attachments
# from .database import get_db
# from .models import User, IncidentRequest, InboundEmail
# from .schemas import RegisterRequest, IncidentRequestCreate
# from .config import get_county_email_map, OPENAI_API_KEY, ADMIN_TOKEN
# from .email_io import send_request_email, send_attachments_to_user, send_alert_no_attachments
# from .utils import normalize, normalize_datetime, rate_limit_sender
# from auth import SECRET_KEY, ALGORITHM
# import json
# #from app.email_parser import parse_inbound_email


# router = APIRouter()

# # Optional: OpenAI client (LLM fallback)
# try:
#     from openai import OpenAI
#     openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
# except Exception:
#     openai_client = None

# @router.post('/inbound')
# async def inbound_parse(request: Request, db: Session = Depends(get_db)):
#     form = await request.form()
#     # address, dt_str, county = parse_inbound_email(form.get("text", ""), form.get("html", ""))
#     sender = form.get('from')
#     subject = form.get('subject')
#     body = form.get('text')

#     if not sender or not body:
#         raise HTTPException(status_code=400, detail="Invalid inbound email payload")

#     rate_limit_sender(sender)

#     # Rule-based parse
#     parsed_address = parsed_datetime = parsed_county = None
#     for raw_line in body.splitlines():
#         line = raw_line.strip()
#         lower = line.lower()
#         if lower.startswith('address:'):
#             parsed_address = line[len('Address:'):].strip()
#         elif lower.startswith('date/time:'):
#             parsed_datetime = line[len('Date/Time:'):].strip()
#         elif lower.startswith('county:'):
#             parsed_county = line[len('County:'):].strip()

#     # Gather attachments
#     attachments = []
#     for key, value in form.multi_items():
#         if hasattr(value, 'filename') and value.filename:
#             try:
#                 content = await value.read()
#                 attachments.append({
#                     'filename': value.filename,
#                     'content': content,
#                     'content_type': getattr(value, 'content_type', 'application/octet-stream') or 'application/octet-stream'
#                 })
#             except Exception:
#                 continue

#     # LLM fallback
#     if openai_client and not (parsed_address and parsed_datetime and parsed_county):
#         prompt = (
#             "Extract the address, datetime, and county from this email text and return JSON with keys 'address', 'datetime', 'county'.\n"
#             f"EMAIL:\n{body}\n\n"
#             "Return ONLY the JSON object."
#         )
#         try:
#             resp = openai_client.chat.completions.create(
#                 model="gpt-4o-mini",
#                 messages=[{"role": "user", "content": prompt}],
#                 timeout=12,
#             )
#             content = resp.choices[0].message.content.strip()
#             llm = json.loads(content)
#             parsed_address = parsed_address or llm.get('address')
#             parsed_datetime = parsed_datetime or llm.get('datetime')
#             parsed_county = parsed_county or llm.get('county')
#         except Exception:
#             pass

#     # Persist inbound
#     inbound_record = InboundEmail(
#         sender=sender,
#         subject=subject or '',
#         body=body,
#         parsed_address=parsed_address,
#         parsed_datetime=parsed_datetime,
#         parsed_county=parsed_county,
#     )
#     db.add(inbound_record)
#     db.commit()

#     # Try match
#     match_info = None
#     matched_request = None
#     if parsed_address and parsed_datetime and parsed_county:
#         p_addr = normalize(parsed_address)
#         p_dt = normalize_datetime(parsed_datetime)
#         candidates = db.query(IncidentRequest).filter(IncidentRequest.county.ilike(f"%{parsed_county}%")).all()
#         for cand in candidates:
#             if normalize(cand.incident_address) == p_addr and normalize_datetime(cand.incident_datetime) == p_dt:
#                 matched_request = cand
#                 match_info = {"incident_request_id": cand.id}
#                 break

#     # Deliver or alert
#     if matched_request:
#         # decode JWT -> username -> user email
#         try:
#             from jose import jwt
#             payload = jwt.decode(matched_request.user_token, SECRET_KEY, algorithms=[ALGORITHM])
#             username = payload.get("sub")
#         except Exception:
#             username = None
#         recipient_email = None
#         if username:
#             user = db.query(User).filter(User.username == username).first()
#             if user:
#                 recipient_email = user.email

#         if attachments and recipient_email:
#             subject_out = f"Your Incident Report(s) for {matched_request.incident_address}"
#             body_out = (
#                 f"We matched a response from the county office to your request.\n"
#                 f"Incident: {matched_request.incident_address} @ {matched_request.incident_datetime} ({matched_request.county})"
#             )
#             try:
#                 send_attachments_to_user(recipient_email, subject_out, body_out, attachments)
#             except Exception:
#                 pass
#         elif not attachments:
#             try:
#                 send_alert_no_attachments(
#                     subject=f"No attachments in county reply (request {matched_request.id})",
#                     body_text=f"Sender: {sender}\nSubject: {subject}\nBody:\n{body}",
#                 )
#             except Exception:
#                 pass

#     return {
#         "status": "received",
#         "sender": sender,
#         "parsed": {"address": parsed_address, "datetime": parsed_datetime, "county": parsed_county},
#         "match": match_info,
#         "attachments": [a['filename'] for a in attachments] if attachments else []
#     }
