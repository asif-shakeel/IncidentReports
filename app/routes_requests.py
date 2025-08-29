# =============================
# FILE: app/routes_requests.py  (auth-required + auto county→email lookup)
# Lookup order: explicit override > DB CountyContact > CSV file > ENV JSON
# =============================
from __future__ import annotations
import logging
import json
import os
import csv
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.email_io import send_request_email

# Auth dependency (prefer your real one)
try:
    from app.routes_auth import get_current_user  # should return models.User
except Exception:  # lightweight fallback
    import jwt
    try:
        from app.config import SECRET_KEY, ALGORITHM
    except Exception:
        from auth import SECRET_KEY, ALGORITHM  # root-level fallback

    def get_current_user(authorization: str | None = None, db: Session = Depends(get_db)):
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
        # optionally expose token for downstream use
        setattr(user, "token", token)
        return user

logger = logging.getLogger("uvicorn.error").getChild("requests")
requests_router = APIRouter(tags=["requests"])  # use this name in main.py

# ---------- Config helpers ----------

def _env_county_map() -> dict[str, str]:
    """Load COUNTY_EMAIL_MAP env (JSON object {"County Name": "email"})."""
    raw = os.getenv("COUNTY_EMAIL_MAP", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).strip().lower(): str(v).strip() for k, v in data.items()}
    except Exception:
        logger.warning("[requests] bad COUNTY_EMAIL_MAP JSON; ignoring")
        return {}


@lru_cache(maxsize=1)
def _csv_county_map() -> dict[str, str]:
    """Load a county→email map from CSV once.
    Paths tried (first found wins):
      - $COUNTY_CONTACTS_CSV
      - ./ca_all_counties_fire_records_contacts.csv
      - ./ca_all_counties_fire_records_contacts_template.csv
    Accepts header variants: county|County|County Name, email|Email|Contact Email.
    """
    paths = []
    if os.getenv("COUNTY_CONTACTS_CSV"):
        paths.append(os.getenv("COUNTY_CONTACTS_CSV"))
    paths += [
        os.path.join(os.getcwd(), "ca_all_counties_fire_records_contacts.csv"),
        os.path.join(os.getcwd(), "ca_all_counties_fire_records_contacts_template.csv"),
    ]
    for p in paths:
        try:
            if not p or not os.path.exists(p):
                continue
            with open(p, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Normalize possible header names
                def pick(d: dict, keys: list[str]) -> str:
                    for k in keys:
                        if k in d and d[k]:
                            return str(d[k])
                    return ""
                out: dict[str, str] = {}
                for row in reader:
                    county = pick(row, ["county", "County", "County Name"]).strip()
                    email = pick(row, ["email", "Email", "Contact Email"]).strip()
                    if county and email:
                        out[county.lower()] = email
                if out:
                    logger.info(f"[requests] loaded county CSV map from {p} ({len(out)} entries)")
                    return out
        except Exception as e:
            logger.warning(f"[requests] CSV load failed for {p}: {e}")
    return {}


def _lookup_to_email(db: Session, county: str, override: Optional[str] = None) -> str:
    if override:
        return override
    name = (county or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="county is required")

    # 1) DB table if present: models.CountyContact(county, email)
    try:
        CountyContact = getattr(models, "CountyContact", None)
        if CountyContact is not None:
            row = (
                db.query(CountyContact)
                .filter(CountyContact.county.ilike(name))
                .order_by(CountyContact.id.desc())
                .first()
            )
            if row and getattr(row, "email", None):
                return row.email.strip()
    except Exception as e:
        logger.warning(f"[requests] CountyContact lookup failed: {e}")

    # 2) CSV fallback (root-level file)
    cmap_csv = _csv_county_map()
    email = cmap_csv.get(name.lower())
    if email:
        return email

    # 3) ENV map fallback
    cmap_env = _env_county_map()
    email = cmap_env.get(name.lower())
    if email:
        return email

    # 4) No mapping
    raise HTTPException(
        status_code=400,
        detail=(
            "Missing to_email and no county mapping found. "
            "Either supply to_email or configure CountyContact table / COUNTY_CONTACTS_CSV / COUNTY_EMAIL_MAP."
        ),
    )

# ---------- Schemas ----------
class IncidentRequestIn(BaseModel):
    incident_address: str = Field(..., min_length=3)
    incident_datetime: str = Field(..., description="e.g. '2025-08-01 10:00'")
    county: str = Field(..., min_length=2)
    # Optional override for testing
    to_email: Optional[EmailStr] = None

# ---------- Routes ----------
@requests_router.post("/incident_request")
def create_incident_request(
    data: IncidentRequestIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Resolve recipient email (override > DB > CSV > ENV)
    to_email_resolved = _lookup_to_email(db, data.county, str(data.to_email) if data.to_email else None)

    # Persist IncidentRequest
    colnames = {c.name for c in models.IncidentRequest.__table__.columns}
    req_kwargs = {
        "incident_address": data.incident_address.strip(),
        "incident_datetime": data.incident_datetime.strip(),
        "county": data.county.strip(),
        "to_email": to_email_resolved,  # if your table has this
    }


    # explicit reply target
    if "requester_email" in colnames and getattr(current_user, "email", None):
        req_kwargs["requester_email"] = current_user.email

    if "to_email" in colnames:
        req_kwargs["to_email"] = to_email_resolved
    if "created_by" in colnames and getattr(current_user, "username", None):
        req_kwargs["created_by"] = current_user.username
    if "user_token" in colnames and hasattr(current_user, "token"):
        req_kwargs["user_token"] = current_user.token

    try:
        req = models.IncidentRequest(**{k: v for k, v in req_kwargs.items() if k in colnames})
        db.add(req)
        db.commit()
        db.refresh(req)
    except Exception as e:
        logger.warning(f"[requests] persist failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to persist incident request")

    # Compose and send outbound email WITH machine-readable headers
    subject = f"Fire Incident Report Request: {data.incident_datetime}"
    content = (
        "Please provide the incident report for the following details:\n"
        f"Address: {data.incident_address}\n"
        f"Date/Time: {data.incident_datetime}\n"
        f"County: {data.county}\n"
    )

    try:
        send_request_email(
            to_email=to_email_resolved,
            subject=subject,
            content=content,
            incident_address=data.incident_address,
            incident_datetime=data.incident_datetime,
            county=data.county,
        )
    except Exception as e:
        logger.warning(f"[requests] send failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")

    return {"id": req.id, "status": "sent", "to_email": to_email_resolved, "subject": subject}
