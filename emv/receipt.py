"""
v1.11.0 — Export TXT/JSON enrichi des autorisations (ticket TPE).

Génère un reçu de paiement formaté à partir d'une transaction EMV,
au format TXT (ticket 40 colonnes, style terminal de paiement) ou
JSON enrichi (tous les champs TPA + contexte CB).

Utilisation :
    from emv.receipt import format_receipt
    txt  = format_receipt(txn, fmt="txt")
    data = format_receipt(txn, fmt="json")
"""

from datetime import datetime
from typing import Optional

# ── Constantes TPE ────────────────────────────────────────────────────────────
RECEIPT_WIDTH     = 40
SEPARATOR         = "-" * RECEIPT_WIDTH
DOUBLE_SEPARATOR  = "=" * RECEIPT_WIDTH

# Mapping codes réponse → libellé FR
RESPONSE_LABELS = {
    "00": "APPROUVÉ",
    "01": "Référer à l'émetteur",
    "02": "Référer à l'émetteur — condition spéciale",
    "05": "REFUSÉ",
    "12": "Transaction invalide",
    "13": "Montant invalide",
    "14": "Numéro de carte invalide",
    "30": "Erreur de format",
    "41": "Carte perdue",
    "43": "Carte volée",
    "51": "Provision insuffisante",
    "54": "Carte expirée",
    "55": "PIN incorrect",
    "57": "Transaction non autorisée",
    "61": "Dépasse la limite",
    "62": "Carte invalide",
    "63": "Violation de sécurité",
    "65": "Fréquence dépassée",
    "1A": "Authentification forte requise",
    "A5": "Plafond sans contact atteint",
    "P1": "PIN bloqué",
    "P2": "Cumul sans contact dépassé",
}

# Mapping types transaction
TRANSACTION_TYPE_LABELS = {
    "00": "ACHAT",
    "20": "REMBOURSEMENT",
    "30": "PRÉAUTORISATION",
    "31": "CAPTURE PRÉAUTORISATION",
    "40": "REDRESSEMENT",
}

# Mapping mode entrée POS
POS_ENTRY_LABELS = {
    "051": "PUCE EMV",
    "071": "SANS CONTACT NFC",
    "011": "PISTE MAGNÉTIQUE",
    "012": "PISTE MAGNÉTIQUE",
    "010": "SAISIE MANUELLE",
    "002": "SAISIE MANUELLE",
}

CURRENCY_SYMBOLS = {
    "978": "EUR", "840": "USD", "826": "GBP", "756": "CHF",
    "392": "JPY", "504": "MAD", "012": "DZD", "788": "TND",
    "208": "DKK", "752": "SEK", "578": "NOK", "124": "CAD",
}


# ── Helpers formatage TXT ─────────────────────────────────────────────────────

def _center(text: str, width: int = RECEIPT_WIDTH) -> str:
    return text.center(width)


def _line(label: str, value: str, width: int = RECEIPT_WIDTH) -> str:
    """Ligne label+valeur alignés : label à gauche, valeur à droite."""
    available = width - len(label) - 1
    if len(value) > available:
        value = value[:available]
    return "{} {:>{}}".format(label, value, available)


