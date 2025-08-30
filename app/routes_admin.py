# ================================
# FILE: app/routes_admin.py
# ================================
import os
import logging
import httpx
from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import InboundEmail

router = APIRouter(tags=["admin"])
log = logging.getLogger("uvicorn.error").getChild("routes_admin")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

@router.get("/admin/forward_status")
def forward_status(
    inbound_id: int | None = Query(default=None),
    sg_msg_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Returns stored forward tracking for an inbound row. If SendGrid Email Activity API
    is available for your account, also attempts a live lookup.
    """
    if not (inbound_id or sg_msg_id):
        raise HTTPException(status_code=400, detail="Provide inbound_id or sg_msg_id")

    row = None
    if inbound_id:
        row = db.query(InboundEmail).filter(InboundEmail.id == inbound_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="InboundEmail not found")
        if not sg_msg_id:
            sg_msg_id = row.forward_sg_message_id

    out = {
        "inbound_id": getattr(row, "id", None),
        "forwarded_to": getattr(row, "forwarded_to", None),
        "forward_status": getattr(row, "forward_status", None),
        "forwarded_at": getattr(row, "forwarded_at", None),
        "sg_msg_id": sg_msg_id,
    }

    # Optional live lookup via Email Activity API
    activity = None
    if sg_msg_id and SENDGRID_API_KEY:
        try:
            q = f'msg_id="{sg_msg_id}"'
            url = "https://api.sendgrid.com/v3/messages"
            headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}"}
            params = {"query": q, "limit": 1}
            with httpx.Client(timeout=10.0) as client:
                r = client.get(url, headers=headers, params=params)
                if r.status_code == 200:
                    activity = r.json()
                else:
                    log.info("[admin] activity lookup status=%s body=%s", r.status_code, r.text[:400])
        except Exception as e:
            log.info("[admin] activity lookup error: %s", e)

    out["activity"] = activity
    return out
