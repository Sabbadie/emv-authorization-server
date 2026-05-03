"""
Tests unitaires — models/card.py
Couvre : Card (is_expired, reset_daily_if_needed, can_spend, debit,
               update_contactless, reset_contactless, to_dict),
         CardDatabase (get_card, add_card, block_card, unblock_card,
                       is_blocked, update_atc, get_stats, all_cards)
"""

import pytest
from unittest.mock import patch
from datetime import datetime, date
from models.card import Card, CardStatus, CardDatabase, UNBLOCKABLE_STATUSES


def make_card(pan="9999000000000001", expiry="2812",
              status=CardStatus.ACTIVE, balance=100000,
              daily_limit=50000):
    return Card(
        pan=pan, expiry=expiry,
        cardholder_name="TEST USER",
        psn="01",
        status=status,
        balance=balance,
        daily_limit=daily_limit,
        cb_scheme="VISA", cb_brand="VISA CB",
    )


def make_fresh_db():
    db = CardDatabase.__new__(CardDatabase)
    db._cards = {}
    db._blocked_list = set()
    return db


class TestCardInit:
    def test_pan_spaces_stripped(self):
        card = Card("4111 1111 1111 1111", "2812", "TEST")
        assert " " not in card.pan

    def test_initial_status_active(self):
        card = make_card()
        assert card.status == CardStatus.ACTIVE

    def test_initial_daily_spent_zero(self):
        card = make_card()
        assert card.daily_spent == 0

    def test_initial_contactless_cumul_zero(self):
        card = make_card()
        assert card.contactless_cumul == 0

    def test_initial_consecutive_offline_zero(self):
        card = make_card()
        assert card.consecutive_offline == 0

    def test_initial_pin_tries_zero(self):
        card = make_card()
        assert card.pin_tries == 0

    def test_initial_block_reason_none(self):
        card = make_card()
        assert card.block_reason is None

    def test_has_master_keys(self):
        card = make_card()
        assert card.master_key_ac is not None
        assert len(card.master_key_ac) in (16, 24)


class TestCardIsExpired:
    def test_future_expiry_not_expired(self):
        card = make_card(expiry="3512")
        assert card.is_expired() is False

    def test_past_expiry_expired(self):
        card = make_card(expiry="2001")
        assert card.is_expired() is True

    def test_current_year_past_month_expired(self):
        now = datetime.utcnow()
        past_month = (now.month - 2) % 12 + 1
        exp = "{}{:02d}".format(str(now.year)[2:], past_month)
        if now.month >= 2:
            card = make_card(expiry=exp)
            assert card.is_expired() is True

    def test_invalid_expiry_returns_true(self):
        card = make_card(expiry="XXXX")
        assert card.is_expired() is True

    def test_empty_expiry_returns_true(self):
        card = make_card(expiry="")
        assert card.is_expired() is True

    def test_far_future_not_expired(self):
        card = make_card(expiry="9912")
        assert card.is_expired() is False


class TestCardResetDaily:
    def test_same_day_no_reset(self):
        card = make_card()
        card.daily_spent = 10000
        today = datetime.utcnow().date().isoformat()
        card.last_reset_date = today
        card.reset_daily_if_needed()
        assert card.daily_spent == 10000

    def test_different_day_resets_spent(self):
        card = make_card()
        card.daily_spent = 10000
        card.last_reset_date = "2000-01-01"
        card.reset_daily_if_needed()
        assert card.daily_spent == 0

    def test_different_day_resets_contactless(self):
        card = make_card()
        card.contactless_cumul = 5000
        card.consecutive_offline = 3
        card.last_reset_date = "2000-01-01"
        card.reset_daily_if_needed()
        assert card.contactless_cumul == 0
        assert card.consecutive_offline == 0

    def test_updates_last_reset_date(self):
        card = make_card()
        card.last_reset_date = "2000-01-01"
        card.reset_daily_if_needed()
        assert card.last_reset_date == datetime.utcnow().date().isoformat()


