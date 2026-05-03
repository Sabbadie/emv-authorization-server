"""
Tests unitaires — Persistance P1 : database.py + ORM models (T008).
S'exécutent sans PostgreSQL (SQLite in-memory) pour CI.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.orm_models import Base, CardORM, TransactionORM
from database import db_health


# ═══════════════════════════════════════════════════════════════════════════════
# Fixture SQLite in-memory (CI sans Docker)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def sqlite_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def sqlite_session(sqlite_engine):
    Session = sessionmaker(bind=sqlite_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ORM — CardORM
# ═══════════════════════════════════════════════════════════════════════════════

class TestCardORM:

    def test_create_card(self, sqlite_session):
        card = CardORM(
            pan="4970101122334455",
            expiry="2812",
            status="ACTIVE",
            daily_limit=100000,
        )
        sqlite_session.add(card)
        sqlite_session.commit()
        fetched = sqlite_session.query(CardORM).filter_by(pan="4970101122334455").first()
        assert fetched is not None
        assert fetched.status == "ACTIVE"

    def test_card_default_values(self, sqlite_session):
        card = CardORM(pan="4970000000005678", expiry="2812", status="ACTIVE")
        sqlite_session.add(card)
        sqlite_session.commit()
        fetched = sqlite_session.query(CardORM).filter_by(pan="4970000000005678").first()
        assert fetched.daily_spent == 0
        assert fetched.contactless_cumul == 0
        assert fetched.pin_tries == 0

    def test_update_card_status(self, sqlite_session):
        card = CardORM(pan="4970000000009999", expiry="2812", status="ACTIVE")
        sqlite_session.add(card)
        sqlite_session.commit()
        card.status = "BLOCKED"
        sqlite_session.commit()
        fetched = sqlite_session.query(CardORM).filter_by(pan="4970000000009999").first()
        assert fetched.status == "BLOCKED"

    def test_pan_unique_constraint(self, sqlite_session):
        from sqlalchemy.exc import IntegrityError
        c1 = CardORM(pan="4970111122223333", expiry="2812", status="ACTIVE")
        c2 = CardORM(pan="4970111122223333", expiry="2812", status="ACTIVE")
        sqlite_session.add(c1)
        sqlite_session.commit()
        sqlite_session.add(c2)
        with pytest.raises(IntegrityError):
            sqlite_session.commit()
        sqlite_session.rollback()


# ═══════════════════════════════════════════════════════════════════════════════
# ORM — TransactionORM
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransactionORM:

    def test_create_transaction(self, sqlite_session):
        txn = TransactionORM(
            id="txn-test-001",
            pan="4970101122334455",
            amount=5000,
            currency="978",
            status="APPROVED",
            response_code="00",
        )
        sqlite_session.add(txn)
        sqlite_session.commit()
        fetched = sqlite_session.query(TransactionORM).filter_by(id="txn-test-001").first()
        assert fetched is not None
        assert fetched.status == "APPROVED"
        assert fetched.amount == 5000

    def test_transaction_events_json(self, sqlite_session):
        events = [{"stage": "AUTH", "level": "INFO", "msg": "ok"}]
        txn = TransactionORM(
            id="txn-test-002",
            pan="4970101122334455",
            amount=1000,
            currency="978",
            status="DECLINED",
            response_code="51",
            events=events,
        )
        sqlite_session.add(txn)
        sqlite_session.commit()
        fetched = sqlite_session.query(TransactionORM).filter_by(id="txn-test-002").first()
        assert isinstance(fetched.events, list)
        assert fetched.events[0]["stage"] == "AUTH"


# ═══════════════════════════════════════════════════════════════════════════════
# db_health
# ═══════════════════════════════════════════════════════════════════════════════

class TestDbHealth:

    def test_returns_dict(self):
        result = db_health()
        assert isinstance(result, dict)

    def test_has_available_key(self):
        result = db_health()
        assert "available" in result

    def test_available_is_bool(self):
        result = db_health()
        assert isinstance(result["available"], bool)

    def test_has_mode_key(self):
        result = db_health()
        assert "mode" in result

    def test_mode_is_string(self):
        result = db_health()
        assert isinstance(result["mode"], str)
