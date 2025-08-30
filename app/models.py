# ================================
# FILE: app/models.py
# ================================
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func
from app.database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, nullable=False)

class IncidentRequest(Base):
    __tablename__ = 'incident_requests'
    id = Column(Integer, primary_key=True, index=True)

    # who created the request (so we can forward replies to the requester)
    created_by = Column(String, nullable=True)           # username from auth
    requester_email = Column(String, nullable=True)      # email of the requester

    # request details used for matching replies
    incident_address = Column(String)
    incident_datetime = Column(String)
    county = Column(String)

    # where the original request was sent (county inbox)
    county_email = Column(String)

class InboundEmail(Base):
    __tablename__ = 'inbound_emails'
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    subject = Column(String)
    body = Column(String)
    parsed_address = Column(String, nullable=True)
    parsed_datetime = Column(String, nullable=True)
    parsed_county = Column(String, nullable=True)

    # attachment tracking
    has_attachments  = Column(Boolean, nullable=False, default=False)
    attachment_count = Column(Integer, nullable=False, default=0)

    # forward tracking
    forwarded_to           = Column(String, nullable=True)
    forward_sg_message_id  = Column(String, nullable=True)
    forward_status         = Column(String, nullable=True)  # accepted/delivered/bounced/etc
    forwarded_at           = Column(DateTime(timezone=True), nullable=True)

    # timestamps
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
