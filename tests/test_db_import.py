"""
Tests P2/P1 v1.10.0 — Import JSON → Base de données.
Couvre : import_snapshot_to_db (dry_run + réel SQLite), auto_recover, get_import_history.
Tests en mode SQLite in-memory pour isolation.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_snapshot(tmp_path):
    data = {
        "version": "1.10.0",
        "saved_at": "2026-05-03T10:00:00Z",
        "cards": [
            {
                "pan": "4111111111111111",
                "expiry": "2812",
                "cardholder_name": "JEAN DUPONT",
                "psn": "00",
                "status": "ACTIVE",
                "balance": 100000,
                "daily_limit": 300000,
                "daily_spent": 0,
                "last_reset_date": "2026-05-03",
                "last_atc": 5,
                "block_reason": None,
                "blocked_at": None,
                "block_history": [],
                "cb_scheme": "VISA",
                "cb_brand": "VISA",
                "aid": None,
                "contactless_cumul": 500,
                "consecutive_offline": 0,
                "pin_tries": 0,
            }
        ],
        "transactions": [
            {
                "id": "TXN-001",
                "rrn": "260503001",
                "pan": "4111111111111111",
                "amount": 5000,
                "currency": "978",
                "transaction_type": "00",
                "terminal_id": "TERM0001",
                "merchant_id": "MERCH001",
                "merchant_name": None,
                "atc": 1,
                "arqc": None,
                "arpc": None,
                "issuer_auth_data": None,
                "auth_code": "A00001",
                "status": "APPROVED",
                "response_code": "00",
                "decline_reason": None,
                "pos_entry_mode": "051",
                "amount_tier": "SMALL",
                "risk_level": "LOW",
                "auth_path": "ONLINE",
                "cb_scheme": "VISA",
                "cb_brand": "VISA",
                "cb_service_indicator": "01",
                "cb_sca_exemption": None,
                "cb_floor_limit": 0,
                "cb_is_contactless": False,
                "cb_response_code": None,
                "cb_decline_reason": None,
                "created_at": "2026-05-03T10:00:00Z",
                "processed_at": "2026-05-03T10:00:01Z",
            },
            {
                "id": "TXN-002",
                "rrn": "260503002",
                "pan": "5500000000000004",
                "amount": 12000,
                "currency": "978",
                "transaction_type": "00",
                "terminal_id": "TERM0002",
                "merchant_id": "MERCH002",
                "merchant_name": None,
                "atc": 2,
                "arqc": None, "arpc": None, "issuer_auth_data": None,
                "auth_code": "B00002",
                "status": "APPROVED",
                "response_code": "00",
                "decline_reason": None,
                "pos_entry_mode": "051",
                "amount_tier": "STANDARD",
                "risk_level": "LOW",
                "auth_path": "ONLINE",
                "cb_scheme": "MC",
                "cb_brand": "MC",
                "cb_service_indicator": "01",
                "cb_sca_exemption": None,
                "cb_floor_limit": 0,
                "cb_is_contactless": False,
                "cb_response_code": None,
                "cb_decline_reason": None,
                "created_at": "2026-05-03T10:01:00Z",
                "processed_at": "2026-05-03T10:01:01Z",
            },
        ],
    }
    path = str(tmp_path / "snapshot_test.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path, data


# ── Tests import_snapshot_to_db — erreurs précoces ────────────────────────────

class TestImportSnapshotErrors:
    def test_missing_file_returns_error(self):
        from db_import import import_snapshot_to_db
        result = import_snapshot_to_db("/nonexistent/snap.json")
        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_invalid_json_returns_error(self, tmp_path):
        bad = str(tmp_path / "bad.json")
        with open(bad, "w") as f:
            f.write("{not valid json}")
        from db_import import import_snapshot_to_db
        result = import_snapshot_to_db(bad)
        assert result["success"] is False

    def test_db_unavailable_returns_error(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        with patch("db_import.is_db_available", return_value=False):
            result = import_snapshot_to_db(path)
        assert result["success"] is False
        assert any("indisponible" in e for e in result["errors"])

    def test_result_has_metadata(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        with patch("db_import.is_db_available", return_value=False):
            result = import_snapshot_to_db(path)
        assert result["path"] == path
        assert result["snapshot_version"] == "1.10.0"
        assert result["nb_cards_in_file"] == 1
        assert result["nb_txns_in_file"] == 2


# ── Tests dry_run ─────────────────────────────────────────────────────────────

class TestImportDryRun:
    def test_dry_run_does_not_write_db(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        with patch("db_import.is_db_available", return_value=True):
            result = import_snapshot_to_db(path, dry_run=True)
        assert result["dry_run"] is True
        assert result["cards_inserted"] == 1
        assert result["txns_inserted"] == 2
        assert result["cards_updated"] == 0

    def test_dry_run_success(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        with patch("db_import.is_db_available", return_value=True):
            result = import_snapshot_to_db(path, dry_run=True)
        assert result["success"] is True

    def test_dry_run_has_timestamps(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        with patch("db_import.is_db_available", return_value=True):
            result = import_snapshot_to_db(path, dry_run=True)
        assert "started_at" in result
        assert "finished_at" in result


# ── Tests import réel avec SQLite in-memory ───────────────────────────────────

@pytest.fixture
def sqlite_session(tmp_path):
    """Crée une DB SQLite in-memory pour tests d'import."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import orm_models  # noqa — enregistre les modèles

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal


