"""
CardRepository — implémentation DB-backed de CardDatabase (P1).
Actif uniquement lorsque DATABASE_URL est configuré.
Conserve la même interface que CardDatabase (in-memory) pour transparence.
"""
import logging
from datetime import datetime

from sqlalchemy import select

from database import get_session
from models.card import Card, CardDatabase, CardStatus, UNBLOCKABLE_STATUSES
from models.orm_models import CardORM

logger = logging.getLogger(__name__)


# ── Convertisseurs ORM ↔ domaine ──────────────────────────────────────────────

def _orm_to_card(row: CardORM) -> Card:
    from config import Config
    card = Card.__new__(Card)
    card.pan                    = row.pan
    card.expiry                 = row.expiry
    card.cardholder_name        = row.cardholder_name
    card.psn                    = row.psn or "00"
    card.status                 = row.status
    card.balance                = row.balance if row.balance is not None else 100000
    card.daily_limit            = row.daily_limit if row.daily_limit is not None else 500000
    card.daily_spent            = row.daily_spent if row.daily_spent is not None else 0
    card.last_reset_date        = row.last_reset_date or datetime.utcnow().date().isoformat()
    card.last_atc               = row.last_atc or 0
    card.created_at             = row.created_at or datetime.utcnow().isoformat()
    card.block_reason           = row.block_reason
    card.blocked_at             = row.blocked_at
    card.unblocked_at           = row.unblocked_at
    card.block_history          = row.block_history or []
    card.cb_scheme              = row.cb_scheme or "VISA"
    card.cb_brand               = row.cb_brand or "VISA CB"
    card.aid                    = row.aid
    card.contactless_cumul      = row.contactless_cumul or 0
    card.consecutive_offline    = row.consecutive_offline or 0
    card.last_contactless_reset = row.last_contactless_reset or datetime.utcnow().date().isoformat()
    card.pin_tries              = row.pin_tries or 0
    card.max_pin_tries          = row.max_pin_tries or 3
    card.pin_hash               = row.pin_hash

    def _hex_to_bytes(v, default):
        if v:
            try:
                return bytes.fromhex(v)
            except Exception:
                pass
        return default

    card.master_key_ac  = _hex_to_bytes(row.master_key_ac,  Config.MDK_AC)
    card.master_key_enc = _hex_to_bytes(row.master_key_enc, Config.MDK_ENC)
    card.master_key_mac = _hex_to_bytes(row.master_key_mac, Config.MDK_MAC)
    return card


def _card_to_orm(card: Card, row: CardORM | None = None) -> CardORM:
    row = row or CardORM()
    row.pan                    = card.pan
    row.expiry                 = card.expiry
    row.cardholder_name        = card.cardholder_name
    row.psn                    = card.psn
    row.status                 = card.status
    row.balance                = card.balance
    row.daily_limit            = card.daily_limit
    row.daily_spent            = card.daily_spent
    row.last_reset_date        = card.last_reset_date
    row.last_atc               = card.last_atc
    row.created_at             = card.created_at
    row.block_reason           = card.block_reason
    row.blocked_at             = card.blocked_at
    row.unblocked_at           = card.unblocked_at
    row.block_history          = card.block_history
    row.cb_scheme              = card.cb_scheme
    row.cb_brand               = card.cb_brand
    row.aid                    = card.aid
    row.contactless_cumul      = card.contactless_cumul
    row.consecutive_offline    = card.consecutive_offline
    row.last_contactless_reset = getattr(card, "last_contactless_reset",
                                          datetime.utcnow().date().isoformat())
    row.pin_tries              = card.pin_tries
    row.max_pin_tries          = card.max_pin_tries
    row.pin_hash               = card.pin_hash

    def _key_hex(v):
        if isinstance(v, bytes):
            return v.hex()
        return v or ""

    row.master_key_ac  = _key_hex(card.master_key_ac)
    row.master_key_enc = _key_hex(card.master_key_enc)
    row.master_key_mac = _key_hex(card.master_key_mac)
    return row


# ── Repository ────────────────────────────────────────────────────────────────

