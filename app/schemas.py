# ================================
# FILE: app/schemas.py
# ================================
from pydantic import BaseModel

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str

class IncidentRequestCreate(BaseModel):
    incident_address: str
    incident_datetime: str
    county: str
