# ================================
# FILE: app/routes_admin.py
# ================================
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
# from app.database import get_db
# from app.models import User, IncidentRequest, InboundEmail
# from app.config import ADMIN_TOKEN

from .database import get_db
from .models import User, IncidentRequest, InboundEmail
from .schemas import RegisterRequest, IncidentRequestCreate
from .config import get_county_email_map, OPENAI_API_KEY, ADMIN_TOKEN
from .email_io import send_request_email, send_attachments_to_user, send_alert_no_attachments
from .utils import normalize, normalize_datetime, rate_limit_sender

router = APIRouter()

def require_admin(request: Request):
    token = request.headers.get("X-Admin-Token")
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized (admin)")

@router.get("/admin/requests", tags=["admin"])
def admin_list_requests(request: Request, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_admin(request)
    rows = db.query(IncidentRequest).order_by(IncidentRequest.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "address": r.incident_address,
            "datetime": r.incident_datetime,
            "county": r.county,
            "county_email": r.county_email,
        } for r in rows
    ]

@router.get("/admin/inbound", tags=["admin"])
def admin_list_inbound(request: Request, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_admin(request)
    rows = db.query(InboundEmail).order_by(InboundEmail.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "sender": r.sender,
            "subject": r.subject,
            "parsed": {"address": r.parsed_address, "datetime": r.parsed_datetime, "county": r.parsed_county},
        } for r in rows
    ]

@router.get("/admin/users", tags=["admin"])
def admin_list_users(request: Request, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_admin(request)
    rows = db.query(User).order_by(User.id.desc()).offset(offset).limit(limit).all()
    return [{"id": u.id, "username": u.username, "email": u.email} for u in rows]
