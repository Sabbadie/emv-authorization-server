"""
Système d'alertes visuelles — D5
Génère des alertes temps réel à partir de l'état des cartes et transactions.

Niveaux : INFO · WARNING · CRITICAL
Types   : CONTACTLESS_CUMUL_HIGH · DAILY_LIMIT_APPROACHING · CARD_BLOCKED_HIGH ·
          TRANSACTION_FAILURE_BURST · BIN_BLACKLIST_ACTIVITY · CHARGEBACK_SURGE ·
          PREAUTH_EXPIRY_WARNING · RISK_SCORE_HIGH
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Seuils configurables ───────────────────────────────────────────────────────
CONTACTLESS_WARNING_PCT  = 0.70   # 70 % du plafond sans contact
CONTACTLESS_CRITICAL_PCT = 0.90   # 90 % du plafond sans contact
DAILY_LIMIT_WARNING_PCT  = 0.80   # 80 % de la limite journalière
DAILY_LIMIT_CRITICAL_PCT = 0.95   # 95 %
FAILURE_BURST_WINDOW     = 20     # dernières N transactions
FAILURE_BURST_THRESHOLD  = 0.50   # taux d'échec > 50 % = alerte
CONTACTLESS_MAX          = 15000  # plafond CB (150 €)
CHARGEBACK_SURGE_LIMIT   = 3      # chargebacks ouverts > N → alerte
PREAUTH_EXPIRY_WARN_H    = 2      # préauths expirant dans < 2h


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pct(used, total):
    if total <= 0:
        return 0.0
    return used / total


# ── Générateurs d'alertes ─────────────────────────────────────────────────────

def _contactless_alerts(cards) -> list:
    """Alertes sur le cumul sans contact des cartes actives."""
    alerts = []
    for card in cards:
        if getattr(card, "status", "ACTIVE") != "ACTIVE":
            continue
        cumul = getattr(card, "contactless_cumul", 0)
        pct   = _pct(cumul, CONTACTLESS_MAX)
        if pct < CONTACTLESS_WARNING_PCT:
            continue
        severity = "CRITICAL" if pct >= CONTACTLESS_CRITICAL_PCT else "WARNING"
        alerts.append({
            "type":       "CONTACTLESS_CUMUL_HIGH",
            "severity":   severity,
            "pan_masked": "*" * (len(card.pan) - 4) + card.pan[-4:],
            "message":    (
                f"Cumul sans contact {cumul/100:.2f} € / {CONTACTLESS_MAX/100:.0f} € "
                f"({pct*100:.0f} %) — carte ...{card.pan[-4:]}"
            ),
            "data": {
                "cumul":     cumul,
                "max":       CONTACTLESS_MAX,
                "pct":       round(pct * 100, 1),
                "cb_scheme": getattr(card, "cb_scheme", "?"),
            },
            "created_at": _now_iso(),
        })
    return alerts


def _daily_limit_alerts(cards) -> list:
    """Alertes sur le quota journalier des cartes actives."""
    alerts = []
    for card in cards:
        if getattr(card, "status", "ACTIVE") != "ACTIVE":
            continue
        spent = getattr(card, "daily_spent", 0)
        limit = getattr(card, "daily_limit", 0)
        pct   = _pct(spent, limit)
        if pct < DAILY_LIMIT_WARNING_PCT:
            continue
        severity = "CRITICAL" if pct >= DAILY_LIMIT_CRITICAL_PCT else "WARNING"
        alerts.append({
            "type":       "DAILY_LIMIT_APPROACHING",
            "severity":   severity,
            "pan_masked": "*" * (len(card.pan) - 4) + card.pan[-4:],
            "message":    (
                f"Quota journalier {spent/100:.2f} € / {limit/100:.2f} € "
                f"({pct*100:.0f} %) — carte ...{card.pan[-4:]}"
            ),
            "data": {
                "spent":  spent,
                "limit":  limit,
                "pct":    round(pct * 100, 1),
            },
            "created_at": _now_iso(),
        })
    return alerts


def _failure_burst_alert(transactions) -> list:
    """Alerte si le taux d'échec sur les dernières transactions est trop élevé."""
    recent = list(transactions)[-FAILURE_BURST_WINDOW:]
    if not recent:
        return []
    failed = sum(1 for t in recent if getattr(t, "status", "") == "DECLINED")
    pct    = _pct(failed, len(recent))
    if pct < FAILURE_BURST_THRESHOLD:
        return []
    severity = "CRITICAL" if pct >= 0.70 else "WARNING"
    return [{
        "type":     "TRANSACTION_FAILURE_BURST",
        "severity": severity,
        "message":  (
            f"Taux de refus élevé : {failed}/{len(recent)} transactions "
            f"({pct*100:.0f} %) sur les {len(recent)} dernières"
        ),
        "data": {
            "failed":    failed,
            "total":     len(recent),
            "failure_pct": round(pct * 100, 1),
        },
        "created_at": _now_iso(),
    }]


