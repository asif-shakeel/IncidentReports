# ================================
# FILE: app/schemas.py
# ================================
from pydantic import BaseModel, EmailStr

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: EmailStr

class IncidentRequestCreate(BaseModel):
    incident_address: str
    incident_datetime: str
    county: str
