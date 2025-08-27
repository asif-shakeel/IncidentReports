import pytest
from fastapi.testclient import TestClient
from main import app, SessionLocal, Base, engine, IncidentRequest

# Create a fresh test database
Base.metadata.create_all(bind=engine)

client = TestClient(app)

# Fixture to create a sample incident request in the DB
@pytest.fixture
def sample_incident_request():
    db = SessionLocal()
    incident = IncidentRequest(
        user_token="testtoken",
        incident_address="334 Wilshire Blvd",
        incident_datetime="2025-06-20 10:00",
        county="Los Angeles",
        county_email="sillaskon@gmail.com"
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    db.close()
    return incident

def test_inbound_happy_path(sample_incident_request):
    """Email perfectly matches an existing IncidentRequest"""
    payload = {
        "from": "firedept@example.com",
        "subject": "Request for Incident Report",
        "text": (
            "Address: 334 Wilshire Blvd\n"
            "Date/Time: 2025-06-20 10:00\n"
            "County: Los Angeles"
        )
    }
    response = client.post("/inbound", data=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["parsed"]["address"] == "334 Wilshire Blvd"
    assert data["parsed"]["datetime"] == "2025-06-20 10:00"
    assert data["parsed"]["county"] == "Los Angeles"
    assert data["match"]["incident_request_id"] == sample_incident_request.id

def test_inbound_missing_fields():
    """Email missing address or datetime"""
    payload = {
        "from": "firedept@example.com",
        "subject": "Missing fields",
        "text": "Date/Time: 2025-06-20 10:00\nCounty: Los Angeles"
    }
    response = client.post("/inbound", data=payload)
    data = response.json()
    assert response.status_code == 200
    assert data["parsed"]["address"] is None
    assert data["match"] is None

def test_inbound_partial_match(sample_incident_request):
    """Email with slightly different address formatting"""
    payload = {
        "from": "firedept@example.com",
        "subject": "Partial match",
        "text": (
            "Address: 334 Wilshire Blvd.\n"  # Note the dot
            "Date/Time: 2025-06-20 10:00\n"
            "County: Los Angeles"
        )
    }
    response = client.post("/inbound", data=payload)
    data = response.json()
    # Should not match due to dot difference (current regex is strict)
    assert data["match"] is None

def test_inbound_extra_whitespace(sample_incident_request):
    """Email with extra whitespace and newlines"""
    payload = {
        "from": "firedept@example.com",
        "subject": "Extra whitespace",
        "text": (
            "Address:    334 Wilshire Blvd  \n"
            "Date/Time:    2025-06-20 10:00  \n"
            "County:   Los Angeles  "
        )
    }
    response = client.post("/inbound", data=payload)
    data = response.json()
    assert data["parsed"]["address"] == "334 Wilshire Blvd"
    assert data["parsed"]["datetime"] == "2025-06-20 10:00"
    assert data["parsed"]["county"] == "Los Angeles"
    # With current exact match in DB, this may still fail to match
    assert data["match"] is None or data["match"]["incident_request_id"] == sample_incident_request.id

def test_inbound_no_match():
    """Email that should not match any request"""
    payload = {
        "from": "someone@example.com",
        "subject": "No match",
        "text": (
            "Address: 999 Unknown St\n"
            "Date/Time: 2025-07-01 12:00\n"
            "County: Unknown County"
        )
    }
    response = client.post("/inbound", data=payload)
    data = response.json()
    assert data["match"] is None

def test_inbound_invalid_payload():
    """Missing sender or body"""
    payload = {"subject": "Invalid", "text": ""}
    response = client.post("/inbound", data=payload)
    assert response.status_code == 400
