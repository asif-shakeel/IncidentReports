# =============================
# FILE: app/routes_requests.py
# Purpose: Create incident requests (AUTH REQUIRED), auto-resolve county inbox,
#          and store who requested it (created_by, requester_email).
# Lookup order for recipient county email: override > DB CountyContact > CSV > ENV
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

logger = logging.getLogger("uvicorn.error").getChild("requests")
requests_router = APIRouter(tags=["requests"])  # import this in main.py

# ---------- Auth dependency ----------
try:
    from app.routes_auth import get_current_user  # must return models.User with .username/.email
except Exception:  # fallback (expects PyJWT installed)
    import jwt
    try:
        from app.config import SECRET_KEY, ALGORITHM
    except Exception:
        from auth import SECRET_KEY, ALGORITHM  # root level fallback

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
        setattr(user, "token", token)
        return user

# ---------- Config helpers ----------
def _env_county_map() -> dict[str, str]:
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
                out: dict[str, str] = {}
                for row in reader:
                    county = row.get("county") or row.get("County") or row.get("County Name") or ""
                    email = row.get("email") or row.get("Email") or row.get("Contact Email") or ""
                    if county and email:
                        out[county.strip().lower()] = email.strip()
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

    m_csv = _csv_county_map()
    if name.lower() in m_csv:
        return m_csv[name.lower()]

    m_env = _env_county_map()
    if name.lower() in m_env:
        return m_env[name.lower()]

    raise HTTPException(status_code=400, detail="No county contact found; provide to_email or configure mapping.")

# ---------- Schemas ----------
class IncidentRequestIn(BaseModel):
    incident_address: str = Field(..., min_length=3)
    incident_datetime: str = Field(..., description="e.g. '2025-08-01 10:00'")
    county: str = Field(..., min_length=2)
    to_email: Optional[EmailStr] = None

