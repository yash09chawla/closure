"""Research endpoints must refuse personal data before doing any work."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)   # no `with` → lifespan (Chrome, source warm-up) is not started


def test_passing_endpoint_rejects_personal_data():
    r = client.post("/api/research/passing-criteria",
                    json={"institute": "Example University", "degree": "B.E. reg 123456789012"})
    assert r.status_code == 422
    assert "blocked" in r.json()["detail"]


def test_accreditation_endpoint_rejects_email():
    r = client.post("/api/research/accreditation", json={"university": "Example University person@example.com"})
    assert r.status_code == 422


def test_required_fields():
    assert client.post("/api/research/accreditation", json={}).status_code == 400
    assert client.post("/api/research/passing-criteria", json={"institute": "X"}).status_code == 400


def test_status_reports_openai_ocr():
    s = client.get("/api/status").json()
    assert s["documents_leave_machine"] is True
    assert s["ocr"]["engine"] == "OpenAI vision"
