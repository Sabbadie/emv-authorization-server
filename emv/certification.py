"""
Moteur de Certification GIE CB — Automatisation des scénarios de test.
Permet d'exécuter des séquences de transactions pour valider la conformité.
"""
import logging
from datetime import datetime, UTC
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class CertificationScenario:
    def __init__(self, name: str, description: str, steps: List[Dict[str, Any]]):
        self.name = name
        self.description = description
        self.steps = steps

class CertificationRunner:
    """Exécuteur de scénarios de certification."""
    
    def __init__(self, client):
        self.client = client # TerminalClient ou fonction d'appel directe

    def run_scenario(self, scenario: CertificationScenario) -> Dict[str, Any]:
        results = []
        success = True
        logger.info("Démarrage du scénario : %s", scenario.name)
        
        for i, step in enumerate(scenario.steps):
            logger.info("  Étape %d/%d : %s", i+1, len(scenario.steps), step.get("name", "Sans nom"))
            
            # Préparation de la requête
            request = step["request"]
            expected = step["expected"]
            
            # Exécution
            response = self.client.send(request)
            
            # Validation
            step_passed = self._validate_step(response, expected)
            results.append({
                "step": i + 1,
                "name": step.get("name"),
                "passed": step_passed,
                "response": response,
                "expected": expected
            })
            
            if not step_passed:
                success = False
                if step.get("abort_on_failure", True):
                    break
        
        return {
            "scenario": scenario.name,
            "success": success,
            "steps": results,
            "finished_at": datetime.now(UTC).isoformat()
        }

    def _validate_step(self, response: dict, expected: dict) -> bool:
        """Valide la réponse par rapport aux attentes du test."""
        for key, expected_value in expected.items():
            actual_value = response.get(key)
            if actual_value != expected_value:
                logger.warning("    ❌ Échec sur %s : attendu=%s, obtenu=%s", 
                               key, expected_value, actual_value)
                return False
        return True

# ── Bibliothèque de scénarios standard ────────────────────────────────────────

CB_CERT_SCENARIOS = [
    CertificationScenario(
        "CL_CUMUL_LIMIT",
        "Dépassement du cumul sans contact (RC=A5)",
        steps=[
            {
                "name": "Transaction CL 1 (50€)",
                "request": {"pan": "4111111111111111", "amount": 5000, "is_contactless": True, "skip_crypto": True},
                "expected": {"approved": True, "cb_response_code": "00"}
            },
            {
                "name": "Transaction CL 2 (50€)",
                "request": {"pan": "4111111111111111", "amount": 5000, "is_contactless": True, "skip_crypto": True},
                "expected": {"approved": True, "cb_response_code": "00"}
            },
            {
                "name": "Transaction CL 3 (50€)",
                "request": {"pan": "4111111111111111", "amount": 5000, "is_contactless": True, "skip_crypto": True},
                "expected": {"approved": True, "cb_response_code": "00"}
            },
            {
                "name": "Transaction CL 4 (1€) -> dépasse 150€ cumul",
                "request": {"pan": "4111111111111111", "amount": 100, "is_contactless": True, "skip_crypto": True},
                "expected": {"approved": False, "cb_response_code": "A5"}
            }
        ]
    ),
    CertificationScenario(
        "INVALID_ARQC",
        "Vérification d'un ARQC invalide (RC=63)",
        steps=[
            {
                "name": "Transaction avec ARQC erroné",
                "request": {
                    "pan": "4111111111111111", "amount": 1000, 
                    "field_55": "9F2608BADBADBADBADBADBAD", # ARQC bidon
                },
                "expected": {"approved": False, "response_code": "63"}
            }
        ]
    ),
    CertificationScenario(
        "CARD_BLOCKED",
        "Refus immédiat d'une carte bloquée (RC=62)",
        steps=[
            {
                "name": "Blocage de la carte",
                "request": {"admin_action": "block", "pan": "4111111111111111"},
                "expected": {"success": True}
            },
            {
                "name": "Tentative d'achat",
                "request": {"pan": "4111111111111111", "amount": 1000, "skip_crypto": True},
                "expected": {"approved": False, "response_code": "62"}
            }
        ]
    )
]
