import re

import app as app_module


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
