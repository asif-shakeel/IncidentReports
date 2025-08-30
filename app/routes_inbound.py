# ================================
# FILE: app/routes_inbound.py
# ================================
import os
import uuid
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.email_parser import parse_inbound_email
from app.utils import normalize, normalize_datetime
from app.email_io import send_attachments_to_user, send_alert_no_attachments

log = logging.getLogger("uvicorn.error").getChild("routes_inbound")
router = APIRouter(tags=["inbound"]) 

TMP_DIR = Path(os.getenv("INBOUND_TMP", "/tmp/irh_inbound"))
TMP_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/inbound")
async def inbound(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    keys = list(form.keys())
    log.info("[inbound] received form keys: %s", keys)

    subject = form.get("subject", "")
    sender  = form.get("from", "")
    text    = form.get("text", "")
    html    = form.get("html", "")

    # attachments
    try:
        att_count = int(form.get("attachments", "0") or 0)
    except Exception:
        att_count = 0

    files: List[dict] = []
    if att_count:
        for k in list(form.keys()):
            if not str(k).startswith("attachment"):
                continue
            up = form.get(k)
            try:
                filename = getattr(up, "filename", f"file-{uuid.uuid4().hex}")
                ctype    = getattr(up, "content_type", None)
                dest = TMP_DIR / f"{uuid.uuid4().hex}-{filename}"
                data = await up.read()
                dest.write_bytes(data)
                files.append({"path": str(dest), "filename": filename, "type": ctype or "application/octet-stream"})
            except Exception as e:
                log.warning("[inbound] failed to save attachment %s: %s", k, e)

    log.info("[inbound] attachment_count=%d", len(files))

    address, dt_str, county = parse_inbound_email(text, html)
    log.info("[inbound] parsed addr=%r dt=%r county=%r", address, dt_str, county)

    # persist
    try:
        inbound_row = models.InboundEmail(
            sender=sender,
            subject=subject,
            body=(text or html or "")[:10000],
            parsed_address=address or None,
            parsed_datetime=dt_str or None,
            parsed_county=county or None,
            has_attachments=bool(files),
            attachment_count=len(files),
        )
        db.add(inbound_row); db.commit(); db.refresh(inbound_row)
        inbound_id = inbound_row.id
    except Exception as e:
        log.warning("[inbound] persist failed: %s", e)
        inbound_id = None

    # match + forward
    match_info = None
    try:
        if address and dt_str and county:
            n_addr = normalize(address)
            n_dt   = normalize_datetime(dt_str)
            n_cnty = normalize(county)

            q = db.query(models.IncidentRequest).filter(models.IncidentRequest.county == county)
            for row in q.all():
                if (
                    normalize(row.incident_address) == n_addr and
                    normalize_datetime(row.incident_datetime) == n_dt and
                    normalize(row.county) == n_cnty
                ):
                    match_info = row
                    break

            if match_info:
                recipient = match_info.requester_email
                if not recipient and match_info.created_by:
                    u = db.query(models.User).filter(models.User.username == match_info.created_by).first()
                    recipient = u.email if u else None

                if recipient:
                    if files:
                        send_attachments_to_user(
                            to_email=recipient,
                            subject=f"Incident report reply — {address}",
                            body="Attached is the response we received.",
                            files=files,
                        )
                        log.info("[forward] dispatched to %s (with_files=True)", recipient)
                    else:
                        send_alert_no_attachments(
                            to_email=recipient,
                            subject=f"Incident report reply — {address}",
                            incident_address=address,
                            incident_datetime=dt_str,
                            county=county,
                        )
                        log.info("[forward] alerted %s (no_files)", recipient)
                else:
                    log.warning("[forward] no recipient email available for matched id=%s", match_info.id)
        else:
            log.info("[match] not attempted; missing parsed fields")
    except Exception as e:
        log.warning("[match] lookup failed: %s", e)

    # cleanup
    for f in files:
        try:
            Path(f["path"]).unlink(missing_ok=True)
        except Exception:
            pass

    return JSONResponse({
        "status": "received",
        "sender": sender,
        "parsed": {"address": address, "datetime": dt_str, "county": county},
        "match": getattr(match_info, "id", None),
        "attachments": [f.get("filename") for f in files],
        "inbound_id": inbound_id,
    })