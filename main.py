# IncidentReportHub Backend Phase 1 - Postgres Version

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from models import User, IncidentRequest
from auth import get_password_hash, verify_password, create_access_token
import csv
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Load county-email mapping from CSV
COUNTY_EMAIL_MAP = {}
with open('ca_all_counties_fire_records_contacts_template.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        COUNTY_EMAIL_MAP[row['County']] = row['Request Email']

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = "request@incidentreporthub.com"

# Postgres DB setup
# Use the DATABASE_URL provided by Render Postgres
# DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://incidentreports_postgres_user:EuRv9ILeWK8uC8M6syt0W90o5ujpgV9x@dpg-d2n6uqp5pdvs73ckeabg-a/incidentreports_postgres")  # Old SQLite comment can be ignored
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="IncidentReportHub Backend Phase 1 - Postgres")

# Create DB tables
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# User registration endpoint with try/except for debugging
@app.post('/register')
def register(username: str, password: str, email: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            raise HTTPException(status_code=400, detail="Username already exists")
        hashed_password = get_password_hash(password)
        new_user = User(username=username, hashed_password=hashed_password, email=email)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return {"msg": "User registered successfully"}
    except Exception as e:
        db.rollback()
        print(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Token endpoint
@app.post('/token')
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# Create incident request and send email with try/except
@app.post('/incident_request')
def create_incident_request(incident_address: str, incident_datetime: str, county: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    email = COUNTY_EMAIL_MAP.get(county, None)
    if not email:
        raise HTTPException(status_code=400, detail="No email found for this county")
    try:
        new_request = IncidentRequest(user_token=token, incident_address=incident_address, incident_datetime=incident_datetime, county=county, county_email=email)
        db.add(new_request)
        db.commit()
        db.refresh(new_request)
    except Exception as e:
        db.rollback()
        print(f"Error creating incident request: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Send email via SendGrid
    if SENDGRID_API_KEY:
        subject = f"Fire Incident Report Request: {incident_datetime}"
        content = f"Please provide the incident report for the following details:\nAddress: {incident_address}\nDate/Time: {incident_datetime}"
        message = Mail(from_email=FROM_EMAIL, to_emails=email, subject=subject, plain_text_content=content)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}

# Inbound parse endpoint to receive emails from SendGrid
@app.post('/inbound')
async def inbound_parse(request: Request):
    form = await request.form()
    sender = form.get('from')
    subject = form.get('subject')
    body = form.get('text')
    # TODO: parse incident address/date from body and store in DB
    return {"status": "received"}

# OpenAPI/Docs URL for reference: https://incidentreports-1.onrender.com/docs

# Note for deployment on Render:
# Add psycopg2-binary to requirements.txt to ensure Postgres driver is installed.
