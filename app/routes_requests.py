# ================================
# FILE: app/routes_requests.py
# ================================
import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.database import get_db
from app.models import User, IncidentRequest
from app.schemas import IncidentRequestCreate
from app.config import get_county_email
from app.email_io import send_request_email

log = logging.getLogger("uvicorn.error").getChild("routes_requests")
router = APIRouter(tags=["requests"]) 

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
ALGORITHM  = os.getenv("ALGORITHM", "HS256")


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
    county_email = get_county_email(req.county)
    if not county_email:
        raise HTTPException(status_code=400, detail=f"No email found for county '{req.county}'")

    new_req = IncidentRequest(
        created_by=current_user.username,
        requester_email=current_user.email,
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
        county_email=county_email,
    )
    db.add(new_req); db.commit(); db.refresh(new_req)

    subject = f"Fire Incident Report Request: {req.incident_datetime}"
    try:
        send_request_email(
            to_email=county_email,
            subject=subject,
            incident_address=req.incident_address,
            incident_datetime=req.incident_datetime,
            county=req.county,
        )
        log.info("[request] sent to %s for %s / %s / %s", county_email, req.incident_address, req.incident_datetime, req.county)
    except Exception as e:
        log.warning("[request] send failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")

    return {"msg": "Incident request created and email sent", "request_id": new_req.id}