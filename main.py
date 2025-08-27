from fastapi import FastAPI, HTTPException, Depends, Body, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import csv
import os
import re
import json
from auth import get_password_hash, verify_password, create_access_token, SECRET_KEY, ALGORITHM
from dotenv import load_dotenv

# Optional: OpenAI client (LLM fallback)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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
    county_email = Column(String)  # destination office email

class InboundEmail(Base):
    __tablename__ = 'inbound_emails'
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    subject = Column(String)
    body = Column(String)
    parsed_address = Column(String, nullable=True)
    parsed_datetime = Column(String, nullable=True)
    parsed_county = Column(String, nullable=True)

COUNTY_EMAIL_MAP = {}
with open('ca_all_counties_fire_records_contacts_template.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        COUNTY_EMAIL_MAP[row['County']] = row['Request Email']

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = "request@incidentreportshub.com"
ALERT_EMAIL = "alert@incidentreportshub.com"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if (OPENAI_API_KEY and OpenAI) else None

app = FastAPI(title="IncidentReportHub Backend Phase 1 - Postgres")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: EmailStr

class IncidentRequestCreate(BaseModel):
    incident_address: str
    incident_datetime: str
    county: str

# Helpers

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def normalize(s: str) -> str:
    """Lowercase, strip punctuation except spaces/digits/letters, collapse whitespace."""
    if not s:
        return ''
    s = re.sub(r'[^0-9a-zA-Z ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()

@app.post('/register')
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

@app.post('/token')
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post('/incident_request')
def create_incident_request(req: IncidentRequestCreate, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    email = COUNTY_EMAIL_MAP.get(req.county)
    if not email:
        raise HTTPException(status_code=400, detail="No email found for this county")

    new_request = IncidentRequest(
        user_token=token,
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
        county_email=email
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    if SENDGRID_API_KEY:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        subject = f"Fire Incident Report Request: {req.incident_datetime}"
        content = (
            f"Please provide the incident report for the following details:\n"
            f"Address: {req.incident_address}\nDate/Time: {req.incident_datetime}\nCounty: {req.county}"
        )
        message = Mail(from_email=FROM_EMAIL, to_emails=email, subject=subject, plain_text_content=content)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}

@app.post('/inbound')
async def inbound_parse(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sender = form.get('from')
    subject = form.get('subject')
    body = form.get('text')

    if not sender or not body:
        raise HTTPException(status_code=400, detail="Invalid inbound email payload")

    # 1) Simple rule-based parse first
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

    # 2) Collect attachments (SendGrid inbound uses file parts; keys vary)
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

    # 3) LLM fallback if any field missing
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
            # swallow errors and continue with whatever we have
            pass

    # 4) Persist inbound record
    inbound_record = InboundEmail(
        sender=sender,
        subject=subject or '',
        body=body,
        parsed_address=parsed_address,
        parsed_datetime=parsed_datetime,
        parsed_county=parsed_county
    )
    db.add(inbound_record)
    db.commit()

    # 5) Robust matching: normalize and compare in Python after a coarse DB filter
    match_info = None
    matched_request = None
    if parsed_address and parsed_datetime and parsed_county:
        p_addr = normalize(parsed_address)
        p_dt = normalize(parsed_datetime)
        candidates = db.query(IncidentRequest).filter(IncidentRequest.county.ilike(f"%{parsed_county}%")).all()
        for cand in candidates:
            if normalize(cand.incident_address) == p_addr and normalize(cand.incident_datetime) == p_dt:
                matched_request = cand
                match_info = {"incident_request_id": cand.id}
                break

    # 6) If matched, deliver attachments to the requesting user; else alert
    if matched_request:
        # Decode username from the JWT stored in user_token and find the user's email
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

        # If we have attachments and a recipient, email them out via SendGrid
        if SENDGRID_API_KEY and attachments and recipient_email:
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail, Attachment, Disposition
                import base64

                message = Mail(
                    from_email=FROM_EMAIL,
                    to_emails=recipient_email,
                    subject=f"Your Incident Report(s) for {matched_request.incident_address}",
                    plain_text_content=(
                        f"We matched a response from the county office to your request.\n"
                        f"Incident: {matched_request.incident_address} @ {matched_request.incident_datetime} ({matched_request.county})"
                    ),
                )
                # Add all attachments
                for att in attachments:
                    encoded = base64.b64encode(att['content']).decode('utf-8')
                    attach = Attachment()
                    attach.file_content = encoded
                    attach.file_type = att['content_type']
                    attach.file_name = att['filename']
                    attach.disposition = Disposition("attachment")
                    # sendgrid's Mail supports a list via .add_attachment
                    try:
                        message.add_attachment(attach)
                    except Exception:
                        # older versions use .attachment single: fallback
                        message.attachment = attach
                sg = SendGridAPIClient(SENDGRID_API_KEY)
                sg.send(message)
            except Exception:
                # best-effort; don't fail webhook
                pass
        elif SENDGRID_API_KEY and not attachments:
            # No attachments from county -> alert
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail
                alert = Mail(
                    from_email=FROM_EMAIL,
                    to_emails=ALERT_EMAIL,
                    subject=f"No attachments in county reply (request {matched_request.id})",
                    plain_text_content=(
                        f"Sender: {sender}\nSubject: {subject}\nBody:\n{body}"
                    ),
                )
                sg = SendGridAPIClient(SENDGRID_API_KEY)
                sg.send(alert)
            except Exception:
                pass

    return {
        "status": "received",
        "sender": sender,
        "parsed": {"address": parsed_address, "datetime": parsed_datetime, "county": parsed_county},
        "match": match_info,
        "attachments": [a['filename'] for a in attachments] if attachments else []
    }

# add temporarily to main.py
@app.get("/admin/dbinfo")
def dbinfo():
    import sqlalchemy as sa
    url = str(engine.url).replace(engine.url.password or "", "****")
    with engine.connect() as conn:
        users = conn.execute(sa.text("select count(*) from users")).scalar()
        reqs  = conn.execute(sa.text("select count(*) from incident_requests")).scalar()
        inbound = conn.execute(sa.text("select count(*) from inbound_emails")).scalar()
    return {"database_url": url, "counts": {"users": users, "incident_requests": reqs, "inbound_emails": inbound}}
