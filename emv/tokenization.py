"""
Tokenisation HCE / NFC — CB-PAY / Wallet — C3
==============================================
Simule un Token Service Provider (TSP) CB.

Un Token est un PAN de substitution :
  - Format identique à un PAN (12–19 chiffres, LUHN valide)
  - Préfixe 4999 (CB-PAY HCE simulé)
  - Lié à un vrai PAN dans le Token Vault chiffré en mémoire
  - Portée (domain) : HCE_MOBILE, ECOMMERCE, WALLET, ANY

Cycle de vie :
  ACTIVE → SUSPENDED → ACTIVE   (toggle)
  ACTIVE / SUSPENDED → DELETED  (terminal)

Intégration dans authorize() :
  Si le PAN passé est un token connu → détokenisation transparente
  → le vrai PAN est utilisé pour l'autorisation
  → la réponse inclut token_used=True + token_id
"""

import uuid
import random
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
TOKEN_PREFIX    = "4999"   # BIN réservé simulation CB-PAY
TOKEN_LENGTHS   = {16}     # longueurs supportées
DOMAIN_TYPES    = ("HCE_MOBILE", "ECOMMERCE", "WALLET", "ANY")
STATUS_ACTIVE    = "ACTIVE"
STATUS_SUSPENDED = "SUSPENDED"
STATUS_DELETED   = "DELETED"

# ── Token Vault ───────────────────────────────────────────────────────────────
# token → {id, token, pan_hash, domain, status, ...}
_token_vault:     dict[str, dict] = {}  # token → metadata
_pan_index:       dict[str, list] = {}  # pan_hash → [token, ...]
_token_by_id:     dict[str, dict] = {}  # token_id → metadata (same objects)


# ── Utilitaires LUHN ──────────────────────────────────────────────────────────

def _luhn_checksum(number: str) -> int:
    """Calcule le chiffre de contrôle LUHN."""
    digits = [int(d) for d in reversed(number)]
    odd_sum = sum(digits[0::2])
    even_sum = sum(
        d * 2 - 9 if d * 2 > 9 else d * 2
        for d in digits[1::2]
    )
    return (odd_sum + even_sum) % 10


def _luhn_valid(number: str) -> bool:
    return _luhn_checksum(number) == 0


def _add_luhn(number_without_check: str) -> str:
    """Ajoute le chiffre de contrôle LUHN à un numéro partiel."""
    check = (10 - _luhn_checksum(number_without_check + "0")) % 10
    return number_without_check + str(check)


def _gen_token_pan(prefix: str = TOKEN_PREFIX, length: int = 16,
                   seed: int = None) -> str:
    """Génère un PAN token LUHN-valide."""
    rng = random.Random(seed)
    payload_len = length - len(prefix) - 1  # -1 pour le check digit
    payload = "".join(str(rng.randint(0, 9)) for _ in range(payload_len))
    return _add_luhn(prefix + payload)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pan_hash(pan: str) -> str:
    return hashlib.sha256(pan.replace(" ", "").encode()).hexdigest()[:32]


# ── API publique ───────────────────────────────────────────────────────────────

def create_token(pan: str, domain: str = "HCE_MOBILE",
                 device_info: str = None,
                 requestor_id: str = None,
                 max_uses: int = None) -> dict:
    """
    Crée un nouveau token pour le PAN donné.

    Retourne le dict token (ne contient JAMAIS le vrai PAN).
    """
    pan = pan.replace(" ", "")
    if domain not in DOMAIN_TYPES:
        domain = "ANY"

    # Éviter les collisions
    for _ in range(100):
        seed = int(uuid.uuid4().hex[:8], 16)
        tok = _gen_token_pan(TOKEN_PREFIX, 16, seed=seed)
        if tok not in _token_vault:
            break
    else:
        raise RuntimeError("Impossible de générer un token unique")

    token_id = f"TOK-{uuid.uuid4().hex[:10].upper()}"
    ph = _pan_hash(pan)

    metadata = {
        "id":            token_id,
        "token":         tok,
        "pan_hash":      ph,
        "pan_last4":     pan[-4:],
        "pan_first6":    pan[:6],
        "domain":        domain,
        "status":        STATUS_ACTIVE,
        "device_info":   device_info,
        "requestor_id":  requestor_id or "CB_PAY_SIM",
        "max_uses":      max_uses,
        "use_count":     0,
        "created_at":    _now_iso(),
        "last_used_at":  None,
        "suspended_at":  None,
        "deleted_at":    None,
    }

    _token_vault[tok] = metadata
    _token_by_id[token_id] = metadata
    _pan_index.setdefault(ph, []).append(tok)

    logger.info("Token créé : %s → PAN ...%s domain=%s", token_id, pan[-4:], domain)
    return dict(metadata)


