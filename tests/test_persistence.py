"""
Tests unitaires — persistence.py
Couvre : save_snapshot, load_snapshot, PeriodicSnapshot
"""

import os
import json
import time
import threading
import tempfile
import pytest
from unittest.mock import patch

from models.card import Card, CardStatus, CardDatabase
from models.transaction import Transaction, TransactionLog, TransactionStatus
import persistence


def make_fresh_db_with_one_card():
    db = CardDatabase.__new__(CardDatabase)
    db._cards = {}
    db._blocked_list = set()
    card = Card(
        pan="4111111111111111",
        expiry="2812",
        cardholder_name="TEST USER",
        psn="01",
        status=CardStatus.ACTIVE,
        balance=75000,
        daily_limit=200000,
        cb_scheme="VISA",
        cb_brand="VISA CB",
    )
    db._cards[card.pan] = card
    return db, card


def make_fresh_log_with_one_txn():
    log = TransactionLog()
    txn = Transaction(
        pan="4111111111111111",
        amount=5000, currency="978",
        transaction_type="00",
    )
    txn.approve("123456")
    txn.amount_tier = "STANDARD"
    txn.auth_path = "ONLINE"
    log.add(txn)
    return log, txn


@pytest.fixture
def tmp_snapshot(tmp_path):
    snap_file = str(tmp_path / "snapshot.json")
    original = persistence.SNAPSHOT_FILE
    persistence.SNAPSHOT_FILE = snap_file
    yield snap_file
    persistence.SNAPSHOT_FILE = original