class TestImportToSQLite:
    def test_inserts_transaction(self, sample_snapshot, sqlite_session):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        from models.orm_models import TransactionORM

        sess_factory = sqlite_session
        session_ctx = MagicMock()

        def fake_get_session():
            from contextlib import contextmanager
            @contextmanager
            def ctx():
                s = sess_factory()
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise
                finally:
                    s.close()
            return ctx()

        with patch("db_import.is_db_available", return_value=True), \
             patch("db_import.get_session", side_effect=fake_get_session):
            result = import_snapshot_to_db(path)

        assert result["txns_inserted"] == 2
        assert result["txns_skipped"] == 0

    def test_skips_duplicate_transaction(self, sample_snapshot, sqlite_session):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        from models.orm_models import TransactionORM

        sess_factory = sqlite_session
        sessions_created = []

        def fake_get_session():
            from contextlib import contextmanager
            @contextmanager
            def ctx():
                s = sess_factory()
                sessions_created.append(s)
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise
                finally:
                    s.close()
            return ctx()

        with patch("db_import.is_db_available", return_value=True), \
             patch("db_import.get_session", side_effect=fake_get_session):
            # Premier import
            r1 = import_snapshot_to_db(path)
            # Second import — devrait skipper les doublons
            r2 = import_snapshot_to_db(path)

        assert r1["txns_inserted"] == 2
        assert r2["txns_skipped"] >= 2

    def test_inserts_card(self, sample_snapshot, sqlite_session):
        path, _ = sample_snapshot
        from db_import import import_snapshot_to_db
        from models.orm_models import CardORM

        sess_factory = sqlite_session

        def fake_get_session():
            from contextlib import contextmanager
            @contextmanager
            def ctx():
                s = sess_factory()
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise
                finally:
                    s.close()
            return ctx()

        with patch("db_import.is_db_available", return_value=True), \
             patch("db_import.get_session", side_effect=fake_get_session):
            result = import_snapshot_to_db(path)

        assert result["cards_inserted"] == 1
        assert result["cards_skipped"] == 0


# ── Tests auto_recover ────────────────────────────────────────────────────────

class TestAutoRecover:
    def test_no_snapshot_returns_failure(self):
        from db_import import auto_recover
        with patch("persistence.get_latest_snapshot_path", return_value=None), \
             patch("persistence.list_snapshots", return_value=[]):
            result = auto_recover()
        assert result["success"] is False

    def test_with_snapshot_calls_import(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import auto_recover
        with patch("db_import.import_snapshot_to_db",
                   return_value={"success": True, "cards_inserted": 1,
                                 "cards_updated": 0, "txns_inserted": 2,
                                 "errors": []}) as mock_import:
            result = auto_recover(snapshot_path=path)
        mock_import.assert_called_once_with(path)
        assert result["success"] is True

    def test_auto_discover_latest(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import auto_recover
        with patch("persistence.get_latest_snapshot_path", return_value=path), \
             patch("db_import.import_snapshot_to_db",
                   return_value={"success": True, "cards_inserted": 0,
                                 "cards_updated": 1, "txns_inserted": 2,
                                 "errors": []}) as mock_import:
            auto_recover()
        mock_import.assert_called_once_with(path)


# ── Tests get_import_history ──────────────────────────────────────────────────

class TestGetImportHistory:
    def test_returns_list(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import get_import_history
        entries = [{"filename": "snap.json", "path": path,
                    "saved_at": "2026-05-03T10:00:00Z",
                    "nb_cards": 1, "nb_txns": 2, "size_bytes": 1024}]
        with patch("persistence.list_snapshots", return_value=entries):
            result = get_import_history()
        assert len(result) == 1
        assert "importable" in result[0]
        assert "size_kb" in result[0]

    def test_importable_true_if_file_exists(self, sample_snapshot):
        path, _ = sample_snapshot
        from db_import import get_import_history
        entries = [{"filename": "snap.json", "path": path,
                    "saved_at": "2026-05-03T10:00:00Z",
                    "nb_cards": 1, "nb_txns": 2, "size_bytes": 2048}]
        with patch("persistence.list_snapshots", return_value=entries):
            result = get_import_history()
        assert result[0]["importable"] is True
        assert result[0]["size_kb"] == 2.0

    def test_importable_false_if_missing(self):
        from db_import import get_import_history
        entries = [{"filename": "missing.json", "path": "/nonexistent/file.json",
                    "saved_at": "2026-05-01T10:00:00Z",
                    "nb_cards": 0, "nb_txns": 0, "size_bytes": 0}]
        with patch("persistence.list_snapshots", return_value=entries):
            result = get_import_history()
        assert result[0]["importable"] is False

    def test_empty_history(self):
        from db_import import get_import_history
        with patch("persistence.list_snapshots", return_value=[]):
            result = get_import_history()
        assert result == []
