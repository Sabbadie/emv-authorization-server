"""
3-D Secure 2.x (3DS2) — Simulation DSP2/PSD2 — E2
===================================================
Flow :  Marchand → AReq → DS → ACS → ARes
        Si CHALLENGE : CReq → ACS → CRes

Niveaux d'authentification :
  Y  – Authenticated (FRICTIONLESS)
  C  – Challenge Required
  A  – Attempted (not authenticated, attempt registered)
  N  – Not Authenticated
  U  – Unable to authenticate

ECI codes :
  05 – Authentifié 3DS2 (plein)
  06 – Tentative (attempt)
  07 – Non authentifié / pas de 3DS

Exemptions DSP2 supportées :
  LVP   – Low Value Payment (< 30 €)
  TRA   – Transaction Risk Analysis (historique bon + montant raisonnable)
  MIT   – Merchant Initiated Transaction
  CORP  – Corporate / B2B
"""

import uuid
import hmac
import hashlib
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ── Seuils ────────────────────────────────────────────────────────────────────
LVP_LIMIT_EUR_CENTS   = 3000    # 30 € — exemption Low Value Payment
TRA_LIMIT_EUR_CENTS   = 25000   # 250 € — limite TRA
CHALLENGE_THRESHOLD   = 25000   # au-dessus → challenge si pas d'exemption
_3DS_TTL_MINUTES      = 10      # durée de vie d'une session 3DS

# ── Store in-memory des sessions ──────────────────────────────────────────────
_3ds_store: dict[str, dict] = {}   # threeds_id → session dict

# ── Constantes ────────────────────────────────────────────────────────────────
AUTH_STATUS = {
    "AUTHENTICATED":   "Y",
    "CHALLENGE":       "C",
    "ATTEMPTED":       "A",
    "NOT_AUTH":        "N",
    "UNAVAILABLE":     "U",
}
ECI = {
    "AUTHENTICATED":   "05",
    "ATTEMPTED":       "06",
    "NOT_AUTH":        "07",
}
EXEMPTIONS = ("LVP", "TRA", "MIT", "CORP", "NONE")


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _expiry_iso(minutes: int = _3DS_TTL_MINUTES) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)
            ).isoformat().replace("+00:00", "Z")


def _gen_cavv(threeds_id: str, pan: str, amount: int) -> str:
    """Génère un Authentication Value (CAVV) simulé — 20 octets hex."""
    key = f"{threeds_id}:{pan}:{amount}".encode()
    return hmac.new(key, b"3DS2_CAVV_SIM", hashlib.sha256).hexdigest()[:40].upper()


def _detect_exemption(amount: int, pan: str, history_ok: bool) -> str:
    """Détermine l'exemption DSP2 applicable."""
    if amount <= LVP_LIMIT_EUR_CENTS:
        return "LVP"
    if amount <= TRA_LIMIT_EUR_CENTS and history_ok:
        return "TRA"
    return "NONE"


def _decide(amount: int, pan: str, card_status: str,
            exemption: str, force_challenge: bool) -> tuple[str, str]:
    """
    Retourne (status_code, eci).
    Logique :
      - Carte inactive → NOT_AUTH
      - Exemption LVP/TRA/MIT/CORP + pas force → FRICTIONLESS Y
      - Montant > seuil sans exemption → CHALLENGE
      - Sinon FRICTIONLESS
    """
    if card_status not in ("ACTIVE",):
        return AUTH_STATUS["NOT_AUTH"], ECI["NOT_AUTH"]

    if force_challenge:
        return AUTH_STATUS["CHALLENGE"], ECI["NOT_AUTH"]

    if exemption in ("LVP", "TRA", "MIT", "CORP"):
        return AUTH_STATUS["AUTHENTICATED"], ECI["AUTHENTICATED"]

    if amount > CHALLENGE_THRESHOLD:
        return AUTH_STATUS["CHALLENGE"], ECI["NOT_AUTH"]

    return AUTH_STATUS["AUTHENTICATED"], ECI["AUTHENTICATED"]


# ── API publique ───────────────────────────────────────────────────────────────

