# ================================
# FILE: main.py
# ================================
from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Local modules
from app.database import engine
from app.routes_auth import router as auth_router
from app.routes_inbound import router as inbound_router
from app.routes_admin import router as admin_router

load_dotenv()

show_docs = os.getenv("SHOW_DOCS", "1") == "1"
app = FastAPI(
    title="IncidentReportHub Backend Phase 1 - Postgres",
    docs_url="/docs" if show_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if show_docs else None,
    swagger_ui_parameters={
        "docExpansion": "none",
        "defaultModelsExpandDepth": -1,
    },
)

# Routers
app.include_router(auth_router)
app.include_router(inbound_router)
app.include_router(admin_router)

# Health check
@app.get("/healthz", tags=["ops"])
def healthz():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("select 1")
        db_ok = True
    except Exception:
        db_ok = False
    return {"ok": True, "db": db_ok}


# ================================
# FILE: app/__init__.py
# ================================
# empty package marker

# ================================
# FILE: app/config.py
# ================================
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
FROM_EMAIL = os.getenv("FROM_EMAIL", "request@incidentreportshub.com")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "alert@incidentreportshub.com")
INBOUND_RPS = int(os.getenv("INBOUND_RPS", "5"))
WINDOW_SECS = int(os.getenv("INBOUND_WINDOW_SECS", "10"))

# County email CSV (lazy-loaded)
import csv

COUNTY_EMAIL_MAP = None

def get_county_email_map():
    global COUNTY_EMAIL_MAP
    if COUNTY_EMAIL_MAP is None:
        COUNTY_EMAIL_MAP = {}
        with open('ca_all_counties_fire_records_contacts_template.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                COUNTY_EMAIL_MAP[row['County']] = row['Request Email']
    return COUNTY_EMAIL_MAP

# ================================
# FILE: app/database.py
# ================================
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ================================
# FILE: app/models.py
# ================================
from sqlalchemy import Column, Integer, String
from app.database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, nullable=False)

class IncidentRequest(Base):
    __tablename__ = 'incident_requests'
    id = Column(Integer, primary_key=True, index=True)
    user_token = Column(String)
    incident_address = Column(String)
    incident_datetime = Column(String)
    county = Column(String)
    county_email = Column(String)

class InboundEmail(Base):
    __tablename__ = 'inbound_emails'
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    subject = Column(String)
    body = Column(String)
    parsed_address = Column(String, nullable=True)
    parsed_datetime = Column(String, nullable=True)
    parsed_county = Column(String, nullable=True)

# ================================
# FILE: app/schemas.py
# ================================
from pydantic import BaseModel, EmailStr

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: EmailStr

class IncidentRequestCreate(BaseModel):
    incident_address: str
    incident_datetime: str
    county: str

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

# ================================
# FILE: app/email_io.py
# ================================
from app.config import SENDGRID_API_KEY, FROM_EMAIL, ALERT_EMAIL

# SendGrid helpers are imported only when needed to keep import cost low

def send_request_email(to_email: str, subject: str, content: str):
    if not SENDGRID_API_KEY:
        return
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    message = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=content)
    sg.send(message)

def send_attachments_to_user(recipient_email: str, subject: str, body_text: str, attachments):
    if not SENDGRID_API_KEY or not recipient_email or not attachments:
        return
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Attachment, Disposition
    import base64

    message = Mail(from_email=FROM_EMAIL, to_emails=recipient_email, subject=subject, plain_text_content=body_text)
    for att in attachments:
        encoded = base64.b64encode(att['content']).decode('utf-8')
        attach = Attachment()
        attach.file_content = encoded
        attach.file_type = att['content_type']
        attach.file_name = att['filename']
        attach.disposition = Disposition("attachment")
        try:
            message.add_attachment(attach)
        except Exception:
            message.attachment = attach
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)

def send_alert_no_attachments(subject: str, body_text: str):
    if not SENDGRID_API_KEY:
        return
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    alert = Mail(from_email=FROM_EMAIL, to_emails=ALERT_EMAIL, subject=subject, plain_text_content=body_text)
    sg.send(alert)

# ================================
# FILE: app/routes_auth.py
# ================================
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, IncidentRequest
from app.schemas import RegisterRequest, IncidentRequestCreate
from app.config import OPENAI_API_KEY
from app.config import get_county_email_map
from app.email_io import send_request_email
from auth import get_password_hash, verify_password, create_access_token

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

@router.post('/register')
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if user:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = get_password_hash(req.password)
    new_user = User(username=req.username, hashed_password=hashed_password, email=req.email)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"msg": "User registered successfully"}

@router.post('/token')
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post('/incident_request')
def create_incident_request(req: IncidentRequestCreate, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    county_email = get_county_email_map().get(req.county)
    if not county_email:
        raise HTTPException(status_code=400, detail="No email found for this county")

    new_request = IncidentRequest(
        user_token=token,
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
        county_email=county_email,
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    subject = f"Fire Incident Report Request: {req.incident_datetime}"
    content = (
        f"Please provide the incident report for the following details:\n"
        f"Address: {req.incident_address}\nDate/Time: {req.incident_datetime}\nCounty: {req.county}"
    )
    try:
        send_request_email(county_email, subject, content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}

# ================================
# FILE: app/routes_inbound.py
# ================================
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import IncidentRequest, InboundEmail, User
from app.utils import normalize, normalize_datetime, rate_limit_sender
from app.config import OPENAI_API_KEY
from app.email_io import send_attachments_to_user, send_alert_no_attachments
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

# ================================
# FILE: app/routes_admin.py
# ================================
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, IncidentRequest, InboundEmail
from app.config import ADMIN_TOKEN

router = APIRouter()

def require_admin(request: Request):
    token = request.headers.get("X-Admin-Token")
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized (admin)")

@router.get("/admin/requests", tags=["admin"])
def admin_list_requests(request: Request, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_admin(request)
    rows = db.query(IncidentRequest).order_by(IncidentRequest.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "address": r.incident_address,
            "datetime": r.incident_datetime,
            "county": r.county,
            "county_email": r.county_email,
        } for r in rows
    ]

@router.get("/admin/inbound", tags=["admin"])
def admin_list_inbound(request: Request, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_admin(request)
    rows = db.query(InboundEmail).order_by(InboundEmail.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "sender": r.sender,
            "subject": r.subject,
            "parsed": {"address": r.parsed_address, "datetime": r.parsed_datetime, "county": r.parsed_county},
        } for r in rows
    ]

@router.get("/admin/users", tags=["admin"])
def admin_list_users(request: Request, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_admin(request)
    rows = db.query(User).order_by(User.id.desc()).offset(offset).limit(limit).all()
    return [{"id": u.id, "username": u.username, "email": u.email} for u in rows]
