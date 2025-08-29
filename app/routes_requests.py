# ================================
# FILE: app/routes_requests.py
# ================================
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer
from app.database import get_db
from app.models import IncidentRequest, User
from app.schemas import IncidentRequestCreate
from app.config import get_county_email_map
from app.email_io import send_request_email
from auth import decode_access_token

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

@router.post("/incident_request")
def create_incident_request(
    req: IncidentRequestCreate,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    username = decode_access_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    county_email = get_county_email_map().get(req.county)
    if not county_email:
        raise HTTPException(status_code=400, detail="No email found for this county")

    new_request = IncidentRequest(
        created_by=user.username,
        requester_email=user.email,
        incident_address=req.incident_address,
        incident_datetime=req.incident_datetime,
        county=req.county,
        county_email=county_email,
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    subject = f"Fire Incident Report Request: {req.incident_datetime}"
    content = f"Please provide the incident report for the following details:\nAddress: {req.incident_address}\nDate/Time: {req.incident_datetime}\nCounty: {req.county}"

    try:
        send_request_email(county_email, subject, content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"msg": "Incident request created and email sent", "request_id": new_request.id}