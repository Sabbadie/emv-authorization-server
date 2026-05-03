"""
P2 — Sauvegarde JSON périodique de l'état en mémoire.
Sauvegarde : transactions + carte (soldes, compteurs, statuts) toutes les N minutes.
Restauration automatique au démarrage si le fichier de snapshot existe.
"""

import os
import json
import logging
import signal
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE", "data/snapshot.json")
SNAPSHOT_INTERVAL = int(os.getenv("SNAPSHOT_INTERVAL_SECS", 120))


def _ensure_dir():
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)


def save_snapshot(card_db, transaction_log):
    """Sérialise l'état complet en JSON et l'écrit sur disque."""
    try:
        _ensure_dir()
        cards_data = []
        for card in card_db.all_cards():
            cards_data.append({
                "pan": card.pan,
                "expiry": card.expiry,
                "cardholder_name": card.cardholder_name,
                "psn": card.psn,
                "status": card.status,
                "balance": card.balance,
                "daily_limit": card.daily_limit,
                "daily_spent": card.daily_spent,
                "last_reset_date": card.last_reset_date,
                "last_atc": card.last_atc,
                "block_reason": card.block_reason,
                "blocked_at": card.blocked_at,
                "unblocked_at": card.unblocked_at,
                "block_history": card.block_history,
                "cb_scheme": card.cb_scheme,
                "cb_brand": card.cb_brand,
                "aid": card.aid,
                "contactless_cumul": card.contactless_cumul,
                "consecutive_offline": card.consecutive_offline,
                "last_contactless_reset": card.last_contactless_reset,
                "pin_tries": card.pin_tries,
            })

        txns_data = []
        for txn in transaction_log.get_all(limit=5000, offset=0):
            txns_data.append({
                "id": txn.id,
                "rrn": txn.rrn,
                "pan": txn.pan,
                "amount": txn.amount,
                "currency": txn.currency,
                "transaction_type": txn.transaction_type,
                "terminal_id": txn.terminal_id,
                "merchant_id": txn.merchant_id,
                "merchant_name": txn.merchant_name,
                "atc": txn.atc,
                "arqc": txn.arqc,
                "arpc": txn.arpc,
                "issuer_auth_data": txn.issuer_auth_data,
                "auth_code": txn.auth_code,
                "status": txn.status,
                "response_code": txn.response_code,
                "decline_reason": txn.decline_reason,
                "pos_entry_mode": txn.pos_entry_mode,
                "amount_tier": txn.amount_tier,
                "risk_level": txn.risk_level,
                "auth_path": txn.auth_path,
                "cb_scheme": txn.cb_scheme,
                "cb_brand": txn.cb_brand,
                "cb_service_indicator": txn.cb_service_indicator,
                "cb_sca_exemption": txn.cb_sca_exemption,
                "cb_floor_limit": txn.cb_floor_limit,
                "cb_is_contactless": txn.cb_is_contactless,
                "cb_response_code": txn.cb_response_code,
                "cb_decline_reason": txn.cb_decline_reason,
                "created_at": txn.created_at,
                "processed_at": txn.processed_at,
            })

        snapshot = {
            "version": "1.3.0",
            "saved_at": datetime.utcnow().isoformat() + "Z",
            "cards": cards_data,
            "transactions": txns_data,
        }

        tmp_file = SNAPSHOT_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, default=str)
        os.replace(tmp_file, SNAPSHOT_FILE)
        logger.info("Snapshot sauvegardé : %d cartes, %d transactions → %s",
                    len(cards_data), len(txns_data), SNAPSHOT_FILE)
        return True
    except Exception as e:
        logger.error("Erreur sauvegarde snapshot : %s", str(e))
        return False


def load_snapshot(card_db, transaction_log):
    """Restaure l'état depuis le fichier snapshot si disponible."""
    if not os.path.exists(SNAPSHOT_FILE):
        logger.info("Aucun snapshot trouvé — démarrage avec état initial.")
        return False

    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            snap = json.load(f)

        saved_at = snap.get("saved_at", "inconnu")
        cards_restored = 0
        txns_restored = 0

        from models.card import CardStatus
        for cd in snap.get("cards", []):
            card = card_db.get_card(cd["pan"])
            if card:
                card.status = cd.get("status", CardStatus.ACTIVE)
                card.balance = cd.get("balance", card.balance)
                card.daily_spent = cd.get("daily_spent", 0)
                card.last_reset_date = cd.get("last_reset_date", card.last_reset_date)
                card.last_atc = cd.get("last_atc", 0)
                card.block_reason = cd.get("block_reason")
                card.blocked_at = cd.get("blocked_at")
                card.unblocked_at = cd.get("unblocked_at")
                card.block_history = cd.get("block_history", [])
                card.contactless_cumul = cd.get("contactless_cumul", 0)
                card.consecutive_offline = cd.get("consecutive_offline", 0)
                card.pin_tries = cd.get("pin_tries", 0)
                cards_restored += 1

        from models.transaction import Transaction, TransactionStatus
        for td in snap.get("transactions", []):
            txn = Transaction.__new__(Transaction)
            txn.id = td["id"]
            txn.rrn = td.get("rrn", "")
            txn.pan = td["pan"]
            txn.amount = td.get("amount", 0)
            txn.currency = td.get("currency", "978")
            txn.transaction_type = td.get("transaction_type", "00")
            txn.terminal_id = td.get("terminal_id")
            txn.merchant_id = td.get("merchant_id")
            txn.merchant_name = td.get("merchant_name")
            txn.atc = td.get("atc")
            txn.arqc = td.get("arqc")
            txn.arpc = td.get("arpc")
            txn.issuer_auth_data = td.get("issuer_auth_data")
            txn.auth_code = td.get("auth_code")
            txn.status = td.get("status", TransactionStatus.PENDING)
            txn.response_code = td.get("response_code")
            txn.decline_reason = td.get("decline_reason")
            txn.pos_entry_mode = td.get("pos_entry_mode")
            txn.amount_tier = td.get("amount_tier")
            txn.risk_level = td.get("risk_level")
            txn.auth_path = td.get("auth_path")
            txn.cb_scheme = td.get("cb_scheme")
            txn.cb_brand = td.get("cb_brand")
            txn.cb_service_indicator = td.get("cb_service_indicator")
            txn.cb_sca_exemption = td.get("cb_sca_exemption")
            txn.cb_floor_limit = td.get("cb_floor_limit")
            txn.cb_is_contactless = td.get("cb_is_contactless", False)
            txn.cb_response_code = td.get("cb_response_code")
            txn.cb_decline_reason = td.get("cb_decline_reason")
            txn.emv_data = None
            txn.created_at = td.get("created_at", "")
            txn.processed_at = td.get("processed_at")
            transaction_log.add(txn)
            txns_restored += 1

        logger.info("Snapshot restauré (sauvegardé le %s) : %d cartes, %d transactions",
                    saved_at, cards_restored, txns_restored)
        return True
    except Exception as e:
        logger.error("Erreur restauration snapshot : %s", str(e))
        return False


class PeriodicSnapshot:
    """Lance une sauvegarde automatique toutes les N secondes en arrière-plan."""

    def __init__(self, card_db, transaction_log, interval=SNAPSHOT_INTERVAL):
        self._card_db = card_db
        self._transaction_log = transaction_log
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="snapshot-worker", daemon=True)
        self._thread.start()
        logger.info("Sauvegarde périodique activée (intervalle: %ds)", self._interval)

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
