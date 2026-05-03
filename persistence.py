"""
P2 — Sauvegarde JSON périodique de l'état en mémoire.
Sauvegarde : transactions + cartes (soldes, compteurs, statuts) toutes les N secondes.
Restauration automatique au démarrage si le fichier de snapshot existe.

v1.10.0 : Historique 7 jours — rotation quotidienne avec index JSON.
          Un snapshot horodaté est conservé dans data/snapshots/ à chaque sauvegarde.
          Les fichiers de plus de SNAPSHOT_RETENTION_DAYS jours sont supprimés.
"""

import os
import json
import logging
import signal
import threading
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_FILE        = os.getenv("SNAPSHOT_FILE",         "data/snapshot.json")
SNAPSHOT_DIR         = os.getenv("SNAPSHOT_DIR",          "data/snapshots")
SNAPSHOT_INTERVAL    = int(os.getenv("SNAPSHOT_INTERVAL_SECS",  120))
SNAPSHOT_RETENTION   = int(os.getenv("SNAPSHOT_RETENTION_DAYS",   7))
SNAPSHOT_INDEX_FILE  = os.path.join(SNAPSHOT_DIR, "index.json")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_dirs():
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def _build_snapshot_data(card_db, transaction_log):
    """Sérialise l'état complet en dict prêt pour JSON."""
    cards_data = []
    for card in card_db.all_cards():
        cards_data.append({
            "pan":                    card.pan,
            "expiry":                 card.expiry,
            "cardholder_name":        card.cardholder_name,
            "psn":                    card.psn,
            "status":                 card.status,
            "balance":                card.balance,
            "daily_limit":            card.daily_limit,
            "daily_spent":            card.daily_spent,
            "last_reset_date":        card.last_reset_date,
            "last_atc":               card.last_atc,
            "block_reason":           card.block_reason,
            "blocked_at":             card.blocked_at,
            "unblocked_at":           card.unblocked_at,
            "block_history":          card.block_history,
            "cb_scheme":              card.cb_scheme,
            "cb_brand":               card.cb_brand,
            "aid":                    card.aid,
            "contactless_cumul":      card.contactless_cumul,
            "consecutive_offline":    card.consecutive_offline,
            "last_contactless_reset": card.last_contactless_reset,
            "pin_tries":              card.pin_tries,
        })

    txns_data = []
    for txn in transaction_log.get_all(limit=5000, offset=0):
        txns_data.append({
            "id":                   txn.id,
            "rrn":                  txn.rrn,
            "pan":                  txn.pan,
            "amount":               txn.amount,
            "currency":             txn.currency,
            "transaction_type":     txn.transaction_type,
            "terminal_id":          txn.terminal_id,
            "merchant_id":          txn.merchant_id,
            "merchant_name":        txn.merchant_name,
            "atc":                  txn.atc,
            "arqc":                 txn.arqc,
            "arpc":                 txn.arpc,
            "issuer_auth_data":     txn.issuer_auth_data,
            "auth_code":            txn.auth_code,
            "status":               txn.status,
            "response_code":        txn.response_code,
            "decline_reason":       txn.decline_reason,
            "pos_entry_mode":       txn.pos_entry_mode,
            "amount_tier":          txn.amount_tier,
            "risk_level":           txn.risk_level,
            "auth_path":            txn.auth_path,
            "cb_scheme":            txn.cb_scheme,
            "cb_brand":             txn.cb_brand,
            "cb_service_indicator": txn.cb_service_indicator,
            "cb_sca_exemption":     txn.cb_sca_exemption,
            "cb_floor_limit":       txn.cb_floor_limit,
            "cb_is_contactless":    txn.cb_is_contactless,
            "cb_response_code":     txn.cb_response_code,
            "cb_decline_reason":    txn.cb_decline_reason,
            "created_at":           txn.created_at,
            "processed_at":         txn.processed_at,
        })

    return {
        "version":      "1.10.0",
        "saved_at":     datetime.utcnow().isoformat() + "Z",
        "cards":        cards_data,
        "transactions": txns_data,
    }


