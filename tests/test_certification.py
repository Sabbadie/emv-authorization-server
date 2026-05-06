"""
Tests pour le moteur de certification GIE CB (v1.14.0).
"""
import pytest
from emv.certification import CertificationRunner, CertificationScenario, CB_CERT_SCENARIOS

def test_runner_validation_success():
    """Vérifie que le runner valide correctement une réponse attendue."""
    client = type('obj', (object,), {'send': lambda self, req: {"approved": True, "rc": "00"}})()
    runner = CertificationRunner(client)
    
    scenario = CertificationScenario("TEST", "Desc", [
        {"request": {}, "expected": {"approved": True, "rc": "00"}}
    ])
    
    report = runner.run_scenario(scenario)
    assert report["success"] is True
    assert report["steps"][0]["passed"] is True

def test_runner_validation_failure():
    """Vérifie que le runner détecte un échec de validation."""
    client = type('obj', (object,), {'send': lambda self, req: {"approved": False, "rc": "51"}})()
    runner = CertificationRunner(client)
    
    scenario = CertificationScenario("TEST", "Desc", [
        {"request": {}, "expected": {"approved": True, "rc": "00"}}
    ])
    
    report = runner.run_scenario(scenario)
    assert report["success"] is False
    assert report["steps"][0]["passed"] is False

def test_cl_cumul_scenario_logic(client):
    """Vérifie le scénario de cumul sans contact via l'API de certification."""
    # On réinitialise la carte de test
    client.post("/api/v1/cards/4111111111111111/unblock")
    
    resp = client.post("/api/v1/certification/run/CL_CUMUL_LIMIT")
    data = resp.get_json()
    
    assert resp.status_code == 200
    assert data["scenario"] == "CL_CUMUL_LIMIT"
    assert data["success"] is True # Le scénario doit réussir car le serveur se comporte comme attendu
    assert len(data["steps"]) == 4