class TestCardCanSpend:
    def test_sufficient_balance_and_limit(self):
        card = make_card(balance=100000, daily_limit=50000)
        assert card.can_spend(5000) is True

    def test_insufficient_balance(self):
        card = make_card(balance=100, daily_limit=50000)
        assert card.can_spend(5000) is False

    def test_daily_limit_reached(self):
        card = make_card(balance=100000, daily_limit=5000)
        card.daily_spent = 5000
        assert card.can_spend(100) is False

    def test_exact_balance(self):
        card = make_card(balance=5000, daily_limit=50000)
        assert card.can_spend(5000) is True

    def test_exactly_over_balance(self):
        card = make_card(balance=4999, daily_limit=50000)
        assert card.can_spend(5000) is False

    def test_daily_limit_partial_remaining(self):
        card = make_card(balance=100000, daily_limit=10000)
        card.daily_spent = 7000
        assert card.can_spend(3000) is True

    def test_daily_limit_no_remaining(self):
        card = make_card(balance=100000, daily_limit=10000)
        card.daily_spent = 9000
        assert card.can_spend(2000) is False

    def test_zero_amount(self):
        card = make_card(balance=100000, daily_limit=50000)
        assert card.can_spend(0) is True


class TestCardDebit:
    def test_reduces_balance(self):
        card = make_card(balance=10000)
        card.debit(3000)
        assert card.balance == 7000

    def test_increases_daily_spent(self):
        card = make_card()
        card.debit(3000)
        assert card.daily_spent == 3000

    def test_cumulative_debit(self):
        card = make_card(balance=10000)
        card.debit(3000)
        card.debit(2000)
        assert card.balance == 5000
        assert card.daily_spent == 5000


class TestCardContactless:
    def test_update_increments_cumul(self):
        card = make_card()
        card.update_contactless(1000)
        assert card.contactless_cumul == 1000

    def test_update_increments_consecutive(self):
        card = make_card()
        card.update_contactless(1000)
        assert card.consecutive_offline == 1

    def test_update_cumulative(self):
        card = make_card()
        card.update_contactless(1000)
        card.update_contactless(2000)
        assert card.contactless_cumul == 3000
        assert card.consecutive_offline == 2

    def test_reset_zeros_cumul(self):
        card = make_card()
        card.contactless_cumul = 5000
        card.reset_contactless()
        assert card.contactless_cumul == 0

    def test_reset_zeros_consecutive(self):
        card = make_card()
        card.consecutive_offline = 3
        card.reset_contactless()
        assert card.consecutive_offline == 0


class TestCardToDict:
    def test_masked_pan(self):
        card = make_card(pan="4111111111111111")
        d = card.to_dict(masked=True)
        assert d["pan"].startswith("*")
        assert d["pan"].endswith("1111")

    def test_unmasked_pan(self):
        card = make_card(pan="4111111111111111")
        d = card.to_dict(masked=False)
        assert d["pan"] == "4111111111111111"

    def test_contains_required_fields(self):
        card = make_card()
        d = card.to_dict()
        required = [
            "pan", "expiry", "cardholder_name", "psn", "status",
            "balance", "daily_limit", "daily_spent", "last_atc",
            "cb_scheme", "cb_brand", "contactless_cumul",
            "consecutive_offline", "pin_tries",
        ]
        for key in required:
            assert key in d, f"Clé manquante : {key}"

    def test_balance_value(self):
        card = make_card(balance=75000)
        d = card.to_dict()
        assert d["balance"] == 75000

    def test_contactless_cumul_formatted(self):
        card = make_card()
        card.contactless_cumul = 1500
        d = card.to_dict()
        assert "contactless_cumul_formatted" in d
        assert d["contactless_cumul_formatted"] == "15.00"


