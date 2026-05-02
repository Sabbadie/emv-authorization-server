"""
Moteur de règles GIE CB (Groupement des Cartes Bancaires "CB").
Implémente les règles d'autorisation spécifiques au réseau CB français :
- Identification des cartes CB par AID et BIN
- Plafonds sans contact (NFC) et cumuls hors ligne
- Règles SCA (DSP2) et exemptions
- Floor limits par catégorie MCC
- CAP/TAP (paramètres d'acceptation CB)
- Codes réponse CB
- Indicateurs de service CB
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# ── AIDs CB reconnus ──────────────────────────────────────────────────────────
CB_AIDS: Dict[str, dict] = {
    "A0000000421010": {"name": "CB",           "scheme": "CB",      "brand": "CB",      "contactless": True},
    "A0000000422010": {"name": "CB CREDIT",    "scheme": "CB",      "brand": "CB",      "contactless": True},
    "A0000000423010": {"name": "CB DEBIT",     "scheme": "CB",      "brand": "CB",      "contactless": True},
    "A0000000031010": {"name": "VISA",         "scheme": "VISA",    "brand": "VISA CB", "contactless": True},
    "A0000000032010": {"name": "VISA ELECTRON","scheme": "VISA",    "brand": "VISA CB", "contactless": False},
    "A0000000032020": {"name": "VISA V PAY",   "scheme": "VISA",    "brand": "VISA CB", "contactless": True},
    "A0000000041010": {"name": "MASTERCARD",   "scheme": "MC",      "brand": "MC CB",   "contactless": True},
    "A0000000043060": {"name": "MC MAESTRO",   "scheme": "MC",      "brand": "MC CB",   "contactless": True},
    "A0000000046000": {"name": "MC CIRRUS",    "scheme": "MC",      "brand": "MC CB",   "contactless": False},
    "A0000000651010": {"name": "MAESTRO",      "scheme": "MAESTRO", "brand": "MC CB",   "contactless": True},
    "A0000002771010": {"name": "INTERAC",      "scheme": "INTERAC", "brand": "INTERAC", "contactless": False},
    "A000000025010402": {"name": "AMEX",       "scheme": "AMEX",    "brand": "AMEX",    "contactless": True},
}

# ── BIN ranges CB (préfixes PAN) ──────────────────────────────────────────────
CB_BIN_RANGES = [
    {"prefix": "4",  "length": 16, "scheme": "VISA",       "brand": "VISA CB"},
    {"prefix": "51", "length": 16, "scheme": "MC",         "brand": "MC CB"},
    {"prefix": "52", "length": 16, "scheme": "MC",         "brand": "MC CB"},
    {"prefix": "53", "length": 16, "scheme": "MC",         "brand": "MC CB"},
    {"prefix": "54", "length": 16, "scheme": "MC",         "brand": "MC CB"},
    {"prefix": "55", "length": 16, "scheme": "MC",         "brand": "MC CB"},
    {"prefix": "6304", "length": 16, "scheme": "MAESTRO",  "brand": "MC CB"},
    {"prefix": "6759", "length": 16, "scheme": "MAESTRO",  "brand": "MC CB"},
    {"prefix": "676770", "length": 16, "scheme": "MAESTRO","brand": "MC CB"},
    {"prefix": "676774", "length": 16, "scheme": "MAESTRO","brand": "MC CB"},
    {"prefix": "34",  "length": 15, "scheme": "AMEX",      "brand": "AMEX"},
    {"prefix": "37",  "length": 15, "scheme": "AMEX",      "brand": "AMEX"},
]

# ── Floor limits CB par MCC ────────────────────────────────────────────────────
# Montants en centimes d'euro (transaction en dessous = hors ligne OK sans ARQC)
CB_MCC_FLOOR_LIMITS: Dict[str, int] = {
    "5411": 3000,   # Supermarchés / épiceries
    "5412": 3000,   # Supermarchés convenience
    "5541": 0,      # Stations service — toujours en ligne
    "5542": 0,      # Stations service automatiques — toujours en ligne
    "5912": 5000,   # Pharmacies
    "5812": 5000,   # Restaurants
    "5813": 3000,   # Bars / tabacs
    "5814": 3000,   # Fast-food
    "5999": 3000,   # Divers détail
    "7011": 0,      # Hôtels — toujours en ligne
    "7996": 3000,   # Parcs d'attractions
    "4111": 5000,   # Transport local
    "4112": 5000,   # Trains
    "4121": 5000,   # Taxis
    "4131": 5000,   # Bus
    "4784": 5000,   # Péages
    "5999": 3000,
    "DEFAULT": 3000,
}

# ── Paramètres sans contact CB (NFC / Contactless) ───────────────────────────
CB_CONTACTLESS = {
    "single_txn_limit":          5000,   # 50,00€ — plafond par transaction sans contact
    "single_txn_limit_no_pin":   5000,   # 50,00€ — sans PIN (DSP2 low value)
    "cumulative_offline_limit":  15000,  # 150,00€ — cumul hors ligne
    "max_consecutive_offline":   5,      # Nb max transactions hors ligne consécutives
    "low_value_threshold":       3000,   # 30,00€ — seuil micro-paiement SCA
}

# ── Plafonds CB CAP (Card Acceptor Parameters) ────────────────────────────────
CB_CAP = {
    "offline_floor_limit":       3000,   # 30,00€
    "max_offline_amount":        20000,  # 200,00€
    "max_online_amount":         500000, # 5 000,00€
    "referral_threshold":        500000, # > 5 000,00€ → référer
    "high_value_threshold":      100000, # 1 000,00€
}

# ── Paramètres CB TAP (Terminal Application Parameters) ──────────────────────
CB_TAP = {
    "TAP1_offline_floor_limit":         3000,
    "TAP2_cumulative_offline_limit":    15000,
    "TAP3_max_per_transaction":         500000,
    "TAP4_max_offline_count":           5,
    "TAP5_terminal_risk_threshold":     10000,
}

# ── Indicateurs de service CB ─────────────────────────────────────────────────
CB_SERVICE_INDICATORS = {
    "01": "Paiement national CB",
    "02": "Paiement international VISA",
    "03": "Paiement international MC",
    "04": "Retrait DAB national CB",
    "05": "Retrait DAB international",
    "06": "Paiement sans contact NFC",
    "07": "Paiement en ligne e-commerce",
    "08": "Paiement récurrent",
    "09": "Paiement différé",
    "10": "Préautorisation",
    "11": "Annulation",
    "12": "Remboursement",
}

# ── Codes réponse CB spécifiques ──────────────────────────────────────────────
CB_RESPONSE_CODES = {
    "00": "Autorisation accordée",
    "01": "Contacter l'émetteur",
    "02": "Contacter l'émetteur — conditions spéciales",
    "03": "Commerçant invalide",
    "04": "Capturer la carte",
    "05": "Ne pas honorer",
    "1A": "Authentification forte requise (SCA DSP2)",
    "12": "Transaction invalide",
    "13": "Montant invalide",
    "14": "Numéro de carte invalide",
    "30": "Erreur de format",
    "41": "Carte perdue — capturer",
    "43": "Carte volée — capturer",
    "51": "Provision insuffisante",
    "54": "Carte expirée",
    "55": "Code PIN incorrect",
    "57": "Transaction non autorisée pour ce type de carte",
    "58": "Transaction non autorisée pour ce terminal",
    "61": "Plafond de retrait dépassé",
    "62": "Carte avec restriction",
    "63": "Violation règles de sécurité",
    "65": "Fréquence des transactions dépassée",
    "70": "Contactez votre banque",
    "75": "Nombre de tentatives PIN dépassé",
    "76": "Carte non activée",
    "90": "Arrêt journalier en cours",
    "91": "Émetteur ou réseau inaccessible",
    "96": "Dysfonctionnement du système",
    "A3": "Carte non acceptée sur ce terminal",
    "A5": "Cumul sans contact dépassé — insérer la carte",
    "P1": "Plafond sans contact dépassé",
    "P2": "Cumul hors ligne dépassé",
}

# ── Codes motif de refus CB ──────────────────────────────────────────────────
CB_DECLINE_REASONS = {
    "R01": "Solde insuffisant",
    "R02": "Carte bloquée par l'émetteur",
    "R03": "Carte perdue",
    "R04": "Carte volée",
    "R05": "Limite journalière dépassée",
    "R06": "Limite mensuelle dépassée",
    "R07": "Plafond sans contact cumulé dépassé",
    "R08": "Nombre de transactions hors ligne dépassé",
    "R09": "SCA requise — authentification forte obligatoire",
    "R10": "Transaction hors zone géographique autorisée",
    "R11": "Type de transaction non autorisé pour cette carte",
    "R12": "Commerçant non autorisé (MCC restreint)",
}

# ── Exemptions SCA (DSP2) CB ──────────────────────────────────────────────────
CB_SCA_EXEMPTIONS = [
    {"code": "LVP",  "name": "Low Value Payment",      "max_amount": 3000,  "description": "Paiement ≤ 30€ — exemption micro-paiement"},
    {"code": "MIT",  "name": "Merchant Initiated",     "max_amount": None,  "description": "Transaction initiée par le commerçant (récurrent)"},
    {"code": "TRA",  "name": "Transaction Risk Analysis", "max_amount": 25000, "description": "Analyse de risque < 250€"},
    {"code": "TTP",  "name": "Trusted Third Party",    "max_amount": None,  "description": "Bénéficiaire de confiance"},
    {"code": "NONE", "name": "Aucune exemption",       "max_amount": None,  "description": "SCA complète requise"},
]


@dataclass
class CBCardInfo:
    pan: str
    scheme: str
    brand: str
    aid: Optional[str]
    aid_name: Optional[str]
    is_cb_network: bool
    supports_contactless: bool
    service_indicator: str
    contactless_cumul: int = 0
    consecutive_offline: int = 0


@dataclass
class CBAuthResult:
    allowed: bool
    response_code: str
    cb_response_code: str
    response_message: str
    service_indicator: str
    sca_exemption: Optional[str]
    floor_limit_applied: int
    is_contactless: bool
    contactless_check: str
    mcc_rule: str
    cap_check: str
    tap_params: dict
    warnings: List[str] = field(default_factory=list)
    cb_decline_reason: Optional[str] = None

    def to_dict(self):
        return {
            "allowed": self.allowed,
            "response_code": self.response_code,
            "cb_response_code": self.cb_response_code,
            "response_message": self.response_message,
            "service_indicator": self.service_indicator,
            "sca_exemption": self.sca_exemption,
            "floor_limit_applied": self.floor_limit_applied,
            "is_contactless": self.is_contactless,
            "contactless_check": self.contactless_check,
            "mcc_rule": self.mcc_rule,
            "cap_check": self.cap_check,
            "tap_params": self.tap_params,
            "warnings": self.warnings,
            "cb_decline_reason": self.cb_decline_reason,
        }


def identify_card(pan: str, aid_hex: Optional[str] = None) -> CBCardInfo:
    """Identifie le type de carte CB à partir du PAN et/ou de l'AID."""
    pan = pan.replace(" ", "")

    aid_info = None
    if aid_hex:
        aid_upper = aid_hex.upper()
        for aid_key, info in CB_AIDS.items():
            if aid_upper.startswith(aid_key):
                aid_info = info
                break

    bin_info = None
    for b in sorted(CB_BIN_RANGES, key=lambda x: -len(x["prefix"])):
        if pan.startswith(b["prefix"]):
            bin_info = b
            break

    if aid_info:
        scheme = aid_info["scheme"]
        brand = aid_info["brand"]
        supports_cl = aid_info["contactless"]
        aid_name = aid_info["name"]
    elif bin_info:
        scheme = bin_info["scheme"]
        brand = bin_info["brand"]
        supports_cl = True
        aid_name = None
    else:
        scheme = "UNKNOWN"
        brand = "UNKNOWN"
        supports_cl = False
        aid_name = None

    is_cb = scheme in ("CB", "VISA", "MC", "MAESTRO", "AMEX")

    service_ind = "01"
    if scheme == "VISA":
        service_ind = "02"
    elif scheme in ("MC", "MAESTRO"):
        service_ind = "03"

    return CBCardInfo(
        pan=pan, scheme=scheme, brand=brand,
        aid=aid_hex, aid_name=aid_name,
        is_cb_network=is_cb, supports_contactless=supports_cl,
        service_indicator=service_ind,
    )


