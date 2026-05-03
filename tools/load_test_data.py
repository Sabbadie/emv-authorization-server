#!/usr/bin/env python3
"""
Chargement du jeu d'essai utilisateurs via l'API REST.
Usage : python tools/load_test_data.py [--url http://localhost:5000] [--scenario SC01]
"""

import argparse
import json
import sys
import time
from pathlib import Path
import urllib.request
import urllib.error

BASE_DIR = Path(__file__).parent.parent
JEU_ESSAI = BASE_DIR / "test_data" / "jeu_essai.json"


def api_call(base_url, method, path, body=None, api_key=None):
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"error": body}
    except Exception as e:
        return 0, {"error": str(e)}


def print_result(scenario_id, nom, status, response, expected):
    ok = status in (200, 201, 202)
    sym = "✓" if ok else "✗"
    print(f"  {sym} [{status}] {scenario_id}: {nom}")
    if not ok:
        print(f"      Réponse : {json.dumps(response, ensure_ascii=False)[:200]}")
    return ok


def run_scenario(scenario, base_url, api_key, context):
    sid = scenario["id"]
    nom = scenario["nom"]
    method = scenario.get("methode", "GET")
    endpoint = scenario.get("endpoint", "")
    body = scenario.get("corps")

    # Substitution de variables de contexte (ex: {{TOKEN_SC10}})
    if body:
        body_str = json.dumps(body)
        for k, v in context.items():
            body_str = body_str.replace("{{" + k + "}}", str(v))
        body = json.loads(body_str)

    # Substitution dans le path (ex: {id})
    for k, v in context.items():
        endpoint = endpoint.replace("{" + k + "}", str(v))

    if method == "GET" and body is None:
        status, response = api_call(base_url, "GET", endpoint, api_key=api_key)
    else:
        status, response = api_call(base_url, method, endpoint, body, api_key=api_key)

    expected = scenario.get("reponse_attendue", {})
    ok = print_result(sid, nom, status, response, expected)

    # Mise à jour du contexte avec les réponses
    if ok and response:
        if "id" in response:
            context[sid + "_id"] = response["id"]
            context["id"] = response["id"]
        if "token" in response:
            context["TOKEN_SC10"] = response.get("token", "")
        if "threeds_id" in response:
            context["threeds_id"] = response["threeds_id"]

    return ok, response, context


def main():
    parser = argparse.ArgumentParser(description="Charger le jeu d'essai EMV")
    parser.add_argument("--url", default="http://localhost:5000",
                        help="URL de base du serveur (défaut: http://localhost:5000)")
    parser.add_argument("--api-key", default="",
                        help="Clé API (si EMV_API_KEY configuré)")
    parser.add_argument("--scenario", default=None,
                        help="Exécuter uniquement ce scénario (ex: SC01)")
    parser.add_argument("--list", action="store_true",
                        help="Lister les scénarios disponibles")
    args = parser.parse_args()

    with open(JEU_ESSAI) as f:
        data = json.load(f)

    scenarios = data["scenarios"]
    cartes = {c["id"]: c for c in data["cartes_test"]}
    utilisateurs = data["utilisateurs_test"]

    if args.list:
        print("\n=== Scénarios disponibles ===")
        for s in scenarios:
            print(f"  {s['id']:6s}  {s['nom']}")
        print(f"\n=== Cartes de test ===")
        for c in data["cartes_test"]:
            print(f"  {c['id']:25s}  PAN: {c['pan']}  ({c['label'][:40]})")
        print(f"\n=== Utilisateurs de test ===")
        for u in utilisateurs:
            print(f"  {u['id']:8s}  {u['nom']:20s}  {u['profil']}")
        return 0

    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Jeu d'essai EMV Authorization Server v1.9.0         ║")
    print(f"║  Serveur : {args.url:<42}║")
    print(f"╚══════════════════════════════════════════════════════╝\n")

    # Vérifier que le serveur est disponible
    status, health = api_call(args.url, "GET", "/api/v1/health")
    if status != 200:
        print(f"✗ Serveur inaccessible ({args.url}) — code {status}")
        return 1
    print(f"✓ Serveur en ligne — version: {health.get('version', '?')}\n")

    context = {}
    passed = failed = 0

    filter_id = args.scenario

    print("── Exécution des scénarios ─────────────────────────────\n")

    for scenario in scenarios:
        if filter_id and scenario["id"] != filter_id:
            continue
        if scenario.get("note"):
            print(f"    ℹ  Note: {scenario['note']}")
        ok, resp, context = run_scenario(scenario, args.url, args.api_key, context)
        if ok:
            passed += 1
        else:
            failed += 1
        time.sleep(0.05)

    print(f"\n── Résultats ───────────────────────────────────────────")
    print(f"  Succès  : {passed}")
    print(f"  Échecs  : {failed}")
    print(f"  Total   : {passed + failed}")
    rate = passed / (passed + failed) * 100 if (passed + failed) > 0 else 0
    print(f"  Taux    : {rate:.0f}%")

    if failed == 0:
        print("\n✓ Tous les scénarios ont réussi.")
    else:
        print(f"\n✗ {failed} scénario(s) en échec — vérifier les logs du serveur.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