def get_token(token_or_id: str) -> dict | None:
    """Récupère les métadonnées d'un token (par valeur ou par ID)."""
    meta = _token_vault.get(token_or_id) or _token_by_id.get(token_or_id)
    return dict(meta) if meta else None


def get_tokens_by_pan(pan: str) -> list[dict]:
    """Retourne tous les tokens (actifs/suspendus) associés à un PAN."""
    ph = _pan_hash(pan.replace(" ", ""))
    tokens = _pan_index.get(ph, [])
    result = []
    for tok in tokens:
        meta = _token_vault.get(tok)
        if meta and meta["status"] != STATUS_DELETED:
            result.append(dict(meta))
    return result


def detokenize(token: str) -> str | None:
    """
    Résout un token vers le PAN réel.
    Retourne None si le token est inconnu, expiré ou supprimé.
    Ne retourne JAMAIS le PAN — utiliser uniquement dans le moteur d'autorisation.
    """
    meta = _token_vault.get(token)
    if not meta or meta["status"] != STATUS_ACTIVE:
        return None
    if meta.get("max_uses") and meta["use_count"] >= meta["max_uses"]:
        return None

    # Retrouver le vrai PAN depuis la liste des cartes connues
    from models.card import card_db as _card_db
    ph = meta["pan_hash"]
    try:
        for card in _card_db.all_cards():
            if _pan_hash(card.pan) == ph:
                return card.pan
    except Exception:
        pass
    return None


def is_token(value: str) -> bool:
    """Vérifie si une valeur ressemble à un token connu."""
    return value in _token_vault


def use_token(token: str) -> bool:
    """Incrémente le compteur d'utilisation. Retourne False si le token est épuisé."""
    meta = _token_vault.get(token)
    if not meta or meta["status"] != STATUS_ACTIVE:
        return False
    meta["use_count"] += 1
    meta["last_used_at"] = _now_iso()
    if meta.get("max_uses") and meta["use_count"] >= meta["max_uses"]:
        meta["status"] = STATUS_SUSPENDED
        logger.info("Token épuisé (max_uses=%d) : %s", meta["max_uses"], meta["id"])
    return True


def suspend_token(token_or_id: str, reason: str = None) -> dict | None:
    """Suspend un token actif."""
    meta = _token_vault.get(token_or_id) or _token_by_id.get(token_or_id)
    if not meta:
        return None
    if meta["status"] == STATUS_ACTIVE:
        meta["status"]       = STATUS_SUSPENDED
        meta["suspended_at"] = _now_iso()
        if reason:
            meta["suspend_reason"] = reason
        logger.info("Token suspendu : %s", meta["id"])
    return dict(meta)


def resume_token(token_or_id: str) -> dict | None:
    """Réactive un token suspendu."""
    meta = _token_vault.get(token_or_id) or _token_by_id.get(token_or_id)
    if not meta:
        return None
    if meta["status"] == STATUS_SUSPENDED:
        meta["status"]       = STATUS_ACTIVE
        meta["suspended_at"] = None
        meta.pop("suspend_reason", None)
        logger.info("Token réactivé : %s", meta["id"])
    return dict(meta)


def delete_token(token_or_id: str) -> dict | None:
    """Supprime définitivement un token."""
    meta = _token_vault.get(token_or_id) or _token_by_id.get(token_or_id)
    if not meta:
        return None
    meta["status"]     = STATUS_DELETED
    meta["deleted_at"] = _now_iso()
    logger.info("Token supprimé : %s", meta["id"])
    return dict(meta)


def get_all_tokens(limit: int = 50, offset: int = 0,
                   status: str = None, domain: str = None) -> list[dict]:
    """Liste tous les tokens (par défaut excluant DELETED)."""
    tokens = list(_token_vault.values())
    if status:
        tokens = [t for t in tokens if t["status"] == status]
    elif status is None:
        tokens = [t for t in tokens if t["status"] != STATUS_DELETED]
    if domain:
        tokens = [t for t in tokens if t["domain"] == domain]
    tokens.sort(key=lambda t: t["created_at"], reverse=True)
    return [dict(t) for t in tokens[offset: offset + limit]]


def get_token_stats() -> dict:
    """Statistiques agrégées du token vault."""
    all_t = list(_token_vault.values())
    active    = sum(1 for t in all_t if t["status"] == STATUS_ACTIVE)
    suspended = sum(1 for t in all_t if t["status"] == STATUS_SUSPENDED)
    deleted   = sum(1 for t in all_t if t["status"] == STATUS_DELETED)
    by_domain: dict[str, int] = {}
    for t in all_t:
        if t["status"] != STATUS_DELETED:
            by_domain[t["domain"]] = by_domain.get(t["domain"], 0) + 1
    return {
        "total":     len(all_t),
        "active":    active,
        "suspended": suspended,
        "deleted":   deleted,
        "by_domain": by_domain,
    }
