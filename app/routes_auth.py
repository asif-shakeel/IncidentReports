# =============================
# FILE: app/routes_auth.py
# =============================
import os, logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.database import get_db
from app.models import User, IncidentRequest
from app.schemas import RegisterRequest, IncidentRequestCreate
from app.config import get_county_email_map
from app.email_io import send_request_email
from auth import get_password_hash, verify_password, create_access_token

SECRET_KEY  = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM   = os.getenv("ALGORITHM", "HS256")

logger = logging.getLogger("uvicorn.error").getChild("auth")
router = APIRouter(tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if user:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = get_password_hash(req.password)
    new_user = User(username=req.username, hashed_password=hashed_password, email=req.email)
    db.add(new_user); db.commit(); db.refresh(new_user)
    return {"msg": "User registered successfully"}

@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# dependency for other routes
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
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
    county_email = get_county_email_map().get(req.county)
    if not county_email:
        raise HTTPException(status_code=400, detail="No email found for this county")

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
    content = (
        "Please provide the incident report for the following details:\\n"
        f"Address: {req.incident_address}\\nDate/Time: {req.incident_datetime}\\nCounty: {req.county}"
    )
    try:
        send_request_email(county_email, subject, content,
                            incident_address=req.incident_address,
                            incident_datetime=req.incident_datetime,
                            county=req.county)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}
