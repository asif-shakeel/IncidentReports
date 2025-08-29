# =============================
# FILE: app/routes_requests.py  (auth-required version)
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

# Require auth: use your existing dependency from routes_auth
try:
    from app.routes_auth import get_current_user  # -> returns models.User
except Exception:
    # Fallback minimal verifier if your project doesn't export get_current_user
    import jwt
    try:
        from app.config import SECRET_KEY, ALGORITHM
    except Exception:
        from auth import SECRET_KEY, ALGORITHM  # root-level fallback

    def get_current_user(authorization: str | None = None, db: Session = Depends(get_db)):
        """Very small fallback that expects Authorization: Bearer <token>"""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
        username = payload.get("sub") or payload.get("username")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        user = db.query(models.User).filter(models.User.username == username).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

logger = logging.getLogger("uvicorn.error").getChild("requests")
requests_router = APIRouter(tags=["requests"])  # avoid name clash with other routers


# -------- Pydantic schema (no username needed; we use auth user) --------
class IncidentRequestIn(BaseModel):
    incident_address: str = Field(..., min_length=3)
    incident_datetime: str = Field(..., description="e.g. '2025-08-01 10:00'")
    county: str = Field(..., min_length=2)
    to_email: EmailStr


# -------- Routes --------
@requests_router.post("/incident_request")
def create_incident_request(
    data: IncidentRequestIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # 1) Persist IncidentRequest
    colnames = {c.name for c in models.IncidentRequest.__table__.columns}
    req_kwargs = {
        "incident_address": data.incident_address.strip(),
        "incident_datetime": data.incident_datetime.strip(),
        "county": data.county.strip(),
        "to_email": str(data.to_email),
    }

    # If your table tracks who created the request, set it
    if "created_by" in colnames:
        req_kwargs["created_by"] = current_user.username
    if "user_token" in colnames:
        # store the caller's token so inbound can route replies back
        # NOTE: only works if your get_current_user attaches a token attr; otherwise omit
        token = getattr(current_user, "token", None)
        if token:
            req_kwargs["user_token"] = token

    try:
        req = models.IncidentRequest(**{k: v for k, v in req_kwargs.items() if k in colnames})
        db.add(req)
        db.commit()
        db.refresh(req)
    except Exception as e:
        logger.warning(f"[requests] persist failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to persist incident request")

    # 2) Compose and send outbound email WITH machine-readable headers
    subject = f"Fire Incident Report Request: {data.incident_datetime}"
    content = (
        "Please provide the incident report for the following details:\n"
        f"Address: {data.incident_address}\n"
        f"Date/Time: {data.incident_datetime}\n"
        f"County: {data.county}\n"
    )

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

    return {"id": req.id, "status": "sent", "to_email": str(data.to_email), "subject": subject}
