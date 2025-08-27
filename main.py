from fastapi import FastAPI, HTTPException, Depends, Body, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import csv
import os
from auth import get_password_hash, verify_password, create_access_token
from dotenv import load_dotenv

# Optional: import for LLM parsing
from openai import OpenAI
import json

# Load environment variables
load_dotenv()

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
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

# Load county-email mapping from CSV
COUNTY_EMAIL_MAP = {}
with open('ca_all_counties_fire_records_contacts_template.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        COUNTY_EMAIL_MAP[row['County']] = row['Request Email']

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = "request@incidentreportshub.com"

# Optional: OpenAI client for LLM parsing
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# FastAPI app
app = FastAPI(title="IncidentReportHub Backend Phase 1 - Postgres")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# Pydantic models
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: EmailStr

class IncidentRequestCreate(BaseModel):
    incident_address: str
    incident_datetime: str
    county: str

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoints
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

    # Send email via SendGrid
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

# Inbound parsing with LLM fallback
@app.post('/inbound')
async def inbound_parse(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sender = form.get('from')
    subject = form.get('subject')
    body = form.get('text')

    if not sender or not body:
        raise HTTPException(status_code=400, detail="Invalid inbound email payload")

    # Try simple parsing first
    parsed_address = parsed_datetime = parsed_county = None
    for line in body.splitlines():
        line = line.strip()
        if line.lower().startswith('address:'):
            parsed_address = line[len('Address:'):].strip()
        elif line.lower().startswith('date/time:'):
            parsed_datetime = line[len('Date/Time:'):].strip()
        elif line.lower().startswith('county:'):
            parsed_county = line[len('County:'):].strip()

    # If parsing failed, use LLM
    if not (parsed_address and parsed_datetime and parsed_county):
        prompt = f"Extract the address, datetime, and county from this email text and return as JSON:\n{body}\n\nFormat: {json.dumps({'address':'','datetime':'','county':''})}"
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            llm_parsed = json.loads(response.choices[0].message.content)
            parsed_address = parsed_address or llm_parsed.get('address')
            parsed_datetime = parsed_datetime or llm_parsed.get('datetime')
            parsed_county = parsed_county or llm_parsed.get('county')
        except Exception:
            pass

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

    match_info = None
    if parsed_address and parsed_datetime and parsed_county:
        match = db.query(IncidentRequest).filter(
            IncidentRequest.incident_address.ilike(f"%{parsed_address}%"),
            IncidentRequest.incident_datetime.ilike(f"%{parsed_datetime}%"),
            IncidentRequest.county.ilike(f"%{parsed_county}%")
        ).first()
        if match:
            match_info = {"incident_request_id": match.id}

    return {
        "status": "received",
        "sender": sender,
        "parsed": {"address": parsed_address, "datetime": parsed_datetime, "county": parsed_county},
        "match": match_info
    }