class TestSaveSnapshot:
    def test_returns_true_on_success(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        result = persistence.save_snapshot(db, log)
        assert result is True

    def test_creates_file(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        assert os.path.exists(tmp_snapshot)

    def test_file_is_valid_json(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_version_in_snapshot(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert "version" in data

    def test_saved_at_in_snapshot(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert "saved_at" in data

    def test_cards_in_snapshot(self, tmp_snapshot):
        db, card = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert len(data["cards"]) == 1
        assert data["cards"][0]["pan"] == card.pan

    def test_transactions_in_snapshot(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, txn = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert len(data["transactions"]) == 1
        assert data["transactions"][0]["id"] == txn.id

    def test_card_balance_saved(self, tmp_snapshot):
        db, card = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        card.balance = 99999
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert data["cards"][0]["balance"] == 99999

    def test_card_status_saved(self, tmp_snapshot):
        db, card = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        card.status = CardStatus.BLOCKED
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert data["cards"][0]["status"] == "BLOCKED"

    def test_empty_log(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log = TransactionLog()
        persistence.save_snapshot(db, log)
        with open(tmp_snapshot, "r") as f:
            data = json.load(f)
        assert data["transactions"] == []

    def test_atomic_write_no_partial_file(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db, log)
        tmp_file = tmp_snapshot + ".tmp"
        assert not os.path.exists(tmp_file)


class TestLoadSnapshot:
    def test_no_file_returns_false(self, tmp_snapshot):
        db = CardDatabase.__new__(CardDatabase)
        db._cards = {}
        db._blocked_list = set()
        log = TransactionLog()
        result = persistence.load_snapshot(db, log)
        assert result is False

    def test_restores_card_balance(self, tmp_snapshot):
        db_save, card = make_fresh_db_with_one_card()
        log_save, _ = make_fresh_log_with_one_txn()
        card.balance = 42000
        persistence.save_snapshot(db_save, log_save)

        db_load = CardDatabase.__new__(CardDatabase)
        db_load._cards = {}
        db_load._blocked_list = set()
        new_card = Card("4111111111111111", "2812", "TEST", balance=99999)
        db_load._cards[new_card.pan] = new_card
        log_load = TransactionLog()

        result = persistence.load_snapshot(db_load, log_load)
        assert result is True
        assert db_load.get_card("4111111111111111").balance == 42000

    def test_restores_card_status(self, tmp_snapshot):
        db_save, card = make_fresh_db_with_one_card()
        log_save = TransactionLog()
        card.status = CardStatus.BLOCKED
        persistence.save_snapshot(db_save, log_save)

        db_load = CardDatabase.__new__(CardDatabase)
        db_load._cards = {}
        db_load._blocked_list = set()
        new_card = Card("4111111111111111", "2812", "TEST")
        db_load._cards[new_card.pan] = new_card
        log_load = TransactionLog()

        persistence.load_snapshot(db_load, log_load)
        assert db_load.get_card("4111111111111111").status == CardStatus.BLOCKED

    def test_restores_transactions(self, tmp_snapshot):
        db_save, _ = make_fresh_db_with_one_card()
        log_save, txn = make_fresh_log_with_one_txn()
        persistence.save_snapshot(db_save, log_save)

        db_load = CardDatabase.__new__(CardDatabase)
        db_load._cards = {}
        db_load._blocked_list = set()
        log_load = TransactionLog()

        persistence.load_snapshot(db_load, log_load)
        restored = log_load.get(txn.id)
        assert restored is not None
        assert restored.pan == txn.pan
        assert restored.amount == txn.amount

    def test_unknown_pan_in_snapshot_skipped(self, tmp_snapshot):
        db_save, _ = make_fresh_db_with_one_card()
        log_save = TransactionLog()
        persistence.save_snapshot(db_save, log_save)

        db_load = CardDatabase.__new__(CardDatabase)
        db_load._cards = {}
        db_load._blocked_list = set()
        log_load = TransactionLog()

        result = persistence.load_snapshot(db_load, log_load)
        assert result is True

    def test_corrupted_file_returns_false(self, tmp_snapshot):
        with open(tmp_snapshot, "w") as f:
            f.write("NOT VALID JSON {{{")
        db = CardDatabase.__new__(CardDatabase)
        db._cards = {}
        db._blocked_list = set()
        log = TransactionLog()
        result = persistence.load_snapshot(db, log)
        assert result is False

    def test_restores_atc(self, tmp_snapshot):
        db_save, card = make_fresh_db_with_one_card()
        log_save = TransactionLog()
        card.last_atc = 77
        persistence.save_snapshot(db_save, log_save)

        db_load = CardDatabase.__new__(CardDatabase)
        db_load._cards = {}
        db_load._blocked_list = set()
        new_card = Card("4111111111111111", "2812", "TEST")
        db_load._cards[new_card.pan] = new_card
        log_load = TransactionLog()

        persistence.load_snapshot(db_load, log_load)
        assert db_load.get_card("4111111111111111").last_atc == 77

    def test_restores_contactless_counters(self, tmp_snapshot):
        db_save, card = make_fresh_db_with_one_card()
        log_save = TransactionLog()
        card.contactless_cumul = 2500
        card.consecutive_offline = 3
        persistence.save_snapshot(db_save, log_save)

        db_load = CardDatabase.__new__(CardDatabase)
        db_load._cards = {}
        db_load._blocked_list = set()
        new_card = Card("4111111111111111", "2812", "TEST")
        db_load._cards[new_card.pan] = new_card
        log_load = TransactionLog()

        persistence.load_snapshot(db_load, log_load)
        restored = db_load.get_card("4111111111111111")
        assert restored.contactless_cumul == 2500
        assert restored.consecutive_offline == 3


class TestPeriodicSnapshot:
    def test_start_creates_thread(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        worker = persistence.PeriodicSnapshot(db, log, interval=9999)
        worker.start()
        assert worker._thread is not None
        assert worker._thread.is_alive()
        worker._stop_event.set()

    def test_stop_triggers_snapshot(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        worker = persistence.PeriodicSnapshot(db, log, interval=9999)
        worker.start()
        worker.stop()
        assert os.path.exists(tmp_snapshot)

    def test_daemon_thread(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        worker = persistence.PeriodicSnapshot(db, log, interval=9999)
        worker.start()
        assert worker._thread.daemon is True
        worker._stop_event.set()

    def test_auto_save_fires(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        worker = persistence.PeriodicSnapshot(db, log, interval=0.05)
        worker.start()
        time.sleep(0.2)
        worker._stop_event.set()
        assert os.path.exists(tmp_snapshot)

    def test_stop_event_stops_thread(self, tmp_snapshot):
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        worker = persistence.PeriodicSnapshot(db, log, interval=9999)
        worker.start()
        worker._stop_event.set()
        worker._thread.join(timeout=2.0)
        assert not worker._thread.is_alive()


class TestRegisterShutdownHandler:
    def test_registers_sigterm_handler(self):
        import signal
        db, _ = make_fresh_db_with_one_card()
        log, _ = make_fresh_log_with_one_txn()
        worker = persistence.PeriodicSnapshot(db, log, interval=9999)
        persistence.register_shutdown_handler(worker)
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
