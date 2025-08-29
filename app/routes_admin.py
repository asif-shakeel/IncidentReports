# ================================
# FILE: app/routes_admin.py
# ================================
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, IncidentRequest, InboundEmail
import os

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")

@router.get("/admin/users")
def list_users(token: str, db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return db.query(User).all()

@router.get("/admin/incident_requests")
def list_requests(token: str, db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return db.query(IncidentRequest).all()

@router.get("/admin/inbound_emails")
def list_inbound(token: str, db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return db.query(InboundEmail).all()