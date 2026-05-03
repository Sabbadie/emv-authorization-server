"""
P2/P1 — Import JSON → Base de données (récupération après perte de connexion).

Permet de réimporter dans PostgreSQL/SQLite le contenu d'un snapshot JSON
lorsque la DB était indisponible lors de l'enregistrement des transactions.

Stratégie :
- Cards       : UPSERT (insert ou mise à jour si PAN déjà présent)
- Transactions : INSERT IGNORE (skip si ID déjà présent — pas de doublon)

Utilisation :
    from db_import import import_snapshot_to_db, auto_recover
    result = import_snapshot_to_db("data/snapshots/snapshot_20260503_120000.json")
    result = import_snapshot_to_db(path, dry_run=True)   # simulation sans écriture
    result = auto_recover()                               # récupération automatique
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Imports DB au niveau module pour permettre le patch dans les tests
try:
    from database import is_db_available, get_session
    from models.orm_models import CardORM, TransactionORM
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    is_db_available = None   # type: ignore[assignment]
    get_session = None       # type: ignore[assignment]
    CardORM = None           # type: ignore[assignment]
    TransactionORM = None    # type: ignore[assignment]


# ── Import principal ───────────────────────────────────────────────────────────

def import_snapshot_to_db(path: str, *, dry_run: bool = False) -> dict:
    """
    Importe un snapshot JSON dans la base de données.

    Args:
        path    : chemin vers le fichier snapshot JSON
        dry_run : si True, simule l'import sans écrire dans la DB

    Returns:
        dict avec compteurs d'import et éventuelles erreurs
    """
    result = {
        "path":           path,
        "dry_run":        dry_run,
        "started_at":     datetime.utcnow().isoformat() + "Z",
        "cards_inserted": 0,
        "cards_updated":  0,
        "cards_skipped":  0,
        "txns_inserted":  0,
        "txns_skipped":   0,
        "errors":         [],
        "success":        False,
    }

    if not os.path.exists(path):
        result["errors"].append("Fichier introuvable : {}".format(path))
        return result

    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except Exception as e:
        result["errors"].append("Erreur lecture JSON : {}".format(e))
        return result

    result["snapshot_version"]  = snap.get("version", "?")
    result["snapshot_saved_at"] = snap.get("saved_at", "?")
    result["nb_cards_in_file"]  = len(snap.get("cards", []))
    result["nb_txns_in_file"]   = len(snap.get("transactions", []))

    if not _DB_AVAILABLE:
        result["errors"].append("Module database non disponible")
        return result

    if not is_db_available():
        result["errors"].append("Base de données indisponible — import impossible")
        return result

    _import_cards(snap.get("cards", []), result, dry_run)
    _import_transactions(snap.get("transactions", []), result, dry_run)

    result["finished_at"] = datetime.utcnow().isoformat() + "Z"
    result["success"]     = len(result["errors"]) == 0
    return result


# ── Import cartes ──────────────────────────────────────────────────────────────

def _import_cards(cards_data: list, result: dict, dry_run: bool):
    """Upsert des cartes dans la DB ORM."""
    for cd in cards_data:
        pan = cd.get("pan")
        if not pan:
            result["cards_skipped"] += 1
            continue
        try:
            if dry_run:
                result["cards_inserted"] += 1
                continue
            with get_session() as session:
                existing = session.get(CardORM, pan)
                if existing is None:
                    new_card = CardORM(
                        pan                 = pan,
                        expiry              = cd.get("expiry", "9912"),
                        cardholder_name     = cd.get("cardholder_name", ""),
                        psn                 = cd.get("psn", "00"),
                        status              = cd.get("status", "ACTIVE"),
                        balance             = cd.get("balance", 0),
                        daily_limit         = cd.get("daily_limit", 300000),
                        daily_spent         = cd.get("daily_spent", 0),
                        last_reset_date     = cd.get("last_reset_date"),
                        last_atc            = cd.get("last_atc", 0),
                        block_reason        = cd.get("block_reason"),
                        blocked_at          = cd.get("blocked_at"),
                        block_history       = json.dumps(cd.get("block_history", [])),
                        cb_scheme           = cd.get("cb_scheme", ""),
                        cb_brand            = cd.get("cb_brand", ""),
                        aid                 = cd.get("aid"),
                        contactless_cumul   = cd.get("contactless_cumul", 0),
                        consecutive_offline = cd.get("consecutive_offline", 0),
                        pin_tries           = cd.get("pin_tries", 0),
                    )
                    session.add(new_card)
                    session.commit()
                    result["cards_inserted"] += 1
                else:
                    existing.balance             = cd.get("balance", existing.balance)
                    existing.daily_spent         = cd.get("daily_spent", existing.daily_spent)
                    existing.status              = cd.get("status", existing.status)
                    existing.last_atc            = cd.get("last_atc", existing.last_atc)
                    existing.block_reason        = cd.get("block_reason", existing.block_reason)
                    existing.contactless_cumul   = cd.get("contactless_cumul", existing.contactless_cumul)
                    existing.consecutive_offline = cd.get("consecutive_offline", existing.consecutive_offline)
                    existing.pin_tries           = cd.get("pin_tries", existing.pin_tries)
                    session.commit()
                    result["cards_updated"] += 1
        except Exception as e:
            result["errors"].append("Carte {} : {}".format(pan, str(e)))
            result["cards_skipped"] += 1


# ── Import transactions ────────────────────────────────────────────────────────

def _import_transactions(txns_data: list, result: dict, dry_run: bool):
    """Insert des transactions dans la DB ORM (skip si ID existant)."""
    for td in txns_data:
        txn_id = td.get("id")
        if not txn_id:
            result["txns_skipped"] += 1
            continue
        try:
            if dry_run:
                result["txns_inserted"] += 1
                continue
            with get_session() as session:
                existing = session.get(TransactionORM, txn_id)
                if existing is not None:
                    result["txns_skipped"] += 1
                    continue
                new_txn = TransactionORM(
                    id                   = txn_id,
                    rrn                  = td.get("rrn", ""),
                    pan                  = td.get("pan", ""),
                    amount               = td.get("amount", 0),
                    currency             = td.get("currency", "978"),
                    transaction_type     = td.get("transaction_type", "00"),
                    terminal_id          = td.get("terminal_id"),
                    merchant_id          = td.get("merchant_id"),
                    merchant_name        = td.get("merchant_name"),
                    atc                  = td.get("atc"),
                    arqc                 = td.get("arqc"),
                    arpc                 = td.get("arpc"),
                    issuer_auth_data     = td.get("issuer_auth_data"),
                    auth_code            = td.get("auth_code"),
                    status               = td.get("status", "PENDING"),
                    response_code        = td.get("response_code"),
                    decline_reason       = td.get("decline_reason"),
                    pos_entry_mode       = td.get("pos_entry_mode"),
                    amount_tier          = td.get("amount_tier"),
                    risk_level           = td.get("risk_level"),
                    auth_path            = td.get("auth_path"),
                    cb_scheme            = td.get("cb_scheme"),
                    cb_brand             = td.get("cb_brand"),
                    cb_service_indicator = td.get("cb_service_indicator"),
                    cb_sca_exemption     = td.get("cb_sca_exemption"),
                    cb_floor_limit       = td.get("cb_floor_limit"),
                    cb_is_contactless    = td.get("cb_is_contactless", False),
                    cb_response_code     = td.get("cb_response_code"),
                    cb_decline_reason    = td.get("cb_decline_reason"),
                    created_at           = td.get("created_at",
                                                   datetime.utcnow().isoformat()),
                    processed_at         = td.get("processed_at"),
                )
                session.add(new_txn)
                session.commit()
                result["txns_inserted"] += 1
        except Exception as e:
            result["errors"].append("Transaction {} : {}".format(txn_id, str(e)))
            result["txns_skipped"] += 1


# ── Récupération automatique ───────────────────────────────────────────────────

def auto_recover(snapshot_path: Optional[str] = None) -> dict:
    """
    Tente de récupérer automatiquement les données depuis le dernier snapshot
    disponible lorsque la DB est disponible mais vide (perte de données).
    Typiquement appelée au démarrage après reconnexion DB.
    """
    from persistence import get_latest_snapshot_path

    target = snapshot_path or get_latest_snapshot_path()

    if not target:
        return {
            "success": False,
            "message": "Aucun snapshot disponible pour la récupération",
        }

    logger.info("[DB Import] Récupération automatique depuis : %s", target)
    result = import_snapshot_to_db(target)

    if result["success"]:
        logger.info("[DB Import] Récupération réussie — %d cartes, %d transactions importées",
                    result["cards_inserted"] + result["cards_updated"],
                    result["txns_inserted"])
    else:
        logger.error("[DB Import] Échec récupération : %s", result["errors"])

    return result


# ── Historique disponible ──────────────────────────────────────────────────────

def get_import_history() -> list:
    """
    Retourne la liste des snapshots disponibles pour import,
    avec des informations utiles (taille, importable, nb enregistrements).
    """
    from persistence import list_snapshots
    enriched = []
    for s in list_snapshots():
        entry = dict(s)
        entry["importable"] = os.path.exists(s.get("path", ""))
        entry["size_kb"]    = round(s.get("size_bytes", 0) / 1024, 1)
        enriched.append(entry)
    return enriched