# ---------- Route ----------
@requests_router.post("/incident_request")
def create_incident_request(
    data: IncidentRequestIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    to_email_resolved = _lookup_to_email(db, data.county, str(data.to_email) if data.to_email else None)

    colnames = {c.name for c in models.IncidentRequest.__table__.columns}
    req_kwargs = {
        "incident_address": data.incident_address.strip(),
        "incident_datetime": data.incident_datetime.strip(),
        "county": data.county.strip(),
    }
    if "county_email" in colnames:
        req_kwargs["county_email"] = to_email_resolved
    if "created_by" in colnames and getattr(current_user, "username", None):
        req_kwargs["created_by"] = current_user.username
    if "requester_email" in colnames and getattr(current_user, "email", None):
        req_kwargs["requester_email"] = current_user.email

    try:
        req = models.IncidentRequest(**{k: v for k, v in req_kwargs.items() if k in colnames})
        db.add(req)
        db.commit()
        db.refresh(req)
    except Exception as e:
        logger.warning(f"[requests] persist failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to persist incident request")

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

    return {"id": req.id, "status": "sent", "county_email": to_email_resolved, "subject": subject}

router = requests_router

# # =============================
# # FILE: app/routes_requests.py
# # Purpose: Create incident requests (AUTH REQUIRED), auto-resolve county inbox,
# #          and store who requested it (created_by, requester_email).
# # Lookup order for recipient county email: override > DB CountyContact > CSV > ENV
# # =============================
# from __future__ import annotations
# import logging
# import json
# import os
# import csv
# from functools import lru_cache
# from typing import Optional

# from fastapi import APIRouter, Depends, HTTPException
# from pydantic import BaseModel, Field, EmailStr
# from sqlalchemy.orm import Session

# from app.database import get_db
# from app import models
# from app.email_io import send_request_email

# logger = logging.getLogger("uvicorn.error").getChild("requests")
# requests_router = APIRouter(tags=["requests"])  # import this in main.py

# # ---------- Auth dependency ----------
# try:
#     from app.routes_auth import get_current_user  # must return models.User with .username/.email
# except Exception:  # fallback (expects PyJWT installed)
#     import jwt as pyjwt
#     try:
#         from app.config import SECRET_KEY, ALGORITHM
#     except Exception:
#         from auth import SECRET_KEY, ALGORITHM  # root level fallback

#     def get_current_user(authorization: str | None = None, db: Session = Depends(get_db)):
#         if not authorization or not authorization.lower().startswith("bearer "):
#             raise HTTPException(status_code=401, detail="Missing bearer token")
#         token = authorization.split(" ", 1)[1]
#         try:
#             payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         except Exception:
#             raise HTTPException(status_code=401, detail="Invalid token")
#         username = payload.get("sub") or payload.get("username")
#         if not username:
#             raise HTTPException(status_code=401, detail="Invalid token payload")
#         user = db.query(models.User).filter(models.User.username == username).first()
#         if not user:
#             raise HTTPException(status_code=401, detail="User not found")
#         # expose token if needed later
#         setattr(user, "token", token)
#         return user

# # ---------- Config helpers ----------

# def _env_county_map() -> dict[str, str]:
#     raw = os.getenv("COUNTY_EMAIL_MAP", "")
#     if not raw:
#         return {}
#     try:
#         data = json.loads(raw)
#         return {str(k).strip().lower(): str(v).strip() for k, v in data.items()}
#     except Exception:
#         logger.warning("[requests] bad COUNTY_EMAIL_MAP JSON; ignoring")
#         return {}


# @lru_cache(maxsize=1)
# def _csv_county_map() -> dict[str, str]:
#     paths = []
#     if os.getenv("COUNTY_CONTACTS_CSV"):
#         paths.append(os.getenv("COUNTY_CONTACTS_CSV"))
#     # repo root fallbacks
#     paths += [
#         os.path.join(os.getcwd(), "ca_all_counties_fire_records_contacts.csv"),
#         os.path.join(os.getcwd(), "ca_all_counties_fire_records_contacts_template.csv"),
#     ]
#     for p in paths:
#         try:
#             if not p or not os.path.exists(p):
#                 continue
#             with open(p, newline="", encoding="utf-8") as f:
#                 reader = csv.DictReader(f)
#                 def pick(d: dict, keys: list[str]) -> str:
#                     for k in keys:
#                         if k in d and d[k]:
#                             return str(d[k])
#                     return ""
#                 out: dict[str, str] = {}
#                 for row in reader:
#                     county = pick(row, ["county", "County", "County Name"]).strip()
#                     email = pick(row, ["email", "Email", "Contact Email"]).strip()
#                     if county and email:
#                         out[county.lower()] = email
#                 if out:
#                     logger.info(f"[requests] loaded county CSV map from {p} ({len(out)} entries)")
#                     return out
#         except Exception as e:
#             logger.warning(f"[requests] CSV load failed for {p}: {e}")
#     return {}


# def _lookup_to_email(db: Session, county: str, override: Optional[str] = None) -> str:
#     if override:
#         return override
#     name = (county or "").strip()
#     if not name:
#         raise HTTPException(status_code=400, detail="county is required")

#     # 1) DB table if present: models.CountyContact(county, email)
#     try:
#         CountyContact = getattr(models, "CountyContact", None)
#         if CountyContact is not None:
#             row = (
#                 db.query(CountyContact)
#                 .filter(CountyContact.county.ilike(name))
#                 .order_by(CountyContact.id.desc())
#                 .first()
#             )
#             if row and getattr(row, "email", None):
#                 return row.email.strip()
#     except Exception as e:
#         logger.warning(f"[requests] CountyContact lookup failed: {e}")

#     # 2) CSV fallback
#     m_csv = _csv_county_map()
#     if name.lower() in m_csv:
#         return m_csv[name.lower()]

#     # 3) ENV JSON fallback
#     m_env = _env_county_map()
#     if name.lower() in m_env:
#         return m_env[name.lower()]

#     raise HTTPException(status_code=400, detail="No county contact found; provide to_email or configure mapping.")

# # ---------- Schemas ----------
# class IncidentRequestIn(BaseModel):
#     incident_address: str = Field(..., min_length=3)
#     incident_datetime: str = Field(..., description="e.g. '2025-08-01 10:00'")
#     county: str = Field(..., min_length=2)
#     to_email: Optional[EmailStr] = None  # optional override for testing

# # ---------- Route ----------
# @requests_router.post("/incident_request")
# def create_incident_request(
#     data: IncidentRequestIn,
#     db: Session = Depends(get_db),
#     current_user: models.User = Depends(get_current_user),
# ):
#     # Resolve county recipient (override > DB > CSV > ENV)
#     to_email_resolved = _lookup_to_email(db, data.county, str(data.to_email) if data.to_email else None)

#     # Persist IncidentRequest, including who created it + where to reply
#     colnames = {c.name for c in models.IncidentRequest.__table__.columns}
#     logger.info("[requests] current_user username=%r email=%r",
#             getattr(current_user, "username", None),
#             getattr(current_user, "email", None))

#     req_kwargs = {
#         "incident_address": data.incident_address.strip(),
#         "incident_datetime": data.incident_datetime.strip(),
#         "county": data.county.strip(),
#     }
#     if "to_email" in colnames:
#         req_kwargs["to_email"] = to_email_resolved
#     if "created_by" in colnames and getattr(current_user, "username", None):
#         req_kwargs["created_by"] = current_user.username
#     if "requester_email" in colnames and getattr(current_user, "email", None):
#         req_kwargs["requester_email"] = current_user.email

#     try:
#         req = models.IncidentRequest(**{k: v for k, v in req_kwargs.items() if k in colnames})
#         db.add(req)
#         db.commit()
#         db.refresh(req)
#     except Exception as e:
#         logger.warning(f"[requests] persist failed: {e}")
#         raise HTTPException(status_code=500, detail="Failed to persist incident request")

#     # Compose email body + headers
#     subject = f"Fire Incident Report Request: {data.incident_datetime}"
#     content = (
#         "Please provide the incident report for the following details:\n"
#         f"Address: {data.incident_address}\n"
#         f"Date/Time: {data.incident_datetime}\n"
#         f"County: {data.county}\n"
#     )

#     try:
#         send_request_email(
#             to_email=to_email_resolved,
#             subject=subject,
#             content=content,
#             incident_address=data.incident_address,
#             incident_datetime=data.incident_datetime,
#             county=data.county,
#         )
#     except Exception as e:
#         logger.warning(f"[requests] send failed: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")

#     return {"id": req.id, "status": "sent", "to_email": to_email_resolved, "subject": subject}

# # Optional alias if you previously imported `router`
# router = requests_router
