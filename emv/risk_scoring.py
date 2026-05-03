"""
Moteur de scoring risque enrichi — C5
Score de 0 (risque minimal) à 100 (risque maximal).

Facteurs (total max = 100) :
  - Montant         : 0–30 pts
  - Vélocité        : 0–25 pts
  - MCC             : 0–20 pts
  - Sans contact    : 0–15 pts
  - Heure           : 0–10 pts

Niveaux : LOW (0–24) · MEDIUM (25–49) · HIGH (50–74) · CRITICAL (75–100)
Décisions : ALLOW · CHALLENGE · BLOCK
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── MCC à risque élevé ────────────────────────────────────────────────────────
HIGH_RISK_MCC = {
    "7995": "Jeux/casinos",
    "5816": "Jeux en ligne / achats in-app",
    "6010": "Retrait bancaire guichet",
    "6011": "DAB / distributeur automatique",
    "6050": "Crypto-monnaies / actifs numériques",
    "7273": "Rencontres en ligne",
    "5122": "Médicaments / drogues",
    "5912": "Pharmacies (risque fraude prescription)",
    "4829": "Transferts de fonds",
    "6051": "Bureaux de change",
}

LOW_RISK_MCC = {
    "5411": "Supermarchés",
    "5412": "Épiceries",
    "5814": "Fast-food",
    "5812": "Restaurants",
    "4111": "Transport urbain",
    "4131": "Bus",
    "4784": "Péages autoroute",
    "5541": "Stations service",
    "7011": "Hôtels",
}

MEDIUM_RISK_MCC = {
    "5999": "Divers détail",
    "5732": "Électronique",
    "5944": "Bijouteries",
    "5065": "Pièces électroniques",
}


def _score_amount(amount: int) -> tuple[int, str]:
    """Score basé sur le montant (0–30 pts)."""
    if amount <= 0:       return 0,  "Montant nul"
    if amount <= 1000:    return 0,  "Montant très faible (≤ 10 €)"
    if amount <= 5000:    return 5,  "Montant faible (≤ 50 €)"
    if amount <= 20000:   return 10, "Montant moyen (≤ 200 €)"
    if amount <= 100000:  return 20, "Montant élevé (≤ 1 000 €)"
    if amount <= 500000:  return 25, "Montant très élevé (≤ 5 000 €)"
    return 30, "Montant critique (> 5 000 €)"


def _score_velocity(daily_count: int, hourly_count: int = 0) -> tuple[int, str]:
    """Score basé sur la vélocité (0–25 pts)."""
    score  = 0
    detail = []

    if daily_count >= 20:
        score += 20; detail.append("Vélocité journalière critique ({} tx/j)".format(daily_count))
    elif daily_count >= 10:
        score += 12; detail.append("Vélocité journalière élevée ({} tx/j)".format(daily_count))
    elif daily_count >= 5:
        score += 6;  detail.append("Vélocité journalière modérée ({} tx/j)".format(daily_count))
    elif daily_count >= 2:
        score += 2;  detail.append("Vélocité normale ({} tx/j)".format(daily_count))

    if hourly_count >= 5:
        score += 10; detail.append("Rafale sur 1h ({} tx)".format(hourly_count))
    elif hourly_count >= 3:
        score += 5;  detail.append("Activité soutenue sur 1h ({} tx)".format(hourly_count))

    return min(score, 25), "; ".join(detail) or "Vélocité normale (1ère tx aujourd'hui)"


def _score_mcc(mcc: Optional[str]) -> tuple[int, str]:
    """Score basé sur le MCC (0–20 pts)."""
    if not mcc:
        return 5, "MCC absent — risque indéterminé"
    if mcc in HIGH_RISK_MCC:
        return 20, "MCC risque élevé : {} ({})".format(mcc, HIGH_RISK_MCC[mcc])
    if mcc in MEDIUM_RISK_MCC:
        return 10, "MCC risque moyen : {} ({})".format(mcc, MEDIUM_RISK_MCC[mcc])
    if mcc in LOW_RISK_MCC:
        return 0,  "MCC faible risque : {} ({})".format(mcc, LOW_RISK_MCC[mcc])
    return 5, "MCC standard : {}".format(mcc)


def _score_contactless(is_contactless: bool, contactless_cumul: int,
                        consecutive_offline: int) -> tuple[int, str]:
    """Score basé sur les paramètres sans contact (0–15 pts)."""
    if not is_contactless:
        return 0, "Transaction contact standard"
    score  = 3   # base contactless
    detail = ["Transaction sans contact"]
    if contactless_cumul > 10000:
        score += 7; detail.append("Cumul SC élevé ({:.2f} €)".format(contactless_cumul / 100))
    elif contactless_cumul > 5000:
        score += 3; detail.append("Cumul SC modéré ({:.2f} €)".format(contactless_cumul / 100))
    if consecutive_offline >= 4:
        score += 5; detail.append("{} tx hors ligne consécutives".format(consecutive_offline))
    elif consecutive_offline >= 2:
        score += 2; detail.append("{} tx hors ligne consécutives".format(consecutive_offline))
    return min(score, 15), "; ".join(detail)


def _score_time(hour: Optional[int] = None) -> tuple[int, str]:
    """Score basé sur l'heure (0–10 pts)."""
    if hour is None:
        hour = datetime.utcnow().hour
    if 0 <= hour < 5:
        return 10, "Transaction nocturne ({}h UTC) — risque élevé".format(hour)
    if 5 <= hour < 7:
        return 5,  "Transaction madrugada ({}h UTC)".format(hour)
    if 22 <= hour < 24:
        return 3,  "Transaction soirée tardive ({}h UTC)".format(hour)
    return 0, "Heure habituelle ({}h UTC)".format(hour)