def get_floor_limit(mcc: Optional[str]) -> int:
    """Retourne le floor limit CB pour un MCC donné."""
    if not mcc:
        return CB_MCC_FLOOR_LIMITS["DEFAULT"]
    return CB_MCC_FLOOR_LIMITS.get(str(mcc), CB_MCC_FLOOR_LIMITS["DEFAULT"])


def get_sca_exemption(amount: int, transaction_type: str,
                      is_recurring: bool = False) -> str:
    """Détermine l'exemption SCA applicable."""
    if is_recurring:
        return "MIT"
    if amount <= CB_CONTACTLESS["low_value_threshold"]:
        return "LVP"
    if amount <= 25000:
        return "TRA"
    return "NONE"


def check_contactless(amount: int, contactless_cumul: int,
                       consecutive_offline: int) -> tuple:
    """
    Vérifie les règles sans contact CB.
    Retourne (allowed, message, new_status)
    """
    cl = CB_CONTACTLESS

    if amount > cl["single_txn_limit"]:
        return False, "P1", "Montant dépasse le plafond sans contact ({:.2f}€)".format(
            cl["single_txn_limit"] / 100)

    if (contactless_cumul + amount) > cl["cumulative_offline_limit"]:
        return False, "A5", "Cumul hors ligne sans contact dépassé — insérer la carte"

    if consecutive_offline >= cl["max_consecutive_offline"]:
        return False, "A5", "Nombre max de transactions hors ligne consécutives atteint"

    return True, "00", "Contactless OK"


