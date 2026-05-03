#!/usr/bin/env python3
"""
A4 — CLI client EMV Authorization Server
Usage :
  python cli.py authorize --pan 4111111111111111 --amount 5000
  python cli.py batch --count 10
  python cli.py cards
  python cli.py stats
  python cli.py tiers
  python cli.py health
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = os.getenv("EMV_SERVER_URL", "http://localhost:5000")
API_KEY  = os.getenv("EMV_API_KEY", "")


def _headers():
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if API_KEY:
        h["X-Api-Key"] = API_KEY
    return h


def _get(path):
    req = urllib.request.Request(BASE_URL + path, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code
    except Exception as e:
        print("Erreur connexion :", e)
        sys.exit(1)


def _post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE_URL + path, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code
    except Exception as e:
        print("Erreur connexion :", e)
        sys.exit(1)


def _color(text, code):
    return "\033[{}m{}\033[0m".format(code, text)


def green(t): return _color(t, "32")
def red(t):   return _color(t, "31")
def yellow(t): return _color(t, "33")
def cyan(t):  return _color(t, "36")
def bold(t):  return _color(t, "1")


def cmd_health(args):
    data, status = _get("/api/v1/health")
    state = data.get("status", "?")
    color = green if state == "UP" else red
    print(bold("Santé du serveur :"), color(state))
    print("  Version  :", cyan(data.get("version", "?")))
    print("  Horodatage:", data.get("timestamp", "?"))
    features = data.get("features", [])
    if features:
        print("  Modules  :", ", ".join(features))


def cmd_authorize(args):
    payload = {
        "pan": args.pan.replace(" ", ""),
        "amount": args.amount,
        "currency": args.currency,
        "transaction_type": args.type,
        "terminal_id": args.terminal or "CLI001",
        "merchant_name": args.merchant or "CLI TEST",
        "pos_entry_mode": args.mode,
        "is_contactless": args.mode.startswith("07"),
        "mcc": args.mcc or None,
        "skip_crypto": True,
    }
    print(bold("Demande d'autorisation…"))
    print("  PAN      :", "****" + args.pan[-4:])
    print("  Montant  :", cyan("{:.2f} {}".format(args.amount / 100,
          {"840":"USD","978":"EUR","826":"GBP"}.get(args.currency, args.currency))))

    data, status = _post("/api/v1/authorize", payload)
    approved = data.get("approved", False)
    rc = data.get("response_code", "?")
    msg = data.get("message", "")

    if approved:
        print(bold("Résultat :"), green("APPROUVÉ ✓"))
        print("  Code auth :", green(data.get("auth_code", "?")))
    else:
        print(bold("Résultat :"), red("REFUSÉ ✗"))
    print("  Code réponse :", rc, "—", msg)

    if data.get("amount_decision"):
        ad = data["amount_decision"]
        print("  Tranche  :", yellow(ad.get("tier_name", "?")),
              "| Chemin :", ad.get("auth_path", "?"))

    if data.get("cb_result"):
        cb = data["cb_result"]
        print("  CB schéma:", cb.get("scheme", "?"),
              "| SCA :", cb.get("sca_exemption") or "Aucune")

    if not approved and "--tpa" in sys.argv:
        txn_id = data.get("transaction", {}).get("id")
        if txn_id:
            tpa_data, _ = _get("/api/v1/transactions/{}/tpa".format(txn_id))
            print("\n  Champs TPA :")
            for k, v in list((tpa_data.get("tpa_fields") or {}).items())[:10]:
                val = v.get("value", "")
                if isinstance(val, list):
                    val = ", ".join(str(x) for x in val)
                print("    {:4s}  {}".format(k, val))


def cmd_batch(args):
    payload = {"count": args.count, "seed": args.seed}
    print(bold("Simulation batch : {} transactions…".format(args.count)))
    data, status = _post("/api/v1/batch/simulate", payload)
    results = data.get("results", [])
    approved = sum(1 for r in results if r.get("approved"))
    declined = len(results) - approved
    print("  Résultats : {} approuvées | {} refusées".format(
        green(str(approved)), red(str(declined))))
    print("  Montant total approuvé : {:,.2f} €".format(
        data.get("total_approved_amount", 0) / 100))
    if args.verbose:
        for r in results[:20]:
            ok = r.get("approved")
            symbol = green("✓") if ok else red("✗")
            print("  {} PAN:...{} {:>8.2f}€  {} {}".format(
                symbol, r.get("pan", "????")[-4:],
                r.get("amount", 0) / 100,
                r.get("response_code", "?"),
                r.get("tier", "")))


def cmd_cards(args):
    data, _ = _get("/api/v1/cards")
    cards = data.get("cards", [])
    print(bold("Cartes de test ({}) :".format(len(cards))))
    print("  {:20s} {:24s} {:10s} {:>10s} {:>12s}".format(
        "PAN", "Titulaire", "Statut", "Solde", "Dépensé/j"))
    print("  " + "-" * 80)
    for c in cards:
        status = c.get("status", "?")
        s_color = green if status == "ACTIVE" else (red if status in ("BLOCKED","LOST","STOLEN") else yellow)
        print("  {:20s} {:24s} {:10s} {:>10s} {:>12s}".format(
            c.get("pan", "?"),
            c.get("cardholder_name", "?")[:24],
            s_color(status),
            "{:.2f}€".format(c.get("balance", 0) / 100),
            "{:.2f}€".format(c.get("daily_spent", 0) / 100),
        ))


def cmd_stats(args):
    data, _ = _get("/api/v1/stats")
    ts = data.get("transaction_stats", {})
    cs = data.get("card_stats", {})
    print(bold("Statistiques serveur :"))
    print("  Transactions : {} total | {} approuvées | {} refusées | {} erreurs".format(
        cyan(str(ts.get("total", 0))),
        green(str(ts.get("approved", 0))),
        red(str(ts.get("declined", 0))),
        yellow(str(ts.get("errors", 0)))))
    print("  Taux approbation :", ts.get("approval_rate", "N/A"))
    print("  Montant approuvé :", cyan("{:.2f} €".format(ts.get("total_approved_amount", 0) / 100)))
    print("  Cartes :", cs.get("total_cards", 0), "| Bloquées :", cs.get("blocked_list_size", 0))
    print("\n  Par tranche :")
    for tier, count in (ts.get("by_tier") or {}).items():
        print("    {:12s} : {}".format(tier, count))
    print("\n  Par schéma CB :")
    for scheme, count in (ts.get("by_cb_scheme") or {}).items():
        print("    {:12s} : {}".format(scheme, count))


def cmd_tiers(args):
    data, _ = _get("/api/v1/amount-tiers")
    tiers = data.get("tiers", [])
    rc = {"LOW": green, "MEDIUM": yellow, "HIGH": yellow,
          "VERY_HIGH": red, "CRITICAL": red}
    print(bold("Tranches de montant ({}) :".format(len(tiers))))
    for t in tiers:
        color = rc.get(t.get("risk_level", "LOW"), cyan)
        max_a = t.get("max_amount", 0)
        max_s = "∞" if max_a > 99999999 else "{:.2f}€".format(max_a / 100)
        print("  {:12s} {:>8.2f}€ → {} | Risque: {} | {}".format(
            color(t.get("name", "?")),
            t.get("min_amount", 0) / 100,
            max_s,
            color(t.get("risk_level", "?")),
            t.get("label", ""),
        ))


def main():
    parser = argparse.ArgumentParser(
        description="CLI Client — Serveur d'Autorisation EMV GIE CB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples :
  python cli.py health
  python cli.py authorize --pan 4111111111111111 --amount 5000
  python cli.py authorize --pan 5500000000000004 --amount 150000 --type 00 --mode 071
  python cli.py batch --count 20 --verbose
  python cli.py cards
  python cli.py stats
  python cli.py tiers

Variables d'environnement :
  EMV_SERVER_URL  : URL du serveur (défaut: http://localhost:5000)
  EMV_API_KEY     : Clé API (si authentification activée)
""")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="Vérifier la santé du serveur")

    p_auth = sub.add_parser("authorize", help="Envoyer une demande d'autorisation")
    p_auth.add_argument("--pan", required=True, help="PAN de la carte")
    p_auth.add_argument("--amount", type=int, default=5000,
                        help="Montant en centimes (défaut: 5000 = 50,00€)")
    p_auth.add_argument("--currency", default="978", help="Code devise ISO 4217 (défaut: 978=EUR)")
    p_auth.add_argument("--type", default="00", help="Type transaction (défaut: 00=Achat)")
    p_auth.add_argument("--mode", default="051", help="Mode saisie POS (défaut: 051=Puce)")
    p_auth.add_argument("--terminal", help="ID terminal (défaut: CLI001)")
    p_auth.add_argument("--merchant", help="Nom commerçant")
    p_auth.add_argument("--mcc", help="MCC commerçant")

    p_batch = sub.add_parser("batch", help="Simuler N transactions aléatoires")
    p_batch.add_argument("--count", type=int, default=10,
                         help="Nombre de transactions à simuler (max 100)")
    p_batch.add_argument("--seed", type=int, default=None, help="Graine aléatoire")
    p_batch.add_argument("--verbose", "-v", action="store_true", help="Afficher le détail")

    sub.add_parser("cards", help="Lister les cartes de test")
    sub.add_parser("stats", help="Afficher les statistiques")
    sub.add_parser("tiers", help="Lister les tranches de montant")

    args = parser.parse_args()
    cmds = {
        "health": cmd_health,
        "authorize": cmd_authorize,
        "batch": cmd_batch,
        "cards": cmd_cards,
        "stats": cmd_stats,
        "tiers": cmd_tiers,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