class DBCardDatabase(CardDatabase):
    """
    Implémentation PostgreSQL/SQLAlchemy de CardDatabase.
    Surcharge toutes les méthodes de stockage ; l'interface reste identique
    pour que le reste du code (server.py, emv/…) continue de fonctionner.
    """

    def __init__(self):
        # On n'appelle PAS super().__init__() pour éviter _load_defaults()
        # en mémoire — la DB est la seule source de vérité.
        self._blocked_list = set()   # cache local pour is_blocked()
        self._seed_defaults()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _seed_defaults(self):
        """Insère les cartes de test si elles n'existent pas encore en DB."""
        try:
            tmp = CardDatabase.__new__(CardDatabase)
            tmp._cards = {}
            tmp._blocked_list = set()
            CardDatabase._load_defaults(tmp)
            with get_session() as session:
                for card in tmp._cards.values():
                    if not session.get(CardORM, card.pan):
                        session.add(_card_to_orm(card))
            logger.info("Cartes de test vérifiées/insérées en base")
        except Exception as exc:
            logger.warning("Seed cartes de test ignoré : %s", exc)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get_card(self, pan: str) -> Card | None:
        pan = pan.replace(" ", "")
        try:
            with get_session() as session:
                row = session.get(CardORM, pan)
                return _orm_to_card(row) if row else None
        except Exception as exc:
            logger.error("get_card(%s): %s", pan[-4:], exc)
            return None

    def add_card(self, card: Card):
        try:
            with get_session() as session:
                existing = session.get(CardORM, card.pan)
                row = _card_to_orm(card, existing)
                session.merge(row)
        except Exception as exc:
            logger.error("add_card(%s): %s", card.pan[-4:], exc)

    def _save(self, card: Card):
        """Sauvegarde une carte modifiée."""
        self.add_card(card)

    # ── Blocage ───────────────────────────────────────────────────────────────

    def block_card(self, pan: str, reason: str = None) -> bool:
        pan = pan.replace(" ", "")
        card = self.get_card(pan)
        if not card:
            return False
        card.block_history.append({
            "action":          "BLOCKED",
            "reason":          reason or "Manuel",
            "at":              datetime.utcnow().isoformat(),
            "previous_status": card.status,
        })
        card.status       = CardStatus.BLOCKED
        card.block_reason = reason or "Bloquée manuellement"
        card.blocked_at   = datetime.utcnow().isoformat()
        self._save(card)
        self._blocked_list.add(pan)
        return True

    def unblock_card(self, pan: str, reason: str = None):
        pan = pan.replace(" ", "")
        card = self.get_card(pan)
        if not card:
            return False, "Carte introuvable"
        if card.status == CardStatus.LOST:
            return False, "Impossible de débloquer une carte déclarée perdue"
        if card.status == CardStatus.STOLEN:
            return False, "Impossible de débloquer une carte déclarée volée"
        if card.status == CardStatus.ACTIVE:
            return False, "La carte est déjà active"
        if card.status not in UNBLOCKABLE_STATUSES:
            return False, f"Statut '{card.status}' ne peut pas être débloqué via cette API"
        card.block_history.append({
            "action":          "UNBLOCKED",
            "reason":          reason or "Manuel",
            "at":              datetime.utcnow().isoformat(),
            "previous_status": card.status,
        })
        card.status       = CardStatus.ACTIVE
        card.block_reason = None
        card.unblocked_at = datetime.utcnow().isoformat()
        self._save(card)
        self._blocked_list.discard(pan)
        return True, "Carte débloquée avec succès"

    def is_blocked(self, pan: str) -> bool:
        pan = pan.replace(" ", "")
        card = self.get_card(pan)
        if not card:
            return False
        return card.status in (CardStatus.BLOCKED, CardStatus.LOST, CardStatus.STOLEN)

    # ── Lectures ─────────────────────────────────────────────────────────────

    def all_cards(self) -> list:
        try:
            with get_session() as session:
                rows = session.execute(select(CardORM)).scalars().all()
                return [_orm_to_card(r) for r in rows]
        except Exception as exc:
            logger.error("all_cards(): %s", exc)
            return []

    def update_atc(self, pan: str, atc: int):
        pan = pan.replace(" ", "")
        card = self.get_card(pan)
        if card:
            card.last_atc = atc
            self._save(card)

    def get_stats(self) -> dict:
        cards = self.all_cards()
        statuses: dict = {}
        schemes:  dict = {}
        for card in cards:
            statuses[card.status] = statuses.get(card.status, 0) + 1
            s = card.cb_scheme or "UNKNOWN"
            schemes[s] = schemes.get(s, 0) + 1
        blocked_count = sum(
            1 for c in cards
            if c.status in (CardStatus.BLOCKED, CardStatus.LOST, CardStatus.STOLEN)
        )
        return {
            "total_cards":      len(cards),
            "blocked_list_size": blocked_count,
            "by_status":        statuses,
            "by_cb_scheme":     schemes,
        }
