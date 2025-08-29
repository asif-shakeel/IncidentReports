# ================================
# FILE: app/routes_auth.py
# ================================
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, IncidentRequest
from .schemas import RegisterRequest, IncidentRequestCreate
from .config import get_county_email_map
from .email_io import send_request_email
from auth import get_password_hash, verify_password, create_access_token

# For decoding JWTs if other modules need current-user info here
import jwt  # PyJWT
try:
    # Prefer app.config for secrets if present
    from .config import SECRET_KEY, ALGORITHM  # type: ignore
except Exception:
    # Fallback if your secrets live in the root auth module
    from auth import SECRET_KEY, ALGORITHM  # type: ignore

logger = logging.getLogger("uvicorn.error").getChild("auth")
router = APIRouter(tags=["auth"])

# OAuth2 bearer flow for /token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# -------------------------------
# Auth helpers
# -------------------------------
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the Bearer token, load the User from DB, and return it.
    Requires SECRET_KEY and ALGORITHM to be configured.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    username = payload.get("sub") or payload.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# -------------------------------
# Routes: register & token
# -------------------------------
@router.post("/register")
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

@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# -------------------------------
# Route: create incident request (AUTH REQUIRED)
# -------------------------------
@router.post("/incident_request")
def create_incident_request(
    req: IncidentRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates an IncidentRequest, records who requested it, and emails the county.
    - Stores created_by = current_user.username
    - Stores requester_email = current_user.email
    - Looks up county recipient via get_county_email_map()
    """
    county_email = get_county_email_map().get(req.county)
    if not county_email:
        raise HTTPException(status_code=400, detail="No email found for this county")

    # Build row based on your current IncidentRequest schema
    new_request = IncidentRequest(
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
        county_email=county_email,
    )

    # Optional columns: set if present on your model/table
    # (Your models.py includes these now; make sure DB migration added them.)
    if hasattr(IncidentRequest, "created_by"):
        setattr(new_request, "created_by", current_user.username)
    if hasattr(IncidentRequest, "requester_email"):
        setattr(new_request, "requester_email", current_user.email)

    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    subject = f"Fire Incident Report Request: {req.incident_datetime}"
    content = (
        "Please provide the incident report for the following details:\n"
        f"Address: {req.incident_address}\n"
        f"Date/Time: {req.incident_datetime}\n"
        f"County: {req.county}"
    )

    try:
        # send_request_email(to_email, subject, content, incident_address=..., incident_datetime=..., county=...)
        send_request_email(
            to_email=county_email,
            subject=subject,
            content=content,
            incident_address=req.incident_address,
            incident_datetime=req.incident_datetime,
            county=req.county,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}

# Re-export for other modules to use
__all__ = ["router", "get_current_user"]


# # ================================
# # FILE: app/routes_auth.py
# # ================================
# from fastapi import APIRouter, Depends, HTTPException
# from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
# from sqlalchemy.orm import Session
# # from app.database import get_db
# # from app.models import User, IncidentRequest
# # from app.schemas import RegisterRequest, IncidentRequestCreate
# # from app.config import OPENAI_API_KEY
# # from app.config import get_county_email_map
# # from app.email_io import send_request_email
# from .database import get_db
# from .models import User, IncidentRequest, InboundEmail
# from .schemas import RegisterRequest, IncidentRequestCreate
# from .config import get_county_email_map, OPENAI_API_KEY, ADMIN_TOKEN
# from .email_io import send_request_email, send_attachments_to_user, send_alert_no_attachments
# from .utils import normalize, normalize_datetime, rate_limit_sender
# from auth import get_password_hash, verify_password, create_access_token

# router = APIRouter()
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# @router.post('/register')
# def register(req: RegisterRequest, db: Session = Depends(get_db)):
#     user = db.query(User).filter(User.username == req.username).first()
#     if user:
#         raise HTTPException(status_code=400, detail="Username already exists")
#     hashed_password = get_password_hash(req.password)
#     new_user = User(username=req.username, hashed_password=hashed_password, email=req.email)
#     db.add(new_user)
#     db.commit()
#     db.refresh(new_user)
#     return {"msg": "User registered successfully"}

# @router.post('/token')
# def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
#     user = db.query(User).filter(User.username == form_data.username).first()
#     if not user or not verify_password(form_data.password, user.hashed_password):
#         raise HTTPException(status_code=401, detail="Invalid credentials")
#     access_token = create_access_token(data={"sub": user.username})
#     return {"access_token": access_token, "token_type": "bearer"}

# @router.post('/incident_request')
# def create_incident_request(req: IncidentRequestCreate, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
#     county_email = get_county_email_map().get(req.county)
#     if not county_email:
#         raise HTTPException(status_code=400, detail="No email found for this county")

#     new_request = IncidentRequest(
#         user_token=token,
#         incident_address=req.incident_address,
#         incident_datetime=req.incident_datetime,
#         county=req.county,
#         county_email=county_email,
#     )
#     db.add(new_request)
#     db.commit()
#     db.refresh(new_request)

#     subject = f"Fire Incident Report Request: {req.incident_datetime}"
#     content = (
#         f"Please provide the incident report for the following details:\n"
#         f"Address: {req.incident_address}\nDate/Time: {req.incident_datetime}\nCounty: {req.county}"
#     )
#     try:
#         send_request_email(county_email, subject, content)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

#     return {"msg": "Incident request created and email sent", "request_id": new_request.id}