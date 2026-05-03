#!/usr/bin/env python3
"""
Simulateur de terminal de paiement — Exemple de connexion TCP au serveur d'autorisation EMV.

Usage :
    python tools/terminal_simulator.py [--host HOST] [--port PORT] [--scenario SCENARIO]

Scénarios disponibles :
    basic        — Achat simple (PAN actif, montant SMALL)
    contactless  — Paiement sans contact
    emv          — Achat avec données EMV (champ 55)
    iso8583      — Requête au format ISO 8583 dict
    batch        — Envoi de 10 transactions variées
    interactive  — Saisie manuelle de la requête

Exemple :
    python tools/terminal_simulator.py --scenario batch
    python tools/terminal_simulator.py --host localhost --port 8583 --scenario basic
"""

import argparse
import json
import socket
import struct
import sys
import time

LENGTH_FMT  = ">I"
LENGTH_SIZE = struct.calcsize(LENGTH_FMT)


# ─────────────────────────────────────────────────────────────────────────────
# Client TCP bas niveau
# ─────────────────────────────────────────────────────────────────────────────

class TerminalClient:
    def __init__(self, host: str = "localhost", port: int = 8583, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        print(f"[TERMINAL] Connecté à {self.host}:{self.port}")

    def disconnect(self):
        if self._sock:
            self._sock.close()
            self._sock = None
        print("[TERMINAL] Déconnecté")

    def send(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = struct.pack(LENGTH_FMT, len(body))
        self._sock.sendall(header + body)
        return self._recv()

    def _recv(self) -> dict:
        header = self._recv_exact(LENGTH_SIZE)
        length = struct.unpack(LENGTH_FMT, header)[0]
        body   = self._recv_exact(length)
        return json.loads(body.decode("utf-8"))

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Connexion fermée pendant la réception")
            buf.extend(chunk)
        return bytes(buf)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# Affichage du résultat
# ─────────────────────────────────────────────────────────────────────────────

def print_response(response: dict, scenario: str = ""):
    status  = "✅ APPROUVÉ" if response.get("approved") else "❌ REFUSÉ"
    rc      = response.get("response_code", "??")
    tier    = response.get("tier", "-")
    auth    = response.get("auth_code", "-")
    pan     = response.get("pan_masked", "-")
    txn_id  = response.get("transaction_id", "-")
    message = response.get("message", "")
    error   = response.get("error", "")
    print()
    print(f"  ━━━ Réponse {scenario} ━━━")
    print(f"  Statut      : {status}  (RC={rc})")
    print(f"  PAN         : {pan}")
    print(f"  Tranche     : {tier}")
    print(f"  Auth code   : {auth}")
    print(f"  Transaction : {txn_id}")
    if message:
        print(f"  Message     : {message}")
    if error:
        print(f"  Erreur      : {error}")
    if response.get("arpc"):
        print(f"  ARPC        : {response['arpc']}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Scénarios de test
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = {
    "basic": {
        "description": "Achat simple (format natif)",
        "request": {
            "pan":              "4111111111111111",
            "amount":           5000,
            "currency":         "978",
            "transaction_type": "00",
            "terminal_id":      "TERM0001",
            "merchant_id":      "MERCH0001",
            "merchant_name":    "BOUTIQUE TEST",
            "skip_crypto":      True,
        }
    },
    "contactless": {
        "description": "Paiement sans contact NFC",
        "request": {
            "pan":              "4111111111111111",
            "amount":           1500,
            "currency":         "978",
            "transaction_type": "00",
            "terminal_id":      "NFC_TERM01",
            "is_contactless":   True,
            "pos_entry_mode":   "071",
            "skip_crypto":      True,
        }
    },
    "emv": {
        "description": "Achat avec données EMV (champ 55)",
        "request": {
            "pan":              "4111111111111111",
            "amount":           15000,
            "currency":         "978",
            "transaction_type": "00",
            "terminal_id":      "EMV_TERM01",
            "skip_crypto":      True,
            "field_55": (
                "9F02060000000150009F03060000000000009F1A020250"
                "950500000000009A032601019C01009F370412345678"
                "9F360200059F2608AABBCCDD112233449F270140"
            ),
        }
    },
    "iso8583": {
        "description": "Requête au format ISO 8583 dict (MTI 0100)",
        "request": {
            "mti": "0100",
            "fields": {
                "2":  "4111111111111111",
                "3":  "000000",
                "4":  "000000005000",
                "7":  "0523143015",
                "11": "000042",
                "12": "143015",
                "13": "0523",
                "22": "051",
                "25": "00",
                "37": "123456789012",
                "41": "TERM0001",
                "42": "MERCH0001      ",
                "43": "BOUTIQUE TEST ISO8583           PARIS  FR",
                "49": "978",
            }
        }
    },
    "blocked": {
        "description": "Carte bloquée (doit être refusée RC=62)",
        "request": {
            "pan":              "4000000000000028",
            "amount":           5000,
            "currency":         "978",
            "transaction_type": "00",
            "skip_crypto":      True,
        }
    },
    "expired": {
        "description": "Carte expirée (doit être refusée RC=54)",
        "request": {
            "pan":              "4000000000000010",
            "amount":           5000,
            "currency":         "978",
            "transaction_type": "00",
            "skip_crypto":      True,
        }
    },
}

BATCH_REQUESTS = [
    {"pan": "4111111111111111", "amount": 200,    "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "4111111111111111", "amount": 5000,   "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "5500000000000004", "amount": 15000,  "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "4000000000000002", "amount": 30000,  "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "4970100000000154", "amount": 1000,   "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "4111111111111111", "amount": 1500,   "currency": "978", "transaction_type": "00", "is_contactless": True, "skip_crypto": True},
    {"pan": "4000000000000036", "amount": 5000,   "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "4000000000000028", "amount": 5000,   "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "5500000000000004", "amount": 100000, "currency": "978", "transaction_type": "00", "skip_crypto": True},
    {"pan": "4111111111111111", "amount": 500000, "currency": "978", "transaction_type": "01", "skip_crypto": True},
]


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Simulateur de terminal de paiement EMV")
    parser.add_argument("--host",     default="localhost",  help="Adresse du serveur TCP (défaut: localhost)")
    parser.add_argument("--port",     default=8583, type=int, help="Port TCP (défaut: 8583)")
    parser.add_argument("--scenario", default="basic",
                        choices=list(SCENARIOS.keys()) + ["batch", "interactive"],
                        help="Scénario à exécuter")
    args = parser.parse_args()

    print(f"\n{'━'*60}")
    print(f"  Simulateur de terminal de paiement EMV")
    print(f"  Serveur cible : {args.host}:{args.port}")
    print(f"  Scénario      : {args.scenario}")
    print(f"{'━'*60}\n")

    try:
        with TerminalClient(args.host, args.port) as client:

            if args.scenario == "batch":
                print(f"[TERMINAL] Envoi de {len(BATCH_REQUESTS)} transactions...")
                approved = 0
                for i, req in enumerate(BATCH_REQUESTS, 1):
                    pan_last4 = req["pan"][-4:]
                    amount_eur = req["amount"] / 100
                    print(f"  [{i:02d}] PAN=****{pan_last4} Montant={amount_eur:.2f}€ ...", end=" ")
                    resp = client.send(req)
                    flag = "✅" if resp.get("approved") else "❌"
                    rc   = resp.get("response_code", "??")
                    print(f"{flag} RC={rc}")
                    if resp.get("approved"):
                        approved += 1
                    time.sleep(0.05)
                print(f"\n  Résultat : {approved}/{len(BATCH_REQUESTS)} approuvées")

            elif args.scenario == "interactive":
                print("[TERMINAL] Mode interactif — saisissez une requête JSON (Ctrl+C pour quitter)")
                while True:
                    try:
                        raw = input("\n  Requête JSON> ").strip()
                        if not raw:
                            continue
                        req = json.loads(raw)
                        resp = client.send(req)
                        print_response(resp, "interactive")
                    except KeyboardInterrupt:
                        break
                    except json.JSONDecodeError as exc:
                        print(f"  JSON invalide : {exc}")

            else:
                scenario = SCENARIOS[args.scenario]
                print(f"[TERMINAL] {scenario['description']}")
                req  = scenario["request"]
                resp = client.send(req)
                print_response(resp, args.scenario)

    except ConnectionRefusedError:
        print(f"\n[ERREUR] Impossible de se connecter à {args.host}:{args.port}")
        print("  Vérifiez que le serveur est démarré (python main.py) et que TCP_ENABLED=true")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[ERREUR] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