def _write_json_atomic(path, data):
    """Écriture atomique via fichier temporaire + rename."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    os.replace(tmp, path)


# ── Sauvegarde principale ──────────────────────────────────────────────────────

def save_snapshot(card_db, transaction_log):
    """
    Sérialise l'état complet en JSON.
    - Écrit data/snapshot.json (dernier état, écrasé)
    - Écrit data/snapshots/snapshot_YYYYMMDD_HHMMSS.json (historique)
    - Met à jour data/snapshots/index.json
    - Purge les snapshots > SNAPSHOT_RETENTION jours
    """
    try:
        _ensure_dirs()
        snapshot = _build_snapshot_data(card_db, transaction_log)

        # 1. Snapshot courant (toujours écrasé)
        _write_json_atomic(SNAPSHOT_FILE, snapshot)

        # 2. Snapshot horodaté dans l'historique
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        hist_filename = "snapshot_{}.json".format(ts)
        hist_path = os.path.join(SNAPSHOT_DIR, hist_filename)
        _write_json_atomic(hist_path, snapshot)

        nb_cards = len(snapshot["cards"])
        nb_txns  = len(snapshot["transactions"])

        logger.info("Snapshot sauvegardé : %d cartes, %d transactions → %s + %s",
                    nb_cards, nb_txns, SNAPSHOT_FILE, hist_filename)

        # 3. Mise à jour de l'index
        _update_index(hist_filename, hist_path, snapshot["saved_at"],
                      nb_cards, nb_txns)

        # 4. Rotation : suppression des anciens
        removed = cleanup_old_snapshots()
        if removed:
            logger.info("Rotation snapshots : %d fichier(s) supprimé(s) (>%d jours)",
                        removed, SNAPSHOT_RETENTION)

        return True
    except Exception as e:
        logger.error("Erreur sauvegarde snapshot : %s", str(e))
        return False


def _update_index(filename, filepath, saved_at, nb_cards, nb_txns):
    """Ajoute une entrée dans l'index des snapshots."""
    try:
        index = _load_index()
        size_bytes = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        entry = {
            "filename":   filename,
            "saved_at":   saved_at,
            "nb_cards":   nb_cards,
            "nb_txns":    nb_txns,
            "size_bytes": size_bytes,
            "path":       filepath,
        }
        # Dé-duplication par filename
        index["snapshots"] = [s for s in index.get("snapshots", [])
                               if s.get("filename") != filename]
        index["snapshots"].append(entry)
        # Tri chronologique décroissant
        index["snapshots"].sort(key=lambda s: s["saved_at"], reverse=True)
        index["updated_at"] = datetime.utcnow().isoformat() + "Z"
        _write_json_atomic(SNAPSHOT_INDEX_FILE, index)
    except Exception as e:
        logger.warning("Erreur mise à jour index snapshots : %s", e)


def _load_index():
    """Charge ou initialise l'index des snapshots."""
    if os.path.exists(SNAPSHOT_INDEX_FILE):
        try:
            with open(SNAPSHOT_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"snapshots": [], "updated_at": None}


# ── Gestion de l'historique ────────────────────────────────────────────────────

def list_snapshots():
    """
    Retourne la liste des snapshots disponibles depuis l'index,
    complétée par un scan du répertoire si l'index est absent.
    """
    index = _load_index()
    entries = index.get("snapshots", [])

    if not entries and os.path.exists(SNAPSHOT_DIR):
        entries = _scan_snapshot_dir()

    return entries


