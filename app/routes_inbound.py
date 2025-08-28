# ================================
# FILE: app/routes_inbound.py
# ================================
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
# from app.database import get_db
# from app.models import IncidentRequest, InboundEmail, User
# from app.utils import normalize, normalize_datetime, rate_limit_sender
# from app.config import OPENAI_API_KEY
# from app.email_io import send_attachments_to_user, send_alert_no_attachments
from .database import get_db
from .models import User, IncidentRequest, InboundEmail
from .schemas import RegisterRequest, IncidentRequestCreate
from .config import get_county_email_map, OPENAI_API_KEY, ADMIN_TOKEN
from .email_io import send_request_email, send_attachments_to_user, send_alert_no_attachments
from .utils import normalize, normalize_datetime, rate_limit_sender
from auth import SECRET_KEY, ALGORITHM
import json

router = APIRouter()

# Optional: OpenAI client (LLM fallback)
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    openai_client = None

@router.post('/inbound')
async def inbound_parse(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sender = form.get('from')
    subject = form.get('subject')
    body = form.get('text')

    if not sender or not body:
        raise HTTPException(status_code=400, detail="Invalid inbound email payload")

    rate_limit_sender(sender)

    # Rule-based parse
    parsed_address = parsed_datetime = parsed_county = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith('address:'):
            parsed_address = line[len('Address:'):].strip()
        elif lower.startswith('date/time:'):
            parsed_datetime = line[len('Date/Time:'):].strip()
        elif lower.startswith('county:'):
            parsed_county = line[len('County:'):].strip()

    # Gather attachments
    attachments = []
    for key, value in form.multi_items():
        if hasattr(value, 'filename') and value.filename:
            try:
                content = await value.read()
                attachments.append({
                    'filename': value.filename,
                    'content': content,
                    'content_type': getattr(value, 'content_type', 'application/octet-stream') or 'application/octet-stream'
                })
            except Exception:
                continue

    # LLM fallback
    if openai_client and not (parsed_address and parsed_datetime and parsed_county):
        prompt = (
            "Extract the address, datetime, and county from this email text and return JSON with keys 'address', 'datetime', 'county'.\n"
            f"EMAIL:\n{body}\n\n"
            "Return ONLY the JSON object."
        )
        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                timeout=12,
            )
            content = resp.choices[0].message.content.strip()
            llm = json.loads(content)
            parsed_address = parsed_address or llm.get('address')
            parsed_datetime = parsed_datetime or llm.get('datetime')
            parsed_county = parsed_county or llm.get('county')
        except Exception:
            pass

    # Persist inbound
    inbound_record = InboundEmail(
        sender=sender,
        subject=subject or '',
        body=body,
        parsed_address=parsed_address,
        parsed_datetime=parsed_datetime,
        parsed_county=parsed_county,
    )
    db.add(inbound_record)
    db.commit()

    # Try match
    match_info = None
    matched_request = None
    if parsed_address and parsed_datetime and parsed_county:
        p_addr = normalize(parsed_address)
        p_dt = normalize_datetime(parsed_datetime)
        candidates = db.query(IncidentRequest).filter(IncidentRequest.county.ilike(f"%{parsed_county}%")).all()
        for cand in candidates:
            if normalize(cand.incident_address) == p_addr and normalize_datetime(cand.incident_datetime) == p_dt:
                matched_request = cand
                match_info = {"incident_request_id": cand.id}
                break

    # Deliver or alert
    if matched_request:
        # decode JWT -> username -> user email
        try:
            from jose import jwt
            payload = jwt.decode(matched_request.user_token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
        except Exception:
            username = None
        recipient_email = None
        if username:
            user = db.query(User).filter(User.username == username).first()
            if user:
                recipient_email = user.email

        if attachments and recipient_email:
            subject_out = f"Your Incident Report(s) for {matched_request.incident_address}"
            body_out = (
                f"We matched a response from the county office to your request.\n"
                f"Incident: {matched_request.incident_address} @ {matched_request.incident_datetime} ({matched_request.county})"
            )
            try:
                send_attachments_to_user(recipient_email, subject_out, body_out, attachments)
            except Exception:
                pass
        elif not attachments:
            try:
                send_alert_no_attachments(
                    subject=f"No attachments in county reply (request {matched_request.id})",
                    body_text=f"Sender: {sender}\nSubject: {subject}\nBody:\n{body}",
                )
            except Exception:
                pass

    return {
        "status": "received",
        "sender": sender,
        "parsed": {"address": parsed_address, "datetime": parsed_datetime, "county": parsed_county},
        "match": match_info,
        "attachments": [a['filename'] for a in attachments] if attachments else []
    }