def _wrap(text: str, width: int = RECEIPT_WIDTH) -> list:
    """Découpe un texte long en lignes de `width` caractères."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + (1 if current else 0) <= width:
            current = current + " " + word if current else word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _pan_mask(pan: str) -> str:
    """Masque le PAN : XXXXXXXXXXXXNNNN."""
    if not pan:
        return ""
    pan = pan.replace(" ", "").replace("*", "")
    if len(pan) <= 4:
        return pan
    return "X" * (len(pan) - 4) + pan[-4:]


def _amount_str(amount: int, currency: str = "978") -> str:
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    return "{:.2f} {}".format(amount / 100, symbol)


def _format_dt(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(dt_str).rstrip("Z"))
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(dt_str)[:19]


# ── Formatage TXT (ticket TPE 40 colonnes) ───────────────────────────────────

def _receipt_txt(txn) -> str:
    lines = []

    # En-tête
    lines.append(DOUBLE_SEPARATOR)
    lines.append(_center("SERVEUR D'AUTORISATION EMV"))
    lines.append(_center("GIE CB — ISO 8583 v1.11"))
    lines.append(DOUBLE_SEPARATOR)

    # Type transaction + statut
    txn_type  = TRANSACTION_TYPE_LABELS.get(str(txn.transaction_type), txn.transaction_type or "ACHAT")
    status    = "✓ APPROUVÉ" if str(getattr(txn, "status", "")).upper() == "APPROVED" else "✗ REFUSÉ"
    lines.append(_center(txn_type))
    lines.append(_center(status))
    lines.append(SEPARATOR)

    # Montant
    amount_str = _amount_str(txn.amount, txn.currency)
    lines.append(_center(amount_str))
    if getattr(txn, "reversal_amount", None):
        rev_str = _amount_str(txn.reversal_amount, txn.currency)
        lines.append(_center("Remboursé: {}".format(rev_str)))
    lines.append(SEPARATOR)

    # Carte
    lines.append(_line("CARTE", _pan_mask(txn.pan)))
    if getattr(txn, "cb_scheme", None):
        scheme = "{} {}".format(txn.cb_scheme, txn.cb_brand or "").strip()
        lines.append(_line("RÉSEAU", scheme))
    pos_mode = POS_ENTRY_LABELS.get(str(txn.pos_entry_mode or ""), txn.pos_entry_mode or "")
    if pos_mode:
        lines.append(_line("MODE ENTRÉE", pos_mode))
    if getattr(txn, "cb_is_contactless", False):
        lines.append(_line("SANS CONTACT", "OUI"))
    lines.append(SEPARATOR)

    # Détails autorisation
    lines.append(_line("CODE AUTH", txn.auth_code or "—"))
    lines.append(_line("RRN", txn.rrn or "—"))
    lines.append(_line("ATC", str(txn.atc) if txn.atc is not None else "—"))
    resp_label = RESPONSE_LABELS.get(str(txn.response_code or ""), txn.response_code or "—")
    lines.append(_line("RÉPONSE", txn.response_code or "—"))
    lines.append(_line("", resp_label))
    if getattr(txn, "decline_reason", None):
        lines.append(_line("MOTIF REFUS", str(txn.decline_reason)[:20]))
    lines.append(SEPARATOR)

    # Cryptogrammes EMV
    if getattr(txn, "arqc", None):
        lines.append(_line("ARQC", str(txn.arqc)[:20]))
    if getattr(txn, "arpc", None):
        lines.append(_line("ARPC", str(txn.arpc)[:20]))
    if getattr(txn, "issuer_auth_data", None):
        lines.append(_line("IAD", str(txn.issuer_auth_data)[:20]))

    # GIE CB
    if getattr(txn, "cb_sca_exemption", None):
        lines.append(_line("SCA EXEMPTION", str(txn.cb_sca_exemption)))
    if getattr(txn, "cb_service_indicator", None):
        lines.append(_line("INDICATEUR CB", str(txn.cb_service_indicator)))
    if getattr(txn, "cb_response_code", None):
        lines.append(_line("CODE CB", str(txn.cb_response_code)))
    if getattr(txn, "cb_floor_limit", None) is not None and txn.cb_floor_limit:
        lines.append(_line("FLOOR LIMIT", _amount_str(txn.cb_floor_limit)))
    lines.append(SEPARATOR)

    # Analyse risque
    tier = getattr(txn, "amount_tier", None)
    risk = getattr(txn, "risk_level", None)
    path = getattr(txn, "auth_path", None)
    if tier:
        lines.append(_line("TRANCHE MONTANT", tier))
    if risk:
        lines.append(_line("NIVEAU RISQUE", risk))
    if path:
        lines.append(_line("CHEMIN AUTH", path))
    lines.append(SEPARATOR)

    # Terminal / commerçant
    if getattr(txn, "terminal_id", None):
        lines.append(_line("TERMINAL", str(txn.terminal_id)[:18]))
    if getattr(txn, "merchant_id", None):
        lines.append(_line("COMMERÇANT ID", str(txn.merchant_id)[:16]))
    if getattr(txn, "merchant_name", None):
        lines.append(_line("COMMERÇANT", str(txn.merchant_name)[:18]))
    lines.append(SEPARATOR)

    # Horodatage
    lines.append(_line("DATE/HEURE", _format_dt(txn.created_at)))
    if getattr(txn, "processed_at", None):
        lines.append(_line("TRAITEMENT", _format_dt(txn.processed_at)))
    lines.append(_line("REF. INTERNE", str(txn.id)[:20]))
    lines.append(DOUBLE_SEPARATOR)

    # Pied de page
    lines.append(_center("Conservez ce reçu"))
    lines.append(_center("Transaction traitée par"))
    lines.append(_center("EMV Auth Server v1.11"))
    lines.append(DOUBLE_SEPARATOR)

    return "\n".join(lines)


# ── Formatage JSON enrichi ────────────────────────────────────────────────────

def _receipt_json(txn) -> dict:
    return {
        "receipt_version": "1.11.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "transaction": {
            "id":                txn.id,
            "rrn":               txn.rrn,
            "status":            getattr(txn, "status", None),
            "response_code":     txn.response_code,
            "response_label":    RESPONSE_LABELS.get(str(txn.response_code or ""), "—"),
            "auth_code":         txn.auth_code,
            "atc":               txn.atc,
            "decline_reason":    getattr(txn, "decline_reason", None),
        },
        "card": {
            "pan_masked":        _pan_mask(txn.pan),
            "pos_entry_mode":    txn.pos_entry_mode,
            "pos_entry_label":   POS_ENTRY_LABELS.get(str(txn.pos_entry_mode or ""), ""),
            "is_contactless":    getattr(txn, "cb_is_contactless", False),
            "cb_scheme":         getattr(txn, "cb_scheme", None),
            "cb_brand":          getattr(txn, "cb_brand", None),
        },
        "amount": {
            "value":             txn.amount,
            "formatted":         _amount_str(txn.amount, txn.currency),
            "currency_code":     txn.currency,
            "currency_symbol":   CURRENCY_SYMBOLS.get(txn.currency, txn.currency),
            "reversal_amount":   getattr(txn, "reversal_amount", None),
            "reversal_formatted": (
                _amount_str(txn.reversal_amount, txn.currency)
                if getattr(txn, "reversal_amount", None) else None
            ),
        },
        "emv": {
            "arqc":              txn.arqc,
            "arpc":              txn.arpc,
            "issuer_auth_data":  txn.issuer_auth_data,
            "transaction_type":  txn.transaction_type,
            "transaction_type_label": TRANSACTION_TYPE_LABELS.get(
                str(txn.transaction_type or ""), txn.transaction_type or ""),
        },
        "cb_rules": {
            "sca_exemption":     getattr(txn, "cb_sca_exemption", None),
            "service_indicator": getattr(txn, "cb_service_indicator", None),
            "cb_response_code":  getattr(txn, "cb_response_code", None),
            "cb_decline_reason": getattr(txn, "cb_decline_reason", None),
            "floor_limit":       getattr(txn, "cb_floor_limit", None),
            "floor_limit_formatted": (
                _amount_str(txn.cb_floor_limit)
                if getattr(txn, "cb_floor_limit", None) else None
            ),
        },
        "risk": {
            "amount_tier":  getattr(txn, "amount_tier", None),
            "risk_level":   getattr(txn, "risk_level", None),
            "auth_path":    getattr(txn, "auth_path", None),
        },
        "terminal": {
            "terminal_id":   getattr(txn, "terminal_id", None),
            "merchant_id":   getattr(txn, "merchant_id", None),
            "merchant_name": getattr(txn, "merchant_name", None),
        },
        "timestamps": {
            "created_at":   txn.created_at,
            "processed_at": getattr(txn, "processed_at", None),
            "reversed_at":  getattr(txn, "reversed_at", None),
        },
    }


# ── Point d'entrée public ─────────────────────────────────────────────────────

def format_receipt(txn, fmt: str = "json"):
    """
    Formate un reçu de paiement pour une transaction.

    Args:
        txn : objet Transaction (ou tout objet avec les attributs requis)
        fmt : "txt" → ticket TPE 40 colonnes | "json" → dict enrichi

    Returns:
        str (fmt=txt) ou dict (fmt=json)
    """
    fmt = (fmt or "json").lower().strip()
    if fmt == "txt":
        return _receipt_txt(txn)
    return _receipt_json(txn)


def format_bulk_receipt_txt(transactions: list, title: str = "EXPORT TRANSACTIONS") -> str:
    """Génère un export TXT multi-transactions (header + séparateurs)."""
    lines = []
    lines.append("=" * RECEIPT_WIDTH)
    lines.append(_center(title))
    lines.append(_center("Exporté le {}".format(
        datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC"))))
    lines.append(_center("{} transaction(s)".format(len(transactions))))
    lines.append("=" * RECEIPT_WIDTH)
    lines.append("")

    for i, txn in enumerate(transactions, 1):
        lines.append("  [{}/{}]".format(i, len(transactions)))
        lines.append(_receipt_txt(txn))
        lines.append("")

    lines.append("=" * RECEIPT_WIDTH)
    lines.append(_center("FIN D'EXPORT"))
    lines.append("=" * RECEIPT_WIDTH)
    return "\n".join(lines)
