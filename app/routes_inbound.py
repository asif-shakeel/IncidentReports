# ================================
# FILE: app/routes_inbound.py
# ================================
from fastapi import APIRouter, Form, UploadFile, Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.email_parser import parse_inbound_email
import logging

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/inbound")
async def inbound(
    request: Request,
    db: Session = Depends(get_db),
    subject: str = Form(None),
    sender: str = Form(None),
    text: str = Form(None),
    html: str = Form(None),
    attachments: int = Form(0),
    attachment1: UploadFile | None = None,
):
    log.info("[inbound] received form keys: %s", list((await request.form()).keys()))

    address, dt_str, county = parse_inbound_email(text, html)
    inbound_row = models.InboundEmail(
        sender=sender,
        subject=subject,
        body=(text or html or "")[:10000],
        parsed_address=address,
        parsed_datetime=dt_str,
        parsed_county=county,
        has_attachments=bool(attachments),
        attachment_count=int(attachments or 0),
    )
    db.add(inbound_row)
    db.commit()
    db.refresh(inbound_row)

    return {"status": "received", "sender": sender, "parsed": {"address": address, "datetime": dt_str, "county": county}, "attachments": inbound_row.attachment_count}