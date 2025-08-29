# =============================
# FILE: app/routes_requests.py
# Purpose: Create Incident Requests and send outbound emails that include
#          machine-readable headers (X-IRH-*) for robust reply parsing.
# =============================
from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.email_io import send_request_email

# SECRET signing for optional per-request user token
try:
    from app.config import SECRET_KEY, ALGORITHM
except Exception:  # root-level fallback
    from auth import SECRET_KEY, ALGORITHM  # type: ignore

import jwt

logger = logging.getLogger("uvicorn.error").getChild("requests")
router = APIRouter()


# -------- Pydantic schemas --------
class IncidentRequestIn(BaseModel):
    incident_address: str = Field(..., min_length=3)
    incident_datetime: str = Field(..., description="e.g. '2025-08-01 10:00'")
    county: str = Field(..., min_length=2)
    to_email: EmailStr
    # Optionally associate with a user so replies can be forwarded later
    username: Optional[str] = None


class IncidentRequestOut(BaseModel):
    id: int
    status: str
    to_email: EmailStr
    subject: str


# -------- Helpers --------

def _maybe_make_user_token(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    try:
        return jwt.encode({"sub": username}, SECRET_KEY, algorithm=ALGORITHM)
    except Exception as e:
        logger.warning(f"[requests] token build failed: {e}")
        return None


# -------- Routes --------

@router.post("/incident_request", response_model=IncidentRequestOut)
def create_incident_request(data: IncidentRequestIn, db: Session = Depends(get_db)):
    # 1) Persist IncidentRequest (columns may vary slightly; we guard by model columns)
    colnames = {c.name for c in models.IncidentRequest.__table__.columns}
    req_kwargs = {
        "incident_address": data.incident_address.strip(),
        "incident_datetime": data.incident_datetime.strip(),
        "county": data.county.strip(),
    }
    if "to_email" in colnames:
        req_kwargs["to_email"] = str(data.to_email)

    user_token = _maybe_make_user_token(data.username)
    if user_token and "user_token" in colnames:
        req_kwargs["user_token"] = user_token

    try:
        req = models.IncidentRequest(**{k: v for k, v in req_kwargs.items() if k in colnames})
        db.add(req)
        db.commit()
        db.refresh(req)
    except Exception as e:
        logger.warning(f"[requests] persist failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to persist incident request")

    # 2) Compose email
    subject = f"Fire Incident Report Request: {data.incident_datetime}"
    content = (
        "Please provide the incident report for the following details:\n"
        f"Address: {data.incident_address}\n"
        f"Date/Time: {data.incident_datetime}\n"
        f"County: {data.county}\n"
    )

    # 3) Send outbound with machine-readable headers
    try:
        send_request_email(
            to_email=str(data.to_email),
            subject=subject,
            content=content,
            incident_address=data.incident_address,
            incident_datetime=data.incident_datetime,
            county=data.county,
        )
    except Exception as e:
        logger.warning(f"[requests] send failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")

    return IncidentRequestOut(id=req.id, status="sent", to_email=data.to_email, subject=subject)


@router.get("/incident_request/recent")
def list_recent_requests(limit: int = 20, db: Session = Depends(get_db)):
    q = db.query(models.IncidentRequest)
    if hasattr(models.IncidentRequest, "created_at"):
        q = q.order_by(models.IncidentRequest.created_at.desc())
    else:
        q = q.order_by(models.IncidentRequest.id.desc())
    rows = q.limit(max(1, min(limit, 100))).all()
    return [
        {
            "id": r.id,
            "incident_address": getattr(r, "incident_address", None),
            "incident_datetime": getattr(r, "incident_datetime", None),
            "county": getattr(r, "county", None),
            "to_email": getattr(r, "to_email", None),
            "created_at": getattr(r, "created_at", None),
        }
        for r in rows
    ]