def _chargeback_surge_alert(chargebacks) -> list:
    """Alerte si trop de chargebacks ouverts simultanément."""
    open_cbs = [c for c in chargebacks
                if getattr(c, "status", "") == "OPEN"]
    if len(open_cbs) <= CHARGEBACK_SURGE_LIMIT:
        return []
    return [{
        "type":     "CHARGEBACK_SURGE",
        "severity": "WARNING",
        "message":  f"{len(open_cbs)} chargebacks ouverts en attente de résolution",
        "data": {"open_count": len(open_cbs)},
        "created_at": _now_iso(),
    }]


def _preauth_expiry_alert(preauths) -> list:
    """Alerte si des préautorisations vont expirer prochainement."""
    from datetime import timedelta
    now = datetime.utcnow()
    alerts = []
    for pa in preauths:
        if getattr(pa, "status", "") != "PENDING":
            continue
        try:
            created = datetime.fromisoformat(pa.created_at)
            expiry  = created + timedelta(hours=getattr(pa, "expiry_hours", 24))
            remaining_h = (expiry - now).total_seconds() / 3600
        except Exception:
            continue
        if remaining_h < 0 or remaining_h > PREAUTH_EXPIRY_WARN_H:
            continue
        alerts.append({
            "type":     "PREAUTH_EXPIRY_WARNING",
            "severity": "WARNING",
            "message":  (
                f"Préautorisation {pa.id[:8]}… expire dans "
                f"{remaining_h:.1f} h (montant {pa.authorized_amount/100:.2f} €)"
            ),
            "data": {
                "preauth_id":    pa.id,
                "remaining_h":   round(remaining_h, 1),
                "amount":        pa.authorized_amount,
                "currency":      getattr(pa, "currency", "978"),
            },
            "created_at": _now_iso(),
        })
    return alerts


def _blacklist_activity_alert(bin_blacklist_obj) -> list:
    """Alerte si la blackliste BIN/PAN a des entrées récentes (< 24 h)."""
    from datetime import timedelta
    now   = datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    try:
        all_data = bin_blacklist_obj.get_all()
    except Exception:
        return []
    recent = []
    for item in all_data.get("bins", []) + all_data.get("pans", []):
        try:
            added = datetime.fromisoformat(item["added_at"])
            if added >= cutoff:
                recent.append(item)
        except Exception:
            pass
    if not recent:
        return []
    return [{
        "type":     "BIN_BLACKLIST_ACTIVITY",
        "severity": "INFO",
        "message":  f"{len(recent)} entrée(s) ajoutée(s) à la blackliste BIN/PAN dans les 24 h",
        "data":     {"recent_count": len(recent)},
        "created_at": _now_iso(),
    }]


# ── API publique ──────────────────────────────────────────────────────────────

def get_active_alerts(card_db=None, transaction_log=None,
                      chargebacks=None, preauths=None,
                      bin_blacklist_obj=None) -> list:
    """
    Calcule et retourne toutes les alertes actives.
    Les arguments peuvent être None — les sources non fournies sont ignorées.
    """
    alerts = []

    if card_db is not None:
        try:
            cards = card_db.all_cards()
            alerts.extend(_contactless_alerts(cards))
            alerts.extend(_daily_limit_alerts(cards))
        except Exception as e:
            logger.warning("Erreur alertes cartes : %s", e)

    if transaction_log is not None:
        try:
            txns = transaction_log.get_all(limit=FAILURE_BURST_WINDOW)
            alerts.extend(_failure_burst_alert(txns))
        except Exception as e:
            logger.warning("Erreur alertes transactions : %s", e)

    if chargebacks is not None:
        try:
            alerts.extend(_chargeback_surge_alert(chargebacks))
        except Exception as e:
            logger.warning("Erreur alertes chargebacks : %s", e)

    if preauths is not None:
        try:
            alerts.extend(_preauth_expiry_alert(preauths))
        except Exception as e:
            logger.warning("Erreur alertes préauths : %s", e)

    if bin_blacklist_obj is not None:
        try:
            alerts.extend(_blacklist_activity_alert(bin_blacklist_obj))
        except Exception as e:
            logger.warning("Erreur alertes blackliste : %s", e)

    # Tri par sévérité décroissante, puis date
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(key=lambda a: (order.get(a["severity"], 9), a["created_at"]))

    # Ajout d'un identifiant stable par alerte
    for i, a in enumerate(alerts):
        a["id"] = f"ALT-{i+1:04d}"

    return alerts


def get_alert_summary(alerts: list) -> dict:
    """Résumé des alertes par sévérité."""
    critical = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
    warning  = sum(1 for a in alerts if a.get("severity") == "WARNING")
    info     = sum(1 for a in alerts if a.get("severity") == "INFO")
    if critical > 0:
        highest = "CRITICAL"
    elif warning > 0:
        highest = "WARNING"
    elif info > 0:
        highest = "INFO"
    else:
        highest = None
    return {
        "total":            len(alerts),
        "critical":         critical,
        "warning":          warning,
        "info":             info,
        "has_critical":     critical > 0,
        "has_warnings":     warning  > 0,
        "highest_severity": highest,
    }