def authenticate(pan: str, amount: int, currency: str = "978",
                 merchant_id: str = None, merchant_name: str = None,
                 mcc: str = None, card_status: str = "ACTIVE",
                 history_ok: bool = True,
                 force_challenge: bool = False,
                 exemption_hint: str = None) -> dict:
    """
    Crée une session d'authentification 3DS2 (AReq → ARes).

    Retourne un dict avec threeds_id, status, eci, exemption.
    Si status == 'C' (Challenge), un challenge_token est inclus.
    """
    threeds_id = f"3DS-{uuid.uuid4().hex[:12].upper()}"
    exemption  = exemption_hint or _detect_exemption(amount, pan, history_ok)
    status, eci = _decide(amount, pan, card_status, exemption, force_challenge)

    session = {
        "id":            threeds_id,
        "pan_masked":    "*" * (len(pan) - 4) + pan[-4:],
        "pan_hash":      hashlib.sha256(pan.encode()).hexdigest()[:16],
        "amount":        amount,
        "currency":      currency,
        "merchant_id":   merchant_id,
        "merchant_name": merchant_name,
        "mcc":           mcc,
        "status":        status,
        "eci":           eci,
        "exemption":     exemption,
        "cavv":          None,
        "challenge_code": None,
        "challenge_verified": False,
        "challenge_attempts": 0,
        "created_at":    _now_iso(),
        "expires_at":    _expiry_iso(),
        "completed_at":  None,
        "acs_url":       f"https://acs.sim.giecb.fr/3ds2/challenge/{threeds_id}",
    }

    if status == AUTH_STATUS["AUTHENTICATED"]:
        session["cavv"] = _gen_cavv(threeds_id, pan, amount)
        session["completed_at"] = _now_iso()
        logger.info("3DS2 FRICTIONLESS: %s PAN=...%s Amt=%d Exc=%s ECI=%s",
                    threeds_id, pan[-4:], amount, exemption, eci)
    elif status == AUTH_STATUS["CHALLENGE"]:
        # Génération OTP simulé (4 chiffres)
        otp_seed = hashlib.md5(f"{threeds_id}:{pan}".encode()).hexdigest()[:4]
        otp = str(int(otp_seed, 16) % 10000).zfill(4)
        session["challenge_code"] = otp
        logger.info("3DS2 CHALLENGE required: %s PAN=...%s Amt=%d",
                    threeds_id, pan[-4:], amount)
    else:
        session["completed_at"] = _now_iso()
        logger.info("3DS2 NOT_AUTH: %s PAN=...%s status=%s", threeds_id, pan[-4:], card_status)

    _3ds_store[threeds_id] = session

    # Réponse ARes (sans exposer l'OTP interne)
    resp = {k: v for k, v in session.items() if k != "challenge_code"}
    if status == AUTH_STATUS["CHALLENGE"]:
        resp["challenge_hint"] = "OTP envoyé par SMS au porteur"
    return resp


def submit_challenge(threeds_id: str, otp_provided: str) -> dict:
    """
    Valide le challenge (CReq → CRes).

    Retourne le dict de session mis à jour avec le résultat de l'authentification.
    """
    session = _3ds_store.get(threeds_id)
    if not session:
        return {"error": "Session 3DS2 introuvable", "threeds_id": threeds_id}

    if session["status"] != AUTH_STATUS["CHALLENGE"]:
        return {"error": "Session non en attente de challenge", "threeds_id": threeds_id,
                "current_status": session["status"]}

    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
    if now > expires:
        session["status"] = AUTH_STATUS["NOT_AUTH"]
        session["eci"]    = ECI["NOT_AUTH"]
        session["completed_at"] = _now_iso()
        return {**session, "error": "Session expirée"}

    session["challenge_attempts"] = session.get("challenge_attempts", 0) + 1

    if otp_provided == session["challenge_code"]:
        session["status"]               = AUTH_STATUS["AUTHENTICATED"]
        session["eci"]                  = ECI["AUTHENTICATED"]
        session["challenge_verified"]   = True
        session["cavv"]                 = _gen_cavv(
            threeds_id, session["pan_hash"], session["amount"])
        session["completed_at"]         = _now_iso()
        logger.info("3DS2 CHALLENGE passed: %s attempts=%d",
                    threeds_id, session["challenge_attempts"])
    else:
        max_attempts = 3
        if session["challenge_attempts"] >= max_attempts:
            session["status"] = AUTH_STATUS["NOT_AUTH"]
            session["eci"]    = ECI["NOT_AUTH"]
            session["completed_at"] = _now_iso()
            logger.warning("3DS2 CHALLENGE failed (max attempts): %s", threeds_id)
        else:
            logger.warning("3DS2 CHALLENGE wrong OTP: %s attempt=%d",
                           threeds_id, session["challenge_attempts"])

    resp = {k: v for k, v in session.items() if k != "challenge_code"}
    if session["status"] == AUTH_STATUS["CHALLENGE"]:
        remaining = max_attempts - session["challenge_attempts"]
        resp["challenge_hint"] = f"Code incorrect — {remaining} tentative(s) restante(s)"
    return resp


def get_session(threeds_id: str) -> dict | None:
    """Retourne la session 3DS2 (sans le code challenge interne)."""
    session = _3ds_store.get(threeds_id)
    if not session:
        return None
    return {k: v for k, v in session.items() if k != "challenge_code"}


def get_all_sessions(limit: int = 50, offset: int = 0,
                     status: str = None) -> list[dict]:
    """Liste les sessions 3DS2 (sans les codes challenge)."""
    sessions = [
        {k: v for k, v in s.items() if k != "challenge_code"}
        for s in _3ds_store.values()
    ]
    if status:
        sessions = [s for s in sessions if s["status"] == status]
    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return sessions[offset: offset + limit]


def get_stats_3ds() -> dict:
    """Statistiques agrégées des sessions 3DS2."""
    total      = len(_3ds_store)
    auth       = sum(1 for s in _3ds_store.values() if s["status"] == AUTH_STATUS["AUTHENTICATED"])
    challenge  = sum(1 for s in _3ds_store.values() if s["status"] == AUTH_STATUS["CHALLENGE"])
    not_auth   = sum(1 for s in _3ds_store.values() if s["status"] == AUTH_STATUS["NOT_AUTH"])
    exemptions = {}
    for s in _3ds_store.values():
        e = s.get("exemption", "NONE")
        exemptions[e] = exemptions.get(e, 0) + 1
    return {
        "total":         total,
        "authenticated": auth,
        "challenge":     challenge,
        "not_auth":      not_auth,
        "exemptions":    exemptions,
        "auth_rate":     f"{auth/total*100:.1f}%" if total > 0 else "0%",
    }
