"""
Card data model for the EMV Authorization Server.
Manages cardholder and card account data in memory (production would use a DB).
"""

import json
import os
import time
from datetime import datetime


class CardStatus:
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    LOST = "LOST"
    STOLEN = "STOLEN"
    RESTRICTED = "RESTRICTED"


class Card:
    def __init__(self, pan, expiry, cardholder_name, psn="00",
                 status=CardStatus.ACTIVE, balance=100000,
                 daily_limit=500000, pin_hash=None,
                 master_key_ac=None, master_key_enc=None, master_key_mac=None):
        self.pan = pan.replace(" ", "")
        self.expiry = expiry
        self.cardholder_name = cardholder_name
        self.psn = psn
        self.status = status
        self.balance = balance
        self.daily_limit = daily_limit
        self.pin_hash = pin_hash

        from config import Config
        self.master_key_ac = master_key_ac or Config.MDK_AC
        self.master_key_enc = master_key_enc or Config.MDK_ENC
        self.master_key_mac = master_key_mac or Config.MDK_MAC

        self.daily_spent = 0
        self.last_reset_date = datetime.utcnow().date().isoformat()
        self.last_atc = 0
        self.transactions = []
        self.created_at = datetime.utcnow().isoformat()

    def is_expired(self):
        try:
            year = int("20" + self.expiry[:2])
            month = int(self.expiry[2:4])
            now = datetime.utcnow()
            return (year < now.year) or (year == now.year and month < now.month)
        except Exception:
            return True

    def reset_daily_if_needed(self):
        today = datetime.utcnow().date().isoformat()
        if self.last_reset_date != today:
            self.daily_spent = 0
            self.last_reset_date = today

    def can_spend(self, amount):
        self.reset_daily_if_needed()
        return self.balance >= amount and (self.daily_spent + amount) <= self.daily_limit

    def debit(self, amount):
        self.balance -= amount
        self.daily_spent += amount

    def to_dict(self, masked=True):
        pan_display = "*" * (len(self.pan) - 4) + self.pan[-4:] if masked else self.pan
        return {
            "pan": pan_display,
            "expiry": self.expiry,
            "cardholder_name": self.cardholder_name,
            "psn": self.psn,
            "status": self.status,
            "balance": self.balance,
            "daily_limit": self.daily_limit,
            "daily_spent": self.daily_spent,
            "last_atc": self.last_atc,
            "created_at": self.created_at,
        }


class CardDatabase:
    def __init__(self):
        self._cards = {}
        self._blocked_list = set()
        self._load_defaults()

    def _load_defaults(self):
        test_cards = [
            Card(
                pan="4111111111111111",
                expiry="2812",
                cardholder_name="JEAN DUPONT",
                psn="01",
                status=CardStatus.ACTIVE,
                balance=500000,
                daily_limit=200000,
            ),
            Card(
                pan="5500000000000004",
                expiry="2912",
                cardholder_name="MARIE MARTIN",
                psn="01",
                status=CardStatus.ACTIVE,
                balance=1000000,
                daily_limit=500000,
            ),
            Card(
                pan="4000000000000002",
                expiry="2712",
                cardholder_name="AHMED BENALI",
                psn="01",
                status=CardStatus.ACTIVE,
                balance=250000,
                daily_limit=100000,
            ),
            Card(
                pan="4000000000000010",
                expiry="2112",
                cardholder_name="TEST EXPIRED",
                psn="01",
                status=CardStatus.ACTIVE,
                balance=100000,
                daily_limit=50000,
            ),
            Card(
                pan="4000000000000028",
                expiry="2812",
                cardholder_name="TEST BLOCKED",
                psn="01",
                status=CardStatus.BLOCKED,
                balance=100000,
                daily_limit=50000,
            ),
            Card(
                pan="4000000000000036",
                expiry="2812",
                cardholder_name="TEST INSUFFICIENT",
                psn="01",
                status=CardStatus.ACTIVE,
                balance=100,
                daily_limit=50000,
            ),
        ]
        for card in test_cards:
            self._cards[card.pan] = card

    def get_card(self, pan):
        pan = pan.replace(" ", "")
        return self._cards.get(pan)

    def add_card(self, card):
        self._cards[card.pan] = card

    def block_card(self, pan):
        pan = pan.replace(" ", "")
        card = self._cards.get(pan)
        if card:
            card.status = CardStatus.BLOCKED
            self._blocked_list.add(pan)
            return True
        return False

    def is_blocked(self, pan):
        pan = pan.replace(" ", "")
        return pan in self._blocked_list or (
            pan in self._cards and self._cards[pan].status in
            [CardStatus.BLOCKED, CardStatus.LOST, CardStatus.STOLEN])

    def all_cards(self):
        return list(self._cards.values())

    def update_atc(self, pan, atc):
        card = self.get_card(pan)
        if card:
            card.last_atc = atc

    def get_stats(self):
        statuses = {}
        for card in self._cards.values():
            statuses[card.status] = statuses.get(card.status, 0) + 1
        return {
            "total_cards": len(self._cards),
            "blocked_list_size": len(self._blocked_list),
            "by_status": statuses,
        }


card_db = CardDatabase()
