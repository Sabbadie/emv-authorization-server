"""
Fixtures partagées pour la suite de tests EMV Authorization Server.
"""

import pytest
from models.card import Card, CardStatus, CardDatabase
from models.transaction import Transaction, TransactionLog, TransactionStatus


CVK1 = bytes.fromhex("0123456789ABCDEF")
CVK2 = bytes.fromhex("FEDCBA9876543210")
MDK   = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")

TEST_PAN        = "4111111111111111"
TEST_EXPIRY     = "2812"
TEST_BLOCKED_PAN = "4000000000000028"
TEST_EXPIRED_PAN = "4000000000000010"
TEST_INSUF_PAN   = "4000000000000036"


@pytest.fixture
def cvk_pair():
    return CVK1, CVK2


@pytest.fixture
def mdk():
    return MDK


@pytest.fixture
def fresh_card():
    return Card(
        pan="9999000000000001",
        expiry="2812",
        cardholder_name="TEST USER",
        psn="01",
        status=CardStatus.ACTIVE,
        balance=500000,
        daily_limit=200000,
        cb_scheme="VISA",
        cb_brand="VISA CB",
    )


@pytest.fixture
def fresh_card_db(fresh_card):
    db = CardDatabase.__new__(CardDatabase)
    db._cards = {}
    db._blocked_list = set()
    db._cards[fresh_card.pan] = fresh_card
    return db


@pytest.fixture
def fresh_transaction_log():
    return TransactionLog()


@pytest.fixture
def sample_transaction():
    txn = Transaction(
        pan="4111111111111111",
        amount=5000,
        currency="978",
        transaction_type="00",
        terminal_id="TERM0001",
        merchant_id="MERCH001",
        merchant_name="TEST SHOP",
        pos_entry_mode="051",
    )
    return txn


@pytest.fixture
def approved_transaction(sample_transaction):
    sample_transaction.approve("123456")
    sample_transaction.amount_tier = "STANDARD"
    sample_transaction.risk_level = "MEDIUM"
    sample_transaction.auth_path = "ONLINE"
    sample_transaction.cb_scheme = "VISA"
    sample_transaction.cb_brand = "VISA CB"
    sample_transaction.cb_service_indicator = "02"
    sample_transaction.cb_sca_exemption = "LVP"
    sample_transaction.cb_floor_limit = 3000
    sample_transaction.cb_is_contactless = False
    sample_transaction.cb_response_code = "00"
    return sample_transaction


@pytest.fixture
def client():
    """Flask test client."""
    from server import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


SIMPLE_EMV_HEX = (
    "9F02060000000050009F03060000000000009F1A020250"
    "950500000000009A032601019C0100"
    "9F370412345678"
    "9F360200059F2608AABBCCDD11223344"
    "9F270140"
)
