import re
import sqlite3

import pytest

import app as app_module
from database import db


def setup_module():
    app_module.init_app()


def test_analyze_route_persists_diagnosis(monkeypatch):
    diagnosis = {
        "root_cause": "Trunk is not established",
        "osi_layer": "Layer 2",
        "confidence": "High",
        "evidence": ["Port is not-trunking"],
        "next_command": "show interfaces trunk",
        "fix_steps": ["Configure switchport mode trunk"],
    }

    monkeypatch.setattr(app_module.db, "insert_diagnosis", lambda record: 123)
    monkeypatch.setattr(app_module, "diagnose", lambda *args: diagnosis)
    monkeypatch.setattr(app_module, "run_all_checks", lambda *args: [
        {"rule": "trunk_mode", "status": "fail", "detail": "not-trunking"}
    ])

    client = app_module.app.test_client()
    page = client.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/analyze",
        data={"csrf_token": token,
            "category": "VLAN",
            "symptom": "VLAN 20 is unreachable",
            "topology": "SW1 to SW2",
            "show_output": "Gi0/1 auto not-trunking",
        },
    )

    assert response.status_code == 302
    assert response.location.endswith("/diagnosis/123")


def test_analyze_route_rejects_missing_symptom():
    client = app_module.app.test_client()

    page = client.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/analyze",
        data={"csrf_token": token, "category": "VLAN", "show_output": "show vlan brief"},
    )

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_health_api():
    response = app_module.app.test_client().get("/api/health")

    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_seeded_dataset_has_all_cases_and_categories():
    cases = app_module.db.get_all_cases()
    assert len(cases) == 32
    assert {case["category"] for case in cases} == {
        "VLAN", "Routing", "DHCP", "DNS",
        "Gateway", "ACL", "NAT", "Wireless",
    }


def test_analyze_rejects_oversized_form_field():
    client = app_module.app.test_client()
    page = client.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/analyze",
        data={"csrf_token": token, "symptom": "x" * 100_001},
    )
    assert response.status_code == 413


def test_diagnosis_page_hides_submitted_inputs_by_default(monkeypatch):
    monkeypatch.setattr(app_module.config, "EXPOSE_DIAGNOSIS_INPUTS", False)
    monkeypatch.setattr(app_module.db, "get_diagnosis", lambda diag_id: {
        "id": diag_id,
        "symptom": "private symptom",
        "topology": "private topology",
        "show_output": "private command output",
        "evidence": [],
        "fix_steps": [],
        "rule_results": [],
        "confidence": "Low",
        "ai_conflict": False,
    })
    monkeypatch.setattr(app_module.db, "get_review_for_diagnosis", lambda diag_id: None)

    response = app_module.app.test_client().get("/diagnosis/1")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "private topology" not in body
    assert "private command output" not in body


def test_seeded_diagnosis_is_idempotent_in_sqlite():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(db.SCHEMA, encoding="utf-8") as schema:
        conn.executescript(schema.read())

    diagnosis = {
        "case_ref": "TEST",
        "category": "VLAN",
        "symptom": "Seeded test diagnosis",
        "topology": "SW1 -> SW2",
        "show_output": "not-trunking",
        "root_cause": "Trunk is down",
        "confidence": "High",
        "evidence": [],
        "fix_steps": [],
        "rule_results": [],
    }
    first_id = db.insert_seeded_diagnosis(diagnosis, "test-seed", conn)
    db.insert_review({"diagnosis_id": first_id, "decision": "accept"}, conn)
    conn.commit()

    assert conn.execute(
        "SELECT diagnosis_id FROM responsible_ai_log"
    ).fetchone()["diagnosis_id"] == first_id

    second_id = db.insert_seeded_diagnosis(diagnosis, "test-seed", conn)

    assert first_id is not None
    assert second_id is None
    assert conn.execute("SELECT COUNT(*) FROM diagnoses").fetchone()[0] == 1
    conn.close()


def _sqlite_schema_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(db.SCHEMA, encoding="utf-8") as schema:
        conn.executescript(schema.read())
    return conn


def _manual_diagnosis():
    return {
        "category": "VLAN",
        "symptom": "VLAN 20 is unreachable",
        "topology": "SW1 -> SW2",
        "show_output": "Gi0/1 is not-trunking",
        "root_cause": "The trunk is not established",
        "confidence": "High",
        "evidence": ["The interface is not-trunking"],
        "fix_steps": ["Configure trunk mode"],
        "rule_results": [],
    }


