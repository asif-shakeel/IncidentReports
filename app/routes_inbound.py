import logging
import os
import jwt
from fastapi import APIRouter, Request, Depends, UploadFile
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.email_parser import parse_inbound_email
from app.email_io import send_attachments_to_user, send_alert_no_attachments
from auth import SECRET_KEY, ALGORITHM

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/inbound")
async def inbound(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sender = (form.get("from") or form.get("sender") or "").strip()
    subject = (form.get("subject") or "").strip()
    text = form.get("text") or ""
    html = form.get("html") or ""

    # --- Attachment debug: list all multipart fields and detect files ---
    attachments = []
    nonfile_log = []
    for key, value in form.multi_items():
        if isinstance(value, UploadFile) and (value.filename or "").strip():
            content = await value.read()
            attachments.append((value.filename, content))
            logger.info(f"[inbound] FILE part key={key!r} filename={value.filename!r} size={len(content)}")
        else:
            val = str(value)
            nonfile_log.append((key, (val[:80] + "…") if len(val) > 80 else val))

    if nonfile_log:
        logger.info(f"[inbound] NONFILE parts: {nonfile_log}")

    attachment_count = len(attachments)
    has_attachments = attachment_count > 0
    logger.info(f"[inbound] attachment_count={attachment_count}")

    # --- Parse email body ---
    address, dt_str, county = parse_inbound_email(text, html)
    logger.info(f"[inbound] parsed addr={address!r} dt={dt_str!r} county={county!r}")

    # --- Persist inbound email ---
    inbound_id = None
    try:
        inbound_row = models.InboundEmail(
            sender=sender,
            subject=subject,
            body=(text or html or "")[:10000],
            parsed_address=address or None,
            parsed_datetime=dt_str or None,
            parsed_county=county or None,
            has_attachments=has_attachments,
            attachment_count=attachment_count,
        )
        db.add(inbound_row)
        db.commit()
        db.refresh(inbound_row)
        inbound_id = inbound_row.id
    except Exception as e:
        logger.warning(f"[inbound] persist failed: {e}")

    # --- Match against IncidentRequests ---
    matched_request = None
    try:
        q = db.query(models.IncidentRequest)
        if county:
            q = q.filter(models.IncidentRequest.county.ilike(f"%{county}%"))
        if hasattr(models.IncidentRequest, "created_at"):
            q = q.order_by(models.IncidentRequest.created_at.desc())
        else:
            q = q.order_by(models.IncidentRequest.id.desc())
        candidates = q.limit(200).all()
        for r in candidates:
            if (r.incident_address or "").strip().lower() == (address or "").strip().lower() and \
               (r.incident_datetime or "").strip() == (dt_str or "").strip():
                matched_request = r
                break
    except Exception as e:
        logger.warning(f"[inbound] match lookup failed: {e}")

    # --- Forward if matched ---
    forwarded = False
    if matched_request and getattr(matched_request, "user_token", None):
        try:
            payload = jwt.decode(matched_request.user_token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub") or payload.get("username")
            if username:
                user = db.query(models.User).filter(models.User.username == username).first()
                if user and user.email:
                    logger.info(
                        f"[forward] to={user.email} files={attachment_count} req_id={getattr(matched_request,'id',None)} inbound_id={inbound_id}"
                    )
                    subj_out = f"Incident Report: {subject or 'reply'}"
                    body_out = text or html or ""
                    if has_attachments:
                        ok = send_attachments_to_user(user.email, subj_out, body_out, attachments)
                    else:
                        ok = send_alert_no_attachments(user.email, subj_out, body_out)
                    forwarded = bool(ok)
        except Exception as e:
            logger.warning(f"[forward] failed: {e}")

    return {
        "status": "received",
        "sender": sender,
        "parsed": {"address": address, "datetime": dt_str, "county": county},
        "match": getattr(matched_request, "id", None),
        "attachments": [fn for fn, _ in attachments],
        "forwarded": forwarded,
        "inbound_id": inbound_id,
    }

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
