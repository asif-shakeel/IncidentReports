# =============================
# FILE: app/routes_auth.py
# =============================
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.database import get_db
from app.models import User, IncidentRequest
from app.schemas import RegisterRequest, IncidentRequestCreate
from app.config import get_county_email, SECRET_KEY, ALGORITHM
from app.email_io import send_request_email
from auth import get_password_hash, verify_password, create_access_token

log = logging.getLogger("uvicorn.error").getChild("routes_auth")

router = APIRouter(tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(username=req.username,
                hashed_password=get_password_hash(req.password),
                email=req.email)
    db.add(user); db.commit(); db.refresh(user)
    return {"msg": "User registered successfully"}

@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@router.post("/incident_request")
def create_incident_request(
    req: IncidentRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Sanity log: make sure we actually got these from the client
    log.info("[request] incoming fields addr=%r dt=%r county=%r",
             getattr(req, "incident_address", None),
             getattr(req, "incident_datetime", None),
             getattr(req, "county", None))

    county_email = get_county_email(req.county)
    if not county_email:
        raise HTTPException(status_code=400, detail=f"No email found for county '{req.county}'")

    new_request = IncidentRequest(
        created_by=current_user.username,
        requester_email=current_user.email,
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
        county_email=county_email,
    )
    db.add(new_request); db.commit(); db.refresh(new_request)

    subject = f"Fire Incident Report Request: {req.incident_datetime}"
    # We’ll still include a human-friendly plain text header in Content below
    content = "Please provide the incident report for the following details:"

    # Explicit keyword args so nothing goes blank
    send_request_email(
        to_email=county_email,
        subject=subject,
        content=content,
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
    )

    log.info("[request] sent to %s for %s / %s / %s",
             county_email, req.incident_address, req.incident_datetime, req.county)

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}