class TestCardDatabase:
    def test_default_load_has_test_cards(self):
        db = CardDatabase()
        assert db.get_card("4111111111111111") is not None

    def test_get_card_existing(self):
        db = CardDatabase()
        card = db.get_card("4111111111111111")
        assert card is not None
        assert card.pan == "4111111111111111"

    def test_get_card_with_spaces(self):
        db = CardDatabase()
        card = db.get_card("4111 1111 1111 1111")
        assert card is not None

    def test_get_card_missing_returns_none(self):
        db = CardDatabase()
        assert db.get_card("0000000000000000") is None

    def test_add_card(self):
        db = make_fresh_db()
        card = make_card(pan="1234567890123456")
        db.add_card(card)
        assert db.get_card("1234567890123456") is not None

    def test_block_existing_card(self):
        db = CardDatabase()
        result = db.block_card("4111111111111111", reason="Test blocage")
        assert result is True
        card = db.get_card("4111111111111111")
        assert card.status == CardStatus.BLOCKED

    def test_block_sets_reason(self):
        db = CardDatabase()
        db.block_card("4111111111111111", reason="Fraude")
        card = db.get_card("4111111111111111")
        assert card.block_reason == "Fraude"

    def test_block_nonexistent_returns_false(self):
        db = CardDatabase()
        assert db.block_card("0000000000000000") is False

    def test_block_adds_to_blocked_list(self):
        db = CardDatabase()
        db.block_card("4111111111111111")
        assert db.is_blocked("4111111111111111") is True

    def test_unblock_blocked_card(self):
        db = CardDatabase()
        db.block_card("4111111111111111")
        success, msg = db.unblock_card("4111111111111111")
        assert success is True
        assert db.get_card("4111111111111111").status == CardStatus.ACTIVE

    def test_unblock_removes_from_blocked_list(self):
        db = CardDatabase()
        db.block_card("4111111111111111")
        db.unblock_card("4111111111111111")
        assert db.is_blocked("4111111111111111") is False

    def test_unblock_lost_fails(self):
        db = CardDatabase()
        db._cards["4111111111111111"].status = CardStatus.LOST
        success, msg = db.unblock_card("4111111111111111")
        assert success is False
        assert "perdue" in msg.lower()

    def test_unblock_stolen_fails(self):
        db = CardDatabase()
        db._cards["4111111111111111"].status = CardStatus.STOLEN
        success, msg = db.unblock_card("4111111111111111")
        assert success is False
        assert "volée" in msg.lower()

    def test_unblock_active_fails(self):
        db = CardDatabase()
        success, msg = db.unblock_card("4111111111111111")
        assert success is False

    def test_unblock_nonexistent_returns_error(self):
        db = CardDatabase()
        success, msg = db.unblock_card("0000000000000000")
        assert success is False

    def test_is_blocked_active_card(self):
        db = CardDatabase()
        assert db.is_blocked("4111111111111111") is False

    def test_is_blocked_blocked_card(self):
        db = CardDatabase()
        db.block_card("4111111111111111")
        assert db.is_blocked("4111111111111111") is True

    def test_is_blocked_unknown_pan(self):
        db = CardDatabase()
        assert db.is_blocked("0000000000000000") is False

    def test_update_atc(self):
        db = CardDatabase()
        db.update_atc("4111111111111111", 42)
        assert db.get_card("4111111111111111").last_atc == 42

    def test_update_atc_unknown_pan_no_error(self):
        db = CardDatabase()
        db.update_atc("0000000000000000", 1)

    def test_all_cards_returns_list(self):
        db = CardDatabase()
        cards = db.all_cards()
        assert isinstance(cards, list)
        assert len(cards) >= 7

    def test_get_stats_structure(self):
        db = CardDatabase()
        stats = db.get_stats()
        assert "total_cards" in stats
        assert "blocked_list_size" in stats
        assert "by_status" in stats
        assert "by_cb_scheme" in stats

    def test_get_stats_total(self):
        db = CardDatabase()
        stats = db.get_stats()
        assert stats["total_cards"] >= 7

    def test_unblockable_statuses_constant(self):
        assert CardStatus.BLOCKED in UNBLOCKABLE_STATUSES
        assert CardStatus.RESTRICTED in UNBLOCKABLE_STATUSES
        assert CardStatus.LOST not in UNBLOCKABLE_STATUSES
        assert CardStatus.ACTIVE not in UNBLOCKABLE_STATUSES
