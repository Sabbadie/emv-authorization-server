"""
Webhooks sortants — A1
Notifie une URL externe (WEBHOOK_URL) lors d'événements métier clés.
Envoi asynchrone (thread daemon) pour ne pas bloquer la réponse HTTP.
"""
import json
import logging
import threading
import urllib.request
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

WEBHOOK_EVENTS = {
    "authorization.approved":  "Autorisation approuvée",
    "authorization.declined":  "Autorisation refusée",
    "reversal.applied":        "Redressement appliqué",
    "chargeback.opened":       "Chargeback ouvert (MTI 0620)",
    "chargeback.reversed":     "Chargeback annulé (MTI 0630)",
    "chargeback.resolved":     "Chargeback résolu",
    "preauth.created":         "Préautorisation créée (MTI 0100)",
    "preauth.captured":        "Préautorisation capturée (MTI 0200)",
    "preauth.cancelled":       "Préautorisation annulée (MTI 0400)",
    "card.blocked":            "Carte bloquée",
    "card.unblocked":          "Carte débloquée",
    "bin_blacklist.added":     "BIN/PAN ajouté à la blackliste",
    "bin_blacklist.removed":   "BIN/PAN retiré de la blackliste",
}

_webhook_log: list = []
_lock = threading.Lock()


def notify(event_type: str, payload: dict,
           webhook_url: Optional[str] = None) -> dict:
    """
    Envoie une notification webhook de façon asynchrone.

    Args:
        event_type:  type d'événement (clé de WEBHOOK_EVENTS)
        payload:     données métier de l'événement
        webhook_url: URL cible (remplace WEBHOOK_URL env var si fourni)

    Returns:
        dict décrivant l'entrée de log (status PENDING | SKIPPED)
    """
    from config import Config
    url = webhook_url or getattr(Config, "WEBHOOK_URL", None)

    body = {
        "event":       event_type,
        "event_label": WEBHOOK_EVENTS.get(event_type, event_type),
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "server":      "EMV-AUTH-SERVER/1.5",
        "data":        payload,
    }

    entry = {
        "id":       _next_id(),
        "event":    event_type,
        "url":      url or "(WEBHOOK_URL non configuré)",
        "sent_at":  body["timestamp"],
        "status":   "SKIPPED" if not url else "PENDING",
        "response": None,
        "error":    None,
    }

    if url:
        def _send():
            try:
                data = json.dumps(body, default=str).encode("utf-8")
                req  = urllib.request.Request(
                    url, data=data, method="POST",
                    headers={
                        "Content-Type":    "application/json",
                        "User-Agent":      "EMV-Auth-Server/1.5",
                        "X-Webhook-Event": event_type,
                    })
                with urllib.request.urlopen(req, timeout=5) as resp:
                    with _lock:
                        entry["status"]   = "DELIVERED"
                        entry["response"] = {"status_code": resp.getcode()}
                    logger.info("Webhook livré : %s → %s", event_type, url)
            except Exception as exc:
                with _lock:
                    entry["status"] = "FAILED"
                    entry["error"]  = str(exc)
                logger.warning("Webhook échoué : %s → %s : %s",
                               event_type, url, exc)

        t = threading.Thread(target=_send, daemon=True)
        t.start()
    else:
        logger.debug("Webhook ignoré (pas d'URL) : %s", event_type)

    with _lock:
        _webhook_log.append(entry)
        if len(_webhook_log) > 200:
            _webhook_log.pop(0)

    return entry


def get_log(limit: int = 50) -> list:
    """Retourne les derniers envois webhook (les plus récents en premier)."""
    with _lock:
        return list(reversed(_webhook_log[-limit:]))


def get_events() -> list:
    """Retourne la liste des types d'événements supportés."""
    return [{"event": k, "label": v} for k, v in WEBHOOK_EVENTS.items()]


def clear_log():
    """Vide le journal des webhooks (usage test)."""
    with _lock:
        _webhook_log.clear()


def stats() -> dict:
    with _lock:
        total     = len(_webhook_log)
        delivered = sum(1 for e in _webhook_log if e["status"] == "DELIVERED")
        failed    = sum(1 for e in _webhook_log if e["status"] == "FAILED")
        skipped   = sum(1 for e in _webhook_log if e["status"] == "SKIPPED")
    return {
        "total": total, "delivered": delivered,
        "failed": failed, "skipped": skipped,
    }


_counter = 0
def _next_id() -> str:
    global _counter
    _counter += 1
    return "WH{:06d}".format(_counter)
