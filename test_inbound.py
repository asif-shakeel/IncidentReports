# test_inbound.py
import json
import pytest
from fastapi.testclient import TestClient

# Import your app and models from the canvas code
from main import (
    app,
    SessionLocal,
    Base,
    engine,
    User,
    IncidentRequest,
    InboundEmail,
)

client = TestClient(app)

# ---------- Test utilities ----------

def _clean_db():
    """Safely clear tables between tests without dropping schema."""
    db = SessionLocal()
    try:
        db.query(InboundEmail).delete()
        db.query(IncidentRequest).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()

def _insert_incident(address: str, dt: str, county: str, county_email: str = "test@example.com"):
    """Insert a test IncidentRequest row and return it."""
    db = SessionLocal()
    try:
        ir = IncidentRequest(
            user_token="testtoken",
            incident_address=address,
            incident_datetime=dt,
            county=county,
            county_email=county_email,
        )
        db.add(ir)
        db.commit()
        db.refresh(ir)
        return ir
    finally:
        db.close()

# ---------- Session-scoped setup/teardown ----------

@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """
    Ensure tables exist. (Uses your current engine from main.py)
    NOTE: For safety, this does not drop tables — it only creates if missing.
    """
    Base.metadata.create_all(bind=engine)
    yield

@pytest.fixture(autouse=True)
def _fresh_db_each_test(monkeypatch):
    """
    Clean rows before each test and disable outbound integrations:
    - Disable SendGrid by unsetting SENDGRID_API_KEY inside app module.
    - Disable OpenAI by forcing openai_client to None unless a test sets it.
    """
    _clean_db()
    # Disable SendGrid in tests to avoid real emails
    import main as appmod
    appmod.SENDGRID_API_KEY = None
    # Disable LLM fallback by default (tests that need it will override)
    appmod.openai_client = None
    yield
    _clean_db()

# ---------- Tests ----------