def evaluate_cb_rules(
        pan: str, amount: int, currency: str, transaction_type: str,
        mcc: Optional[str] = None, aid_hex: Optional[str] = None,
        is_contactless: bool = False, contactless_cumul: int = 0,
        consecutive_offline: int = 0, is_recurring: bool = False,
        pos_entry_mode: Optional[str] = None) -> CBAuthResult:
    """
    Moteur de règles GIE CB principal.
    Évalue toutes les règles CB applicables à une transaction.
    """
    warnings = []
    card_info = identify_card(pan, aid_hex)

    # Détection mode sans contact via POS entry mode
    if pos_entry_mode and pos_entry_mode[:2] in ("07", "91", "92"):
        is_contactless = True

    # ── 1. Contrôle CAP — plafond global ─────────────────────────────────────
    if amount > CB_CAP["referral_threshold"]:
        return CBAuthResult(
            allowed=False, response_code="01", cb_response_code="01",
            response_message="Référer à l'émetteur — plafond CB CAP dépassé",
            service_indicator=card_info.service_indicator,
            sca_exemption=None, floor_limit_applied=0,
            is_contactless=is_contactless, contactless_check="N/A",
            mcc_rule="CAP_EXCEEDED", cap_check="REFERRAL",
            tap_params=CB_TAP,
            warnings=["Montant {:.2f}€ > plafond CAP {:.2f}€".format(
                amount/100, CB_CAP["referral_threshold"]/100)],
            cb_decline_reason="R05",
        )

    # ── 2. Règles sans contact ────────────────────────────────────────────────
    cl_check = "N/A"
    if is_contactless:
        cl_ok, cl_code, cl_msg = check_contactless(
            amount, contactless_cumul, consecutive_offline)
        if not cl_ok:
            return CBAuthResult(
                allowed=False, response_code="62", cb_response_code=cl_code,
                response_message=CB_RESPONSE_CODES.get(cl_code, cl_msg),
                service_indicator="06",
                sca_exemption=None, floor_limit_applied=0,
                is_contactless=True, contactless_check="FAILED",
                mcc_rule="N/A", cap_check="OK",
                tap_params=CB_TAP,
                warnings=[cl_msg],
                cb_decline_reason="R07",
            )
        cl_check = "PASSED ({:.2f}€ / {:.2f}€ cumul)".format(
            amount/100, (contactless_cumul + amount)/100)

        if is_contactless:
            card_info.service_indicator = "06"

    # ── 3. Floor limit MCC ───────────────────────────────────────────────────
    floor = get_floor_limit(mcc)
    mcc_rule = "MCC={} FloorLimit={:.2f}€".format(mcc or "DEFAULT", floor/100)
    if floor == 0:
        warnings.append("MCC {} — autorisation en ligne obligatoire (floor = 0)".format(mcc))

    # ── 4. SCA exemption ─────────────────────────────────────────────────────
    sca = get_sca_exemption(amount, transaction_type, is_recurring)
    if sca == "NONE" and amount > CB_CONTACTLESS["low_value_threshold"]:
        warnings.append("SCA complète requise pour ce montant")

    # ── 5. Vérification TAP4 (cumul hors ligne) ───────────────────────────────
    if consecutive_offline >= CB_TAP["TAP4_max_offline_count"]:
        warnings.append("TAP4: Nombre max transactions hors ligne ({}) atteint — forcer en ligne".format(
            CB_TAP["TAP4_max_offline_count"]))

    # ── 6. High value check ──────────────────────────────────────────────────
    if amount >= CB_CAP["high_value_threshold"]:
        warnings.append("Montant élevé CB ({:.2f}€) — contrôle renforcé".format(amount/100))

    # ── 7. Service indicator final ───────────────────────────────────────────
    si = card_info.service_indicator
    if transaction_type == "01":
        si = "04"
    elif transaction_type == "20":
        si = "12"
    elif is_contactless:
        si = "06"

    return CBAuthResult(
        allowed=True, response_code="00",
        cb_response_code="00",
        response_message="Règles CB validées",
        service_indicator=si,
        sca_exemption=sca,
        floor_limit_applied=floor,
        is_contactless=is_contactless,
        contactless_check=cl_check,
        mcc_rule=mcc_rule,
        cap_check="OK — Montant {:.2f}€ ≤ CAP {:.2f}€".format(
            amount/100, CB_CAP["max_online_amount"]/100),
        tap_params=CB_TAP,
        warnings=warnings,
    )