def test_reviewed_manual_diagnosis_is_in_responsible_ai_log_for_all_decisions():
    conn = _sqlite_schema_connection()
    for decision in ("accept", "edit", "reject"):
        diagnosis_id = db.insert_diagnosis(_manual_diagnosis(), conn)
        db.insert_review({
            "diagnosis_id": diagnosis_id,
            "decision": decision,
            "human_root_cause": "Reviewed root cause",
            "reason": "Human review completed",
        }, conn)
    conn.commit()

    rows = conn.execute(
        "SELECT diagnosis_id, category, ai_diagnosis, ai_confidence, human_decision "
        "FROM responsible_ai_log ORDER BY diagnosis_id"
    ).fetchall()

    assert len(rows) == 3
    assert [row["human_decision"] for row in rows] == ["accept", "edit", "reject"]
    assert all(row["category"] == "VLAN" for row in rows)
    assert all(row["ai_diagnosis"] == "The trunk is not established" for row in rows)
    assert all(row["ai_confidence"] == "High" for row in rows)
    conn.close()


def test_unreviewed_manual_diagnosis_is_in_responsible_ai_log():
    conn = _sqlite_schema_connection()
    diagnosis_id = db.insert_diagnosis(_manual_diagnosis(), conn)
    conn.commit()

    row = conn.execute(
        "SELECT diagnosis_id, category, ai_diagnosis, ai_confidence, human_decision "
        "FROM responsible_ai_log WHERE diagnosis_id=?",
        (diagnosis_id,),
    ).fetchone()

    assert dict(row) == {
        "diagnosis_id": diagnosis_id,
        "category": "VLAN",
        "ai_diagnosis": "The trunk is not established",
        "ai_confidence": "High",
        "human_decision": None,
    }
    conn.close()


def test_manual_review_retry_cannot_create_duplicate_audit_entry():
    conn = _sqlite_schema_connection()
    diagnosis_id = db.insert_diagnosis(_manual_diagnosis(), conn)
    db.insert_review({"diagnosis_id": diagnosis_id, "decision": "accept"}, conn)
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.insert_review({"diagnosis_id": diagnosis_id, "decision": "accept"}, conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM responsible_ai_log WHERE diagnosis_id=?",
        (diagnosis_id,),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE diagnosis_id=?",
        (diagnosis_id,),
    ).fetchone()[0] == 1
    conn.close()


def test_diagnosis_and_review_rollback_together_in_sqlite():
    conn = _sqlite_schema_connection()
    try:
        diagnosis_id = db.insert_diagnosis(_manual_diagnosis(), conn)
        db.insert_review({"diagnosis_id": diagnosis_id, "decision": "reject"}, conn)
        raise RuntimeError("simulate transaction failure")
    except RuntimeError:
        conn.rollback()

    assert conn.execute("SELECT COUNT(*) FROM diagnoses").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM responsible_ai_log").fetchone()[0] == 0
    conn.close()


def test_diagnose_api_validates_and_returns_structured_result(monkeypatch):
    diagnosis = {
        "root_cause": "Trunk failure",
        "osi_layer": "Layer 2",
        "confidence": "High",
        "evidence": ["not-trunking"],
        "next_command": "show interfaces trunk",
        "fix_steps": ["Set trunk mode"],
    }
    monkeypatch.setattr(app_module, "diagnose", lambda *args: diagnosis)
    monkeypatch.setattr(app_module.db, "insert_diagnosis", lambda record: 44)
    monkeypatch.setattr(app_module, "run_all_checks", lambda *args: [])

    response = app_module.app.test_client().post(
        "/api/diagnose",
        json={"category": "VLAN", "symptom": "No connectivity",
              "show_output": "not-trunking"},
    )

    assert response.status_code == 201
    assert response.json["id"] == 44
    assert response.json["diagnosis"]["root_cause"] == "Trunk failure"
    assert "show_output" not in response.json["diagnosis"]


def test_diagnose_api_rejects_invalid_json():
    response = app_module.app.test_client().post(
        "/api/diagnose", data="not-json", content_type="text/plain"
    )

    assert response.status_code == 400
    assert "JSON object" in response.json["error"]


def test_review_api_validates_decision(monkeypatch):
    monkeypatch.setattr(app_module.db, "get_diagnosis", lambda diag_id: {"id": diag_id})
    monkeypatch.setattr(app_module.db, "get_review_for_diagnosis", lambda diag_id: None)

    response = app_module.app.test_client().post(
        "/api/diagnoses/44/reviews", json={"decision": "maybe"}
    )

    assert response.status_code == 400
    assert "decision" in response.json["error"]


def test_public_cases_api_does_not_expose_expected_fault(monkeypatch):
    monkeypatch.setattr(app_module.db, "get_all_cases", lambda: [{
        "case_id": "001", "category": "VLAN", "symptom": "No connectivity",
        "topology": "PC -> SW", "show_output": "show vlan brief",
        "expected_fault": "Hidden ground truth", "osi_layer": "Layer 2",
        "concept": "VLAN", "severity": "High",
    }])
    response = app_module.app.test_client().get("/api/cases")
    assert response.status_code == 200
    assert "expected_fault" not in response.json["cases"][0]
    assert "Hidden ground truth" not in response.get_data(as_text=True)


def test_analyze_route_rejects_missing_csrf_token():
    response = app_module.app.test_client().post(
        "/analyze", data={"category": "VLAN", "symptom": "No connectivity"}
    )
    assert response.status_code == 400