def _get_recommendations(score: int, level: str) -> list[str]:
    if score >= 75:
        return [
            "Bloquer la transaction — risque CRITIQUE",
            "Alerter l'émetteur et le porteur immédiatement",
            "Lancer une procédure de vérification d'identité",
        ]
    if score >= 50:
        return [
            "Exiger une authentification forte (SCA/3DS2)",
            "Demander validation PIN en ligne obligatoire",
            "Surveiller les transactions suivantes de ce PAN",
        ]
    if score >= 25:
        return [
            "Autoriser avec surveillance renforcée",
            "Enregistrer pour analyse comportementale",
        ]
    return ["Transaction à faible risque — autoriser normalement"]


def score_transaction(pan: str, amount: int, currency: str = "978",
                       mcc: Optional[str] = None,
                       is_contactless: bool = False,
                       contactless_cumul: int = 0,
                       consecutive_offline: int = 0,
                       daily_count: int = 0,
                       hourly_count: int = 0,
                       hour: Optional[int] = None) -> dict:
    """
    Calcule un score de risque complet pour une transaction.

    Returns:
        {
            "score": 0–100,
            "level": "LOW|MEDIUM|HIGH|CRITICAL",
            "decision": "ALLOW|CHALLENGE|BLOCK",
            "factors": { montant, vélocité, mcc, sans_contact, heure },
            "recommendations": [...]
        }
    """
    pan = pan.replace(" ", "")
    pan_masked = "*" * (len(pan) - 4) + pan[-4:] if len(pan) > 4 else pan

    s_amount,   d_amount   = _score_amount(amount)
    s_velocity, d_velocity = _score_velocity(daily_count, hourly_count)
    s_mcc,      d_mcc      = _score_mcc(mcc)
    s_cl,       d_cl       = _score_contactless(is_contactless, contactless_cumul,
                                                 consecutive_offline)
    s_time,     d_time     = _score_time(hour)

    total = min(s_amount + s_velocity + s_mcc + s_cl + s_time, 100)

    if total < 25:    level, color = "LOW",      "#28a745"
    elif total < 50:  level, color = "MEDIUM",   "#fd7e14"
    elif total < 75:  level, color = "HIGH",     "#dc3545"
    else:             level, color = "CRITICAL", "#6f0000"

    if total >= 75:   decision = "BLOCK"
    elif total >= 50: decision = "CHALLENGE"
    else:             decision = "ALLOW"

    logger.debug("Risk score PAN=...%s score=%d level=%s decision=%s",
                 pan[-4:], total, level, decision)

    return {
        "score":    total,
        "level":    level,
        "color":    color,
        "decision": decision,
        "pan_masked": pan_masked,
        "inputs": {
            "amount":              amount,
            "amount_formatted":    "{:.2f}".format(amount / 100),
            "currency":            currency,
            "mcc":                 mcc,
            "is_contactless":      is_contactless,
            "contactless_cumul":   contactless_cumul,
            "consecutive_offline": consecutive_offline,
            "daily_count":         daily_count,
            "hourly_count":        hourly_count,
        },
        "factors": {
            "amount": {
                "score": s_amount, "max": 30,
                "pct": round(s_amount / 30 * 100),
                "detail": d_amount,
            },
            "velocity": {
                "score": s_velocity, "max": 25,
                "pct": round(s_velocity / 25 * 100),
                "detail": d_velocity,
            },
            "mcc": {
                "score": s_mcc, "max": 20,
                "pct": round(s_mcc / 20 * 100) if s_mcc else 0,
                "detail": d_mcc,
            },
            "contactless": {
                "score": s_cl, "max": 15,
                "pct": round(s_cl / 15 * 100) if s_cl else 0,
                "detail": d_cl,
            },
            "time": {
                "score": s_time, "max": 10,
                "pct": round(s_time / 10 * 100) if s_time else 0,
                "detail": d_time,
            },
        },
        "recommendations": _get_recommendations(total, level),
    }
