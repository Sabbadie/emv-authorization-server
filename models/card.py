"""
Card data model — avec champs GIE CB (sans contact, cumul offline, type CB).
"""

from datetime import datetime


class CardStatus:
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    LOST = "LOST"
    STOLEN = "STOLEN"
    RESTRICTED = "RESTRICTED"


UNBLOCKABLE_STATUSES = {CardStatus.BLOCKED, CardStatus.RESTRICTED}


class Card:
    def __init__(self, pan, expiry, cardholder_name, psn="00",
                 status=CardStatus.ACTIVE, balance=100000,
                 daily_limit=500000, pin_hash=None,
                 master_key_ac=None, master_key_enc=None, master_key_mac=None,
                 cb_scheme="VISA", cb_brand="VISA CB", aid=None):
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
        self.created_at = datetime.utcnow().isoformat()
        self.block_reason = None
        self.blocked_at = None
        self.unblocked_at = None
        self.block_history = []

        # Champs GIE CB
        self.cb_scheme = cb_scheme
        self.cb_brand = cb_brand
        self.aid = aid
        self.contactless_cumul = 0
        self.consecutive_offline = 0
        self.last_contactless_reset = datetime.utcnow().date().isoformat()
        self.pin_tries = 0
        self.max_pin_tries = 3

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
            self.consecutive_offline = 0
            self.contactless_cumul = 0
            self.last_contactless_reset = today

    def can_spend(self, amount):
        self.reset_daily_if_needed()
        return self.balance >= amount and (self.daily_spent + amount) <= self.daily_limit

    def debit(self, amount):
        self.balance -= amount
        self.daily_spent += amount

    def update_contactless(self, amount):
        """Met à jour les compteurs sans contact CB."""
        self.contactless_cumul += amount
        self.consecutive_offline += 1

    def reset_contactless(self):
        """Remet à zéro les compteurs sans contact (après transaction en ligne)."""
        self.contactless_cumul = 0
        self.consecutive_offline = 0

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
            "block_reason": self.block_reason,
            "blocked_at": self.blocked_at,
            "unblocked_at": self.unblocked_at,
            "cb_scheme": self.cb_scheme,
            "cb_brand": self.cb_brand,
            "aid": self.aid,
            "contactless_cumul": self.contactless_cumul,
            "contactless_cumul_formatted": "{:.2f}".format(self.contactless_cumul / 100),
            "consecutive_offline": self.consecutive_offline,
            "pin_tries": self.pin_tries,
        }


class CardDatabase:
    def __init__(self):
        self._cards = {}
        self._blocked_list = set()
        self._load_defaults()

    def _load_defaults(self):
        from emv.giecb import identify_card
        test_cards = [
            Card(pan="4111111111111111", expiry="2812", cardholder_name="JEAN DUPONT",
                 psn="01", status=CardStatus.ACTIVE, balance=500000, daily_limit=200000,
                 cb_scheme="VISA", cb_brand="VISA CB", aid="A0000000031010"),
            Card(pan="5500000000000004", expiry="2912", cardholder_name="MARIE MARTIN",
                 psn="01", status=CardStatus.ACTIVE, balance=1000000, daily_limit=500000,
                 cb_scheme="MC", cb_brand="MC CB", aid="A0000000041010"),
            Card(pan="4000000000000002", expiry="2712", cardholder_name="AHMED BENALI",
                 psn="01", status=CardStatus.ACTIVE, balance=250000, daily_limit=100000,
                 cb_scheme="VISA", cb_brand="VISA CB", aid="A0000000031010"),
            Card(pan="4000000000000010", expiry="2112", cardholder_name="TEST EXPIRED",
                 psn="01", status=CardStatus.ACTIVE, balance=100000, daily_limit=50000,
                 cb_scheme="VISA", cb_brand="VISA CB"),
            Card(pan="4000000000000028", expiry="2812", cardholder_name="TEST BLOCKED",
                 psn="01", status=CardStatus.BLOCKED, balance=100000, daily_limit=50000,
                 cb_scheme="VISA", cb_brand="VISA CB"),
            Card(pan="4000000000000036", expiry="2812", cardholder_name="TEST INSUFFICIENT",
                 psn="01", status=CardStatus.ACTIVE, balance=100, daily_limit=50000,
                 cb_scheme="VISA", cb_brand="VISA CB"),
            Card(pan="4970100000000154", expiry="2812", cardholder_name="CB NATIVE TEST",
                 psn="01", status=CardStatus.ACTIVE, balance=300000, daily_limit=150000,
                 cb_scheme="CB", cb_brand="CB", aid="A0000000421010"),
        ]
        for card in test_cards:
            self._cards[card.pan] = card

    def get_card(self, pan):
        return self._cards.get(pan.replace(" ", ""))

    def add_card(self, card):
        self._cards[card.pan] = card

    def block_card(self, pan, reason=None):
        pan = pan.replace(" ", "")
        card = self._cards.get(pan)
        if card:
            card.block_history.append({
                "action": "BLOCKED",
                "reason": reason or "Manuel",
                "at": datetime.utcnow().isoformat(),
                "previous_status": card.status,
            })
            card.status = CardStatus.BLOCKED
            card.block_reason = reason or "Bloquée manuellement"
            card.blocked_at = datetime.utcnow().isoformat()
            self._blocked_list.add(pan)
            return True
        return False

    def unblock_card(self, pan, reason=None):
        """Débloque une carte bloquée ou restreinte."""
        pan = pan.replace(" ", "")
        card = self._cards.get(pan)
        if not card:
            return False, "Carte introuvable"
        if card.status == CardStatus.LOST:
            return False, "Impossible de débloquer une carte déclarée perdue"
        if card.status == CardStatus.STOLEN:
            return False, "Impossible de débloquer une carte déclarée volée"
        if card.status == CardStatus.ACTIVE:
            return False, "La carte est déjà active"
        if card.status not in UNBLOCKABLE_STATUSES:
            return False, "Statut '{}' ne peut pas être débloqué via cette API".format(card.status)

        card.block_history.append({
            "action": "UNBLOCKED",
            "reason": reason or "Manuel",
            "at": datetime.utcnow().isoformat(),
            "previous_status": card.status,
        })
        card.status = CardStatus.ACTIVE
        card.block_reason = None
        card.unblocked_at = datetime.utcnow().isoformat()
        self._blocked_list.discard(pan)
        return True, "Carte débloquée avec succès"

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
        schemes = {}
        for card in self._cards.values():
            statuses[card.status] = statuses.get(card.status, 0) + 1
            s = card.cb_scheme or "UNKNOWN"
            schemes[s] = schemes.get(s, 0) + 1
        return {
            "total_cards": len(self._cards),
            "blocked_list_size": len(self._blocked_list),
            "by_status": statuses,
            "by_cb_scheme": schemes,
        }



class _CardDBProxy:
    """
    Proxy transparent vers l'implémentation active (in-memory ou DB-backed).
    Permet de permuter l'implémentation sans changer les références existantes.
    """
    def __init__(self, impl):
        object.__setattr__(self, "_impl", impl)

    def _swap(self, new_impl):
        object.__setattr__(self, "_impl", new_impl)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_impl"), name)

    def __setattr__(self, name, value):
        if name == "_impl":
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_impl"), name, value)


card_db = _CardDBProxy(CardDatabase())
