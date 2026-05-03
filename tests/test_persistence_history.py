"""
Tests P2 v1.10.0 — Historique JSON 7 jours.
Couvre : rotation, index, list_snapshots, cleanup, save/load.
"""

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dirs(tmp_path):
    snap_file = str(tmp_path / "snapshot.json")
    snap_dir  = str(tmp_path / "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    return snap_file, snap_dir, tmp_path


def make_card_db(cards=None):
    db = MagicMock()
    card = MagicMock()
    card.pan = "4111111111111111"
    card.expiry = "2812"
    card.cardholder_name = "TEST USER"
    card.psn = "00"
    card.status = "ACTIVE"
    card.balance = 100000
    card.daily_limit = 300000
    card.daily_spent = 0
    card.last_reset_date = "2026-05-03"
    card.last_atc = 0
    card.block_reason = None
    card.blocked_at = None
    card.unblocked_at = None
    card.block_history = []
    card.cb_scheme = "VISA"
    card.cb_brand = "VISA"
    card.aid = None
    card.contactless_cumul = 0
    card.consecutive_offline = 0
    card.last_contactless_reset = None
    card.pin_tries = 0
    db.all_cards.return_value = cards or [card]
    return db


def make_txn_log(txns=None):
    log = MagicMock()
    txn = MagicMock()
    txn.id = "TXN-001"
    txn.rrn = "260503001"
    txn.pan = "4111111111111111"
    txn.amount = 5000
    txn.currency = "978"
    txn.transaction_type = "00"
    txn.terminal_id = "TERM0001"
    txn.merchant_id = "MERCH001"
    txn.merchant_name = None
    txn.atc = 1
    txn.arqc = None
    txn.arpc = None
    txn.issuer_auth_data = None
    txn.auth_code = "A00001"
    txn.status = "APPROVED"
    txn.response_code = "00"
    txn.decline_reason = None
    txn.pos_entry_mode = "051"
    txn.amount_tier = "SMALL"
    txn.risk_level = "LOW"
    txn.auth_path = "ONLINE"
    txn.cb_scheme = "VISA"
    txn.cb_brand = "VISA"
    txn.cb_service_indicator = "01"
    txn.cb_sca_exemption = None
    txn.cb_floor_limit = 0
    txn.cb_is_contactless = False
    txn.cb_response_code = None
    txn.cb_decline_reason = None
    txn.created_at = "2026-05-03T10:00:00Z"
    txn.processed_at = "2026-05-03T10:00:01Z"
    log.get_all.return_value = txns or [txn]
    return log


# ── Tests _build_snapshot_data ────────────────────────────────────────────────

class TestBuildSnapshotData:
    def test_returns_dict_with_version(self):
        import persistence
        card_db = make_card_db()
        txn_log = make_txn_log()
        snap = persistence._build_snapshot_data(card_db, txn_log)
        assert snap["version"] == "1.10.0"

    def test_has_saved_at(self):
        import persistence
        snap = persistence._build_snapshot_data(make_card_db(), make_txn_log())
        assert "saved_at" in snap
        assert snap["saved_at"].endswith("Z")

    def test_cards_serialized(self):
        import persistence
        snap = persistence._build_snapshot_data(make_card_db(), make_txn_log())
        assert len(snap["cards"]) == 1
        assert snap["cards"][0]["pan"] == "4111111111111111"

    def test_transactions_serialized(self):
        import persistence
        snap = persistence._build_snapshot_data(make_card_db(), make_txn_log())
        assert len(snap["transactions"]) == 1
        assert snap["transactions"][0]["id"] == "TXN-001"

    def test_empty_state(self):
        import persistence
        db = MagicMock(); db.all_cards.return_value = []
        log = MagicMock(); log.get_all.return_value = []
        snap = persistence._build_snapshot_data(db, log)
        assert snap["cards"] == []
        assert snap["transactions"] == []


# ── Tests save_snapshot + historique ─────────────────────────────────────────

class TestSaveSnapshotHistory:
    def test_saves_main_file(self, tmp_dirs):
        snap_file, snap_dir, _ = tmp_dirs
        import persistence as p
        with patch.object(p, "SNAPSHOT_FILE", snap_file), \
             patch.object(p, "SNAPSHOT_DIR",  snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", os.path.join(snap_dir, "index.json")):
            result = p.save_snapshot(make_card_db(), make_txn_log())
        assert result is True
        assert os.path.exists(snap_file)

    def test_saves_timestamped_file(self, tmp_dirs):
        snap_file, snap_dir, _ = tmp_dirs
        import persistence as p
        with patch.object(p, "SNAPSHOT_FILE", snap_file), \
             patch.object(p, "SNAPSHOT_DIR",  snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", os.path.join(snap_dir, "index.json")):
            p.save_snapshot(make_card_db(), make_txn_log())
        hist_files = [f for f in os.listdir(snap_dir)
                      if f.startswith("snapshot_") and f.endswith(".json")
                      and f != "index.json"]
        assert len(hist_files) == 1

    def test_timestamped_file_content_valid(self, tmp_dirs):
        snap_file, snap_dir, _ = tmp_dirs
        import persistence as p
        with patch.object(p, "SNAPSHOT_FILE", snap_file), \
             patch.object(p, "SNAPSHOT_DIR",  snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", os.path.join(snap_dir, "index.json")):
            p.save_snapshot(make_card_db(), make_txn_log())
        hist_files = [f for f in os.listdir(snap_dir)
                      if f.startswith("snapshot_") and not f == "index.json"]
        with open(os.path.join(snap_dir, hist_files[0])) as f:
            data = json.load(f)
        assert data["version"] == "1.10.0"
        assert len(data["cards"]) == 1

    def test_index_created(self, tmp_dirs):
        snap_file, snap_dir, _ = tmp_dirs
        import persistence as p
        index_file = os.path.join(snap_dir, "index.json")
        with patch.object(p, "SNAPSHOT_FILE", snap_file), \
             patch.object(p, "SNAPSHOT_DIR",  snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", index_file):
            p.save_snapshot(make_card_db(), make_txn_log())
        assert os.path.exists(index_file)
        with open(index_file) as f:
            idx = json.load(f)
        assert len(idx["snapshots"]) == 1
        assert idx["snapshots"][0]["nb_cards"] == 1

    def test_multiple_saves_accumulate_in_index(self, tmp_dirs):
        snap_file, snap_dir, _ = tmp_dirs
        import persistence as p
        index_file = os.path.join(snap_dir, "index.json")
        with patch.object(p, "SNAPSHOT_FILE", snap_file), \
             patch.object(p, "SNAPSHOT_DIR",  snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", index_file):
            p.save_snapshot(make_card_db(), make_txn_log())
            time.sleep(1.1)
            p.save_snapshot(make_card_db(), make_txn_log())
        with open(index_file) as f:
            idx = json.load(f)
        assert len(idx["snapshots"]) == 2

    def test_returns_false_on_error(self):
        import persistence as p
        with patch.object(p, "SNAPSHOT_FILE", "/nonexistent/dir/snapshot.json"), \
             patch.object(p, "SNAPSHOT_DIR",  "/nonexistent/dir/snapshots"), \
             patch.object(p, "_ensure_dirs", side_effect=OSError("disk error")):
            result = p.save_snapshot(make_card_db(), make_txn_log())
        assert result is False


# ── Tests cleanup_old_snapshots ───────────────────────────────────────────────

class TestCleanupOldSnapshots:
    def _make_old_entry(self, snap_dir, days_ago):
        ts = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y%m%d_%H%M%S")
        fname = "snapshot_{}.json".format(ts)
        fpath = os.path.join(snap_dir, fname)
        with open(fpath, "w") as f:
            json.dump({"version": "1.10.0", "saved_at": (datetime.utcnow() - timedelta(days=days_ago)).isoformat() + "Z",
                       "cards": [], "transactions": []}, f)
        return fname, fpath

    def test_old_snapshots_removed(self, tmp_dirs):
        _, snap_dir, _ = tmp_dirs
        import persistence as p
        index_file = os.path.join(snap_dir, "index.json")
        fname, fpath = self._make_old_entry(snap_dir, days_ago=10)
        idx = {"snapshots": [{"filename": fname, "path": fpath,
                               "saved_at": (datetime.utcnow() - timedelta(days=10)).isoformat() + "Z",
                               "nb_cards": 0, "nb_txns": 0, "size_bytes": 100}],
               "updated_at": None}
        with open(index_file, "w") as f:
            json.dump(idx, f)
        with patch.object(p, "SNAPSHOT_DIR", snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", index_file), \
             patch.object(p, "SNAPSHOT_RETENTION", 7):
            removed = p.cleanup_old_snapshots()
        assert removed == 1
        assert not os.path.exists(fpath)

    def test_recent_snapshots_kept(self, tmp_dirs):
        _, snap_dir, _ = tmp_dirs
        import persistence as p
        index_file = os.path.join(snap_dir, "index.json")
        fname, fpath = self._make_old_entry(snap_dir, days_ago=3)
        idx = {"snapshots": [{"filename": fname, "path": fpath,
                               "saved_at": (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z",
                               "nb_cards": 0, "nb_txns": 0, "size_bytes": 100}],
               "updated_at": None}
        with open(index_file, "w") as f:
            json.dump(idx, f)
        with patch.object(p, "SNAPSHOT_DIR", snap_dir), \
             patch.object(p, "SNAPSHOT_INDEX_FILE", index_file), \
             patch.object(p, "SNAPSHOT_RETENTION", 7):
            removed = p.cleanup_old_snapshots()
        assert removed == 0
        assert os.path.exists(fpath)

    def test_no_dir_returns_zero(self):
        import persistence as p
        with patch.object(p, "SNAPSHOT_DIR", "/nonexistent/dir/snapshots"):
            assert p.cleanup_old_snapshots() == 0


# ── Tests list_snapshots ──────────────────────────────────────────────────────

class TestListSnapshots:
    def test_returns_index_entries(self, tmp_dirs):
        snap_file, snap_dir, _ = tmp_dirs
        import persistence as p
        index_file = os.path.join(snap_dir, "index.json")
        idx = {"snapshots": [{"filename": "snapshot_20260503_120000.json",
                               "saved_at": "2026-05-03T12:00:00Z",
                               "nb_cards": 2, "nb_txns": 5}]}
        with open(index_file, "w") as f:
            json.dump(idx, f)
        with patch.object(p, "SNAPSHOT_INDEX_FILE", index_file), \
             patch.object(p, "SNAPSHOT_DIR", snap_dir):
            entries = p.list_snapshots()
        assert len(entries) == 1
        assert entries[0]["nb_cards"] == 2

    def test_empty_dir_returns_empty(self, tmp_dirs):
        _, snap_dir, _ = tmp_dirs
        import persistence as p
        with patch.object(p, "SNAPSHOT_INDEX_FILE", os.path.join(snap_dir, "noindex.json")), \
             patch.object(p, "SNAPSHOT_DIR", snap_dir):
            entries = p.list_snapshots()
        assert entries == []


# ── Tests load_snapshot avec path ─────────────────────────────────────────────

class TestLoadSnapshotPath:
    def test_load_from_specific_path(self, tmp_dirs, tmp_path):
        snap_file, _, _ = tmp_dirs
        snap_data = {
            "version": "1.10.0",
            "saved_at": "2026-05-01T10:00:00Z",
            "cards": [{"pan": "4111111111111111", "balance": 80000, "status": "ACTIVE",
                       "daily_spent": 0, "last_reset_date": "2026-05-01", "last_atc": 0,
                       "block_reason": None, "blocked_at": None, "unblocked_at": None,
                       "block_history": [], "contactless_cumul": 0, "consecutive_offline": 0,
                       "pin_tries": 0}],
            "transactions": [],
        }
        specific = str(tmp_path / "specific_snap.json")
        with open(specific, "w") as f:
            json.dump(snap_data, f)
        import persistence as p
        card = MagicMock(); card.pan = "4111111111111111"
        card_db = MagicMock(); card_db.get_card.return_value = card
        txn_log = MagicMock(); txn_log.add = MagicMock()
        result = p.load_snapshot(card_db, txn_log, path=specific)
        assert result is True
        assert card.balance == 80000

    def test_load_missing_path_returns_false(self, tmp_dirs):
        import persistence as p
        card_db = MagicMock(); txn_log = MagicMock()
        result = p.load_snapshot(card_db, txn_log, path="/nonexistent/file.json")
        assert result is False