def test_inbound_happy_path():
    """
    Email perfectly matches an existing IncidentRequest.
    """
    inc = _insert_incident("334 Wilshire Blvd", "2025-06-20 10:00", "Los Angeles")

    payload = {
        "from": "firedept@example.com",
        "subject": "Incident Report Response",
        "text": "Address: 334 Wilshire Blvd\nDate/Time: 2025-06-20 10:00\nCounty: Los Angeles",
    }
    resp = client.post("/inbound", data=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "received"
    assert data["parsed"]["address"] == "334 Wilshire Blvd"
    assert data["parsed"]["datetime"] == "2025-06-20 10:00"
    assert data["parsed"]["county"] == "Los Angeles"
    assert data["match"]["incident_request_id"] == inc.id

def test_inbound_whitespace_and_punctuation_variants():
    """
    Extra spaces, punctuation, and different county case should still match,
    thanks to normalize()+coarse county filter in the app.
    """
    inc = _insert_incident("334 Wilshire Blvd", "2025-06-20 10:00", "Los Angeles")

    payload = {
        "from": "firedept@example.com",
        "subject": "Extra whitespace",
        "text": "Address:   334  Wilshire Blvd. \nDate/Time:  2025-06-20 10:00 \nCounty:  los angeles  ",
    }
    resp = client.post("/inbound", data=payload)
    assert resp.status_code == 200
    data = resp.json()

    # Parsed values should be trimmed lines (parser keeps punctuation if present)
    assert data["parsed"]["address"] in ["334  Wilshire Blvd.", "334 Wilshire Blvd.", "334 Wilshire Blvd"]
    assert data["parsed"]["datetime"] == "2025-06-20 10:00"
    assert data["parsed"]["county"].lower() == "los angeles"

    # Matching should still succeed due to normalization
    assert data["match"]["incident_request_id"] == inc.id

def test_inbound_missing_address():
    """
    Missing Address line -> parsed address None and no match.
    """
    _insert_incident("334 Wilshire Blvd", "2025-06-20 10:00", "Los Angeles")
    payload = {
        "from": "firedept@example.com",
        "subject": "Missing Address",
        "text": "Date/Time: 2025-06-20 10:00\nCounty: Los Angeles",
    }
    resp = client.post("/inbound", data=payload)
    data = resp.json()
    assert resp.status_code == 200
    assert data["parsed"]["address"] is None
    assert data["match"] is None

def test_inbound_missing_datetime():
    """
    Missing Date/Time -> parsed datetime None and no match.
    """
    _insert_incident("334 Wilshire Blvd", "2025-06-20 10:00", "Los Angeles")
    payload = {
        "from": "firedept@example.com",
        "subject": "Missing Date",
        "text": "Address: 334 Wilshire Blvd\nCounty: Los Angeles",
    }
    resp = client.post("/inbound", data=payload)
    data = resp.json()
    assert resp.status_code == 200
    assert data["parsed"]["datetime"] is None
    assert data["match"] is None

def test_inbound_missing_county():
    """
    Missing County -> parsed county None and no match (coarse county filter needs county).
    """
    _insert_incident("334 Wilshire Blvd", "2025-06-20 10:00", "Los Angeles")
    payload = {
        "from": "firedept@example.com",
        "subject": "Missing County",
        "text": "Address: 334 Wilshire Blvd\nDate/Time: 2025-06-20 10:00",
    }
    resp = client.post("/inbound", data=payload)
    data = resp.json()
    assert resp.status_code == 200
    assert data["parsed"]["county"] is None
    assert data["match"] is None

def test_inbound_no_match():
    """
    Valid parsed fields but no matching IncidentRequest in DB -> match None.
    """
    _insert_incident("111 First St", "2025-06-15 08:00", "Orange County")

    payload = {
        "from": "someone@example.com",
        "subject": "No match",
        "text": "Address: 999 Unknown Rd\nDate/Time: 2025-07-01 12:00\nCounty: Unknown County",
    }
    resp = client.post("/inbound", data=payload)
    data = resp.json()
    assert resp.status_code == 200
    assert data["match"] is None

def test_inbound_invalid_payload_missing_text():
    """
    Missing 'text' field (email body) should return 400.
    """
    payload = {"from": "firedept@example.com", "subject": "Invalid"}
    resp = client.post("/inbound", data=payload)
    assert resp.status_code == 400

def test_inbound_llm_fallback(monkeypatch):
    """
    Body has no labeled lines; rule-based parsing fails.
    LLM fallback is monkeypatched to return JSON, enabling a match.
    """
    # Prepare a matching incident
    inc = _insert_incident("334 Wilshire Blvd", "2025-06-20 10:00", "Los Angeles")

    # Monkeypatch openai_client to a fake one that returns a JSON we expect.
    class _FakeChoice:
        def __init__(self, content):
            self.message = type("obj", (), {"content": content})

    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]

    class _FakeChat:
        def __init__(self, outer):
            self.outer = outer
        def completions_create(self, **kwargs):
            # not used, but keep for compatibility if called
            return _FakeResp(self.outer.content)
        def completions(self):
            return self
        def create(self, **kwargs):
            return _FakeResp(self.outer.content)

    class _FakeOpenAI:
        def __init__(self, content):
            self.content = content
            # mimic the .chat.completions.create(...) path
            self.chat = type("obj", (), {"completions": _FakeChat(self)})

    # JSON the LLM would return
    llm_json = json.dumps({
        "address": "334 Wilshire Blvd",
        "datetime": "2025-06-20 10:00",
        "county": "Los Angeles"
    })

    import main as appmod
    appmod.openai_client = _FakeOpenAI(llm_json)

    # Body without labels; only LLM can parse it.
    payload = {
        "from": "firedept@example.com",
        "subject": "Free-form",
        "text": "Please send the report for the incident at 334 Wilshire Blvd on 2025-06-20 10:00 in Los Angeles.",
    }
    resp = client.post("/inbound", data=payload)
    data = resp.json()

    assert resp.status_code == 200
    assert data["parsed"]["address"] == "334 Wilshire Blvd"
    assert data["parsed"]["datetime"] == "2025-06-20 10:00"
    assert data["parsed"]["county"] == "Los Angeles"
    assert data["match"]["incident_request_id"] == inc.id