def _scan_snapshot_dir():
    """Scan du répertoire pour reconstruire l'index à partir des fichiers."""
    entries = []
    for name in sorted(os.listdir(SNAPSHOT_DIR), reverse=True):
        if not name.startswith("snapshot_") or not name.endswith(".json"):
            continue
        if name == "index.json":
            continue
        path = os.path.join(SNAPSHOT_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            entries.append({
                "filename":   name,
                "saved_at":   snap.get("saved_at", ""),
                "nb_cards":   len(snap.get("cards", [])),
                "nb_txns":    len(snap.get("transactions", [])),
                "size_bytes": os.path.getsize(path),
                "path":       path,
            })
        except Exception:
            continue
    return entries


def cleanup_old_snapshots():
    """
    Supprime les snapshots dont la date de sauvegarde dépasse
    SNAPSHOT_RETENTION jours. Retourne le nombre de fichiers supprimés.
    """
    if not os.path.exists(SNAPSHOT_DIR):
        return 0

    cutoff = datetime.utcnow() - timedelta(days=SNAPSHOT_RETENTION)
    removed = 0
    index = _load_index()
    kept   = []

    for entry in index.get("snapshots", []):
        saved_at_str = entry.get("saved_at", "")
        try:
            saved_at = datetime.fromisoformat(saved_at_str.rstrip("Z"))
        except Exception:
            kept.append(entry)
            continue

        if saved_at < cutoff:
            path = entry.get("path", "")
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    removed += 1
                    logger.debug("Snapshot supprimé (>%d jours) : %s",
                                 SNAPSHOT_RETENTION, entry["filename"])
                except OSError as e:
                    logger.warning("Impossible de supprimer %s : %s", path, e)
                    kept.append(entry)
        else:
            kept.append(entry)

    if removed:
        index["snapshots"] = kept
        index["updated_at"] = datetime.utcnow().isoformat() + "Z"
        try:
            _write_json_atomic(SNAPSHOT_INDEX_FILE, index)
        except Exception as e:
            logger.warning("Erreur mise à jour index après rotation : %s", e)

    return removed


def get_latest_snapshot_path():
    """Retourne le chemin du snapshot le plus récent (hors snapshot courant)."""
    entries = list_snapshots()
    if entries:
        return entries[0].get("path")
    if os.path.exists(SNAPSHOT_FILE):
        return SNAPSHOT_FILE
    return None


# ── Restauration en mémoire ────────────────────────────────────────────────────

def load_snapshot(card_db, transaction_log, path=None):
    """
    Restaure l'état depuis un fichier snapshot JSON.
    Si path est None, utilise SNAPSHOT_FILE (snapshot courant).
    """
    target = path or SNAPSHOT_FILE
    if not os.path.exists(target):
        logger.info("Aucun snapshot trouvé (%s) — démarrage avec état initial.", target)
        return False

    try:
        with open(target, "r", encoding="utf-8") as f:
            snap = json.load(f)

        saved_at = snap.get("saved_at", "inconnu")
        cards_restored = 0
        txns_restored  = 0

        from models.card import CardStatus
        for cd in snap.get("cards", []):
            card = card_db.get_card(cd["pan"])
            if card:
                card.status                = cd.get("status", CardStatus.ACTIVE)
                card.balance               = cd.get("balance", card.balance)
                card.daily_spent           = cd.get("daily_spent", 0)
                card.last_reset_date       = cd.get("last_reset_date", card.last_reset_date)
                card.last_atc              = cd.get("last_atc", 0)
                card.block_reason          = cd.get("block_reason")
                card.blocked_at            = cd.get("blocked_at")
                card.unblocked_at          = cd.get("unblocked_at")
                card.block_history         = cd.get("block_history", [])
                card.contactless_cumul     = cd.get("contactless_cumul", 0)
                card.consecutive_offline   = cd.get("consecutive_offline", 0)
                card.pin_tries             = cd.get("pin_tries", 0)
                cards_restored += 1

        from models.transaction import Transaction, TransactionStatus
        for td in snap.get("transactions", []):
            txn = Transaction.__new__(Transaction)
            txn.id                   = td["id"]
            txn.rrn                  = td.get("rrn", "")
            txn.pan                  = td["pan"]
            txn.amount               = td.get("amount", 0)
            txn.currency             = td.get("currency", "978")
            txn.transaction_type     = td.get("transaction_type", "00")
            txn.terminal_id          = td.get("terminal_id")
            txn.merchant_id          = td.get("merchant_id")
            txn.merchant_name        = td.get("merchant_name")
            txn.atc                  = td.get("atc")
            txn.arqc                 = td.get("arqc")
            txn.arpc                 = td.get("arpc")
            txn.issuer_auth_data     = td.get("issuer_auth_data")
            txn.auth_code            = td.get("auth_code")
            txn.status               = td.get("status", TransactionStatus.PENDING)
            txn.response_code        = td.get("response_code")
            txn.decline_reason       = td.get("decline_reason")
            txn.pos_entry_mode       = td.get("pos_entry_mode")
            txn.amount_tier          = td.get("amount_tier")
            txn.risk_level           = td.get("risk_level")
            txn.auth_path            = td.get("auth_path")
            txn.cb_scheme            = td.get("cb_scheme")
            txn.cb_brand             = td.get("cb_brand")
            txn.cb_service_indicator = td.get("cb_service_indicator")
            txn.cb_sca_exemption     = td.get("cb_sca_exemption")
            txn.cb_floor_limit       = td.get("cb_floor_limit")
            txn.cb_is_contactless    = td.get("cb_is_contactless", False)
            txn.cb_response_code     = td.get("cb_response_code")
            txn.cb_decline_reason    = td.get("cb_decline_reason")
            txn.emv_data             = None
            txn.created_at           = td.get("created_at", "")
            txn.processed_at         = td.get("processed_at")
            transaction_log.add(txn)
            txns_restored += 1

        logger.info("Snapshot restauré depuis %s (sauvegardé le %s) : %d cartes, %d txns",
                    target, saved_at, cards_restored, txns_restored)
        return True
    except Exception as e:
        logger.error("Erreur restauration snapshot depuis %s : %s", target, str(e))
        return False


# ── Worker périodique ──────────────────────────────────────────────────────────

class PeriodicSnapshot:
    """Lance une sauvegarde automatique toutes les N secondes en arrière-plan."""

    def __init__(self, card_db, transaction_log, interval=SNAPSHOT_INTERVAL):
        self._card_db          = card_db
        self._transaction_log  = transaction_log
        self._interval         = interval
        self._stop_event       = threading.Event()
        self._thread           = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="snapshot-worker", daemon=True)
        self._thread.start()
        logger.info("Sauvegarde périodique activée (intervalle: %ds, rétention: %dj)",
                    self._interval, SNAPSHOT_RETENTION)

    def stop(self):
        self._stop_event.set()
        save_snapshot(self._card_db, self._transaction_log)
        logger.info("Snapshot final sauvegardé à l'arrêt.")

    def _run(self):
        while not self._stop_event.wait(self._interval):
            save_snapshot(self._card_db, self._transaction_log)


def register_shutdown_handler(snapshot_worker):
    """Enregistre le handler SIGTERM pour sauvegarde propre à l'arrêt."""
    def _handler(signum, frame):
        logger.info("Signal %d reçu — sauvegarde snapshot avant arrêt…", signum)
        snapshot_worker.stop()
    signal.signal(signal.SIGTERM, _handler)
