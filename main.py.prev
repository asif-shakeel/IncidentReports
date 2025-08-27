# IncidentReportHub Backend Phase 1 - Postgres with Alembic Ready Setup

from fastapi import FastAPI, HTTPException, Depends, Request, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import csv
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from auth import get_password_hash, verify_password, create_access_token
from dotenv import load_dotenv

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

# Load county-email mapping from CSV
COUNTY_EMAIL_MAP = {}
with open('ca_all_counties_fire_records_contacts_template.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        COUNTY_EMAIL_MAP[row['County']] = row['Request Email']

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = "request@incidentreportshub.com"

# FastAPI app
app = FastAPI(title="IncidentReportHub Backend Phase 1 - Postgres")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# Pydantic models for request bodies
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: EmailStr

class IncidentRequestCreate(BaseModel):
    incident_address: str
    incident_datetime: str
    county: str

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# User registration endpoint
@app.post('/register', summary="Register a new user", description="Register a new user with username, password, and email.")
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

# Token endpoint
@app.post('/token', summary="Obtain access token", description="Provide username and password to receive a JWT access token.")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# Create incident request endpoint (request body version)
@app.post(
    '/incident_request',
    summary="Create a new incident report request",
    description="Submit a request for an incident report by providing the incident address, date/time, and county."
)
def create_incident_request(
    req: IncidentRequestCreate = Body(..., example={
        "incident_address": "123 Main St",
        "incident_datetime": "2025-08-26 14:00",
        "county": "Los Angeles"
    }),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
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
        subject = f"Fire Incident Report Request: {req.incident_datetime}"
        content = (
            f"Please provide the incident report for the following details:\n"
            f"Address: {req.incident_address}\nDate/Time: {req.incident_datetime}"
        )
        message = Mail(from_email=FROM_EMAIL, to_emails=email, subject=subject, plain_text_content=content)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}

# Inbound parse endpoint
@app.post('/inbound', summary="Receive inbound emails", description="Parse inbound emails for incident requests.")
async def inbound_parse(request: Request):
    form = await request.form()
    sender = form.get('from')
    subject = form.get('subject')
    body = form.get('text')
    # TODO: parse incident address/date from body and store in DB
    return {"status": "received"}

# Requirements note: ensure pydantic[email] is installed for EmailStr validation
