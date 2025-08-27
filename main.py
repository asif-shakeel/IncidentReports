# main.py
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from models import User, IncidentRequest
from auth import get_password_hash, verify_password, create_access_token
import csv
import os
from fastapi import FastAPI, Request

# Load county-email mapping from CSV
COUNTY_EMAIL_MAP = {}
with open('ca_all_counties_fire_records_contacts_template.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        COUNTY_EMAIL_MAP[row['County']] = row['Request Email']

app = FastAPI(title="IncidentReportHub Backend Phase 1")

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

# Register user endpoint
@app.post('/register')
def register(username: str, password: str, email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if user:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = get_password_hash(password)
    new_user = User(username=username, hashed_password=hashed_password, email=email)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"msg": "User registered successfully"}

# Token endpoint
@app.post('/token')
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# Create incident request
@app.post('/incident_request')
def create_incident_request(incident_address: str, incident_datetime: str, county: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    email = COUNTY_EMAIL_MAP.get(county, None)
    if not email:
        raise HTTPException(status_code=400, detail="No email found for this county")
    new_request = IncidentRequest(user_token=token, incident_address=incident_address, incident_datetime=incident_datetime, county=county, county_email=email)
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    return {"msg": "Incident request created", "request_id": new_request.id}





@app.post('/inbound')
async def inbound_parse(request: Request):
    form = await request.form()
    sender = form.get('from')
    subject = form.get('subject')
    body = form.get('text')
    # TODO: parse incident address/date and store in DB
    return {"status": "received"}