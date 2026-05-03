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
- Vélocité par carte (fenêtre glissante)
- MCC bloqués (jeux, contenus adultes, etc.)
- Routage domestique CB prioritaire sur VISA/MC
- Intégration résultat 3DS2 (ECI)
- Contrôle PIN (tentatives restantes)
- Règles remboursement / retrait / récurrent
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
CB_MCC_FLOOR_LIMITS: Dict[str, int] = {
    "5411": 3000,
    "5412": 3000,
    "5541": 0,
    "5542": 0,
    "5912": 5000,
    "5812": 5000,
    "5813": 3000,
    "5814": 3000,
    "5999": 3000,
    "7011": 0,
    "7996": 3000,
    "4111": 5000,
    "4112": 5000,
    "4121": 5000,
    "4131": 5000,
    "4784": 5000,
    "DEFAULT": 3000,
}

# ── Paramètres sans contact CB (NFC / Contactless) ───────────────────────────
CB_CONTACTLESS = {
    "single_txn_limit":          5000,
    "single_txn_limit_no_pin":   5000,
    "cumulative_offline_limit":  15000,
    "max_consecutive_offline":   5,
    "low_value_threshold":       3000,
}

# ── Plafonds CB CAP (Card Acceptor Parameters) ────────────────────────────────
CB_CAP = {
    "offline_floor_limit":       3000,
    "max_offline_amount":        20000,
    "max_online_amount":         500000,
    "referral_threshold":        500000,
    "high_value_threshold":      100000,
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
    "R13": "Vélocité dépassée — trop de transactions en peu de temps",
    "R14": "PIN bloqué — nombre de tentatives dépassé",
    "R15": "Remboursement non autorisé — montant supérieur à l'original",
}

# ── Exemptions SCA (DSP2) CB ──────────────────────────────────────────────────
CB_SCA_EXEMPTIONS = [
    {"code": "LVP",  "name": "Low Value Payment",      "max_amount": 3000,  "description": "Paiement ≤ 30€ — exemption micro-paiement"},
    {"code": "MIT",  "name": "Merchant Initiated",     "max_amount": None,  "description": "Transaction initiée par le commerçant (récurrent)"},
    {"code": "TRA",  "name": "Transaction Risk Analysis", "max_amount": 25000, "description": "Analyse de risque < 250€"},
    {"code": "TTP",  "name": "Trusted Third Party",    "max_amount": None,  "description": "Bénéficiaire de confiance"},
    {"code": "NONE", "name": "Aucune exemption",       "max_amount": None,  "description": "SCA complète requise"},
]

# ── MCC bloqués (C1) ─────────────────────────────────────────────────────────
# Catégories refusées par défaut sur le réseau CB (paramétrable par l'émetteur)
CB_BLOCKED_MCCS: Dict[str, str] = {
    "7995": "Jeux d'argent / Paris sportifs",
    "5967": "Contenu adulte / services téléphoniques",
    "7801": "Casinos en ligne",
    "7802": "Casinos hors ligne (régulé)",
    "9754": "Loteries d'état (restreint)",
    "6051": "Crypto-actifs / monnaies virtuelles",
    "6211": "Instruments financiers / spéculation",
}

# ── Règles vélocité CB (fenêtre glissante) ────────────────────────────────────
CB_VELOCITY_LIMITS = {
    "max_txn_per_30min":   10,   # max 10 transactions sur 30 minutes
    "max_txn_per_hour":    15,   # max 15 transactions sur 60 minutes
    "max_amount_per_hour": 200000,  # 2 000 € / heure (en centimes)
    "max_refund_per_day":  3,    # max 3 remboursements par jour
    "max_refund_amount_ratio": 1.0,  # remboursement ≤ 100 % du montant original
}

# ── Règles PIN CB ─────────────────────────────────────────────────────────────
CB_PIN_RULES = {
    "max_tries": 3,           # 3 tentatives PIN avant blocage
    "block_on_zero": True,    # Bloquer si tries_remaining == 0
}

# ── Pays domestiques CB (routage prioritaire) ─────────────────────────────────
CB_DOMESTIC_COUNTRIES = {"250", "FRA", "FR"}  # France métropolitaine + DOM-TOM
CB_OVERSEAS_TERRITORIES = {"GP", "MQ", "GF", "RE", "YT", "PM", "MF", "BL",
                            "NC", "PF", "WF", "TF"}


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
    velocity_check: str = "N/A"
    routing_info: str = "N/A"
    threeds_result: Optional[str] = None
    pin_check: Optional[str] = None

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
            "velocity_check": self.velocity_check,
            "routing_info": self.routing_info,
            "threeds_result": self.threeds_result,
            "pin_check": self.pin_check,
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
    Retourne (allowed, code, message)
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


# ── C1 : Nouvelles fonctions flux CB complet ─────────────────────────────────

def check_mcc_restriction(mcc: Optional[str]) -> tuple:
    """
    Vérifie si le MCC est bloqué sur le réseau CB.
    Retourne (allowed, reason_code, message)
    """
    if not mcc:
        return True, None, "MCC non spécifié — autorisé par défaut"
    if mcc in CB_BLOCKED_MCCS:
        return False, "R12", "MCC {} bloqué : {}".format(mcc, CB_BLOCKED_MCCS[mcc])
    return True, None, "MCC {} autorisé".format(mcc)


def check_velocity(recent_transactions: Optional[List[dict]],
                   current_amount: int,
                   transaction_type: str) -> tuple:
    """
    Vérifie les règles de vélocité CB (fenêtre glissante).
    recent_transactions : liste de dicts avec clés 'timestamp' (ISO-8601 str ou datetime),
                          'amount' (int centimes), 'type' (str).
    Retourne (allowed, reason_code, message, stats)
    """
    if not recent_transactions:
        return True, None, "Vélocité OK (aucun historique)", {}

    now = datetime.now(timezone.utc)
    txns_30min, txns_1h, amount_1h, refunds_today = [], [], 0, 0

    for t in recent_transactions:
        ts = t.get("timestamp")
        if ts is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        age_secs = (now - ts).total_seconds()
        if age_secs <= 1800:
            txns_30min.append(t)
        if age_secs <= 3600:
            txns_1h.append(t)
            amount_1h += int(t.get("amount", 0))
        if age_secs <= 86400 and t.get("type") in ("20", "refund", "REFUND"):
            refunds_today += 1

    lim = CB_VELOCITY_LIMITS
    stats = {
        "txn_30min": len(txns_30min),
        "txn_1h": len(txns_1h),
        "amount_1h": amount_1h,
        "refunds_today": refunds_today,
    }

    if len(txns_30min) >= lim["max_txn_per_30min"]:
        return False, "R13", "Vélocité dépassée : {} txn/30min (max {})".format(
            len(txns_30min), lim["max_txn_per_30min"]), stats

    if len(txns_1h) >= lim["max_txn_per_hour"]:
        return False, "R13", "Vélocité dépassée : {} txn/h (max {})".format(
            len(txns_1h), lim["max_txn_per_hour"]), stats

    if (amount_1h + current_amount) > lim["max_amount_per_hour"]:
        return False, "R13", "Vélocité montant dépassée : {:.2f}€/h > {:.2f}€".format(
            (amount_1h + current_amount) / 100,
            lim["max_amount_per_hour"] / 100), stats

    if transaction_type in ("20", "refund", "REFUND"):
        if refunds_today >= lim["max_refund_per_day"]:
            return False, "R13", "Trop de remboursements aujourd'hui : {} (max {})".format(
                refunds_today, lim["max_refund_per_day"]), stats

    return True, None, "Vélocité OK ({} txn/30min, {:.2f}€/h)".format(
        len(txns_30min), amount_1h / 100), stats


def check_cb_routing(pan: str, aid_hex: Optional[str],
                     country_code: Optional[str]) -> dict:
    """
    Détermine le routage optimal CB pour une transaction.
    Pour les transactions domestiques (France), préférence CB native (AID CB)
    sur VISA/MC selon règle de préférence locale GIE CB.
    Retourne un dict avec preferred_network, routing_reason, is_domestic.
    """
    card = identify_card(pan, aid_hex)
    is_domestic = country_code in CB_DOMESTIC_COUNTRIES or country_code in CB_OVERSEAS_TERRITORIES

    preferred = card.scheme
    reason = "Routage par défaut ({})" .format(card.scheme)

    if is_domestic and card.scheme in ("VISA", "MC", "MAESTRO"):
        preferred = "CB"
        reason = "Routage CB national prioritaire (pays={}, scheme={})".format(
            country_code, card.scheme)
    elif is_domestic:
        reason = "Réseau CB natif (pays={})".format(country_code)
    else:
        reason = "Routage international ({})".format(card.scheme)

    return {
        "preferred_network": preferred,
        "actual_scheme": card.scheme,
        "routing_reason": reason,
        "is_domestic": is_domestic,
        "country_code": country_code,
    }


def check_pin_status(pin_tries_remaining: Optional[int]) -> tuple:
    """
    Vérifie le statut PIN de la carte.
    Retourne (allowed, response_code, message)
    """
    if pin_tries_remaining is None:
        return True, None, "Statut PIN non renseigné"
    if pin_tries_remaining <= 0 and CB_PIN_RULES["block_on_zero"]:
        return False, "75", "PIN bloqué — {} tentatives épuisées".format(CB_PIN_RULES["max_tries"])
    if pin_tries_remaining == 1:
        return True, None, "WARN: Dernière tentative PIN autorisée"
    return True, None, "PIN OK ({} tentative(s) restante(s))".format(pin_tries_remaining)


def check_refund_rules(amount: int, refund_original_amount: Optional[int]) -> tuple:
    """
    Vérifie les règles de remboursement CB.
    Retourne (allowed, reason_code, message)
    """
    if refund_original_amount is None:
        return True, None, "Remboursement sans montant original de référence"
    ratio = CB_VELOCITY_LIMITS["max_refund_amount_ratio"]
    max_refund = int(refund_original_amount * ratio)
    if amount > max_refund:
        return False, "R15", "Montant remboursement {:.2f}€ > original {:.2f}€ (ratio={})".format(
            amount / 100, refund_original_amount / 100, ratio)
    return True, None, "Remboursement OK ({:.2f}€ ≤ {:.2f}€)".format(
        amount / 100, refund_original_amount / 100)


def get_cb_service_indicator(transaction_type: str, is_contactless: bool = False,
                              is_ecommerce: bool = False, is_recurring: bool = False,
                              is_preauth: bool = False, scheme: str = "CB",
                              is_international: bool = False) -> str:
    """
    Calcule l'indicateur de service CB final selon le contexte complet
    de la transaction.
    """
    if transaction_type in ("01", "withdrawal"):
        if is_international and scheme in ("VISA", "MC", "MAESTRO", "AMEX"):
            return "05"
        return "04"
    if transaction_type in ("20", "refund", "REFUND"):
        return "12"
    if transaction_type in ("22", "cancel", "CANCEL"):
        return "11"
    if transaction_type in ("10", "preauth", "PREAUTH") or is_preauth:
        return "10"
    if is_recurring:
        return "08"
    if is_ecommerce:
        return "07"
    if is_contactless:
        return "06"
    if scheme in ("VISA",):
        return "02"
    if scheme in ("MC", "MAESTRO"):
        return "03"
    return "01"


def evaluate_threeds_result(threeds_eci: Optional[str]) -> tuple:
    """
    Interprète l'ECI 3DS2 dans le contexte CB.
    ECI 05 = authentifié, 06 = tentative, 07 = non authentifié.
    Retourne (sca_satisfied, threeds_result_str, warnings)
    """
    warnings = []
    if threeds_eci is None:
        return None, None, warnings
    if threeds_eci == "05":
        return True, "3DS2_AUTHENTICATED (ECI=05)", warnings
    if threeds_eci == "06":
        warnings.append("3DS2 tentative (ECI=06) — authentification partielle")
        return True, "3DS2_ATTEMPT (ECI=06)", warnings
    if threeds_eci == "07":
        warnings.append("3DS2 non authentifié (ECI=07) — SCA non satisfaite")
        return False, "3DS2_NOT_AUTHENTICATED (ECI=07)", warnings
    warnings.append("ECI inconnu : {}".format(threeds_eci))
    return None, "3DS2_UNKNOWN (ECI={})".format(threeds_eci), warnings


def evaluate_cb_rules(
        pan: str, amount: int, currency: str, transaction_type: str,
        mcc: Optional[str] = None, aid_hex: Optional[str] = None,
        is_contactless: bool = False, contactless_cumul: int = 0,
        consecutive_offline: int = 0, is_recurring: bool = False,
        pos_entry_mode: Optional[str] = None,
        country_code: Optional[str] = None,
        is_ecommerce: bool = False,
        is_preauth: bool = False,
        threeds_eci: Optional[str] = None,
        pin_tries_remaining: Optional[int] = None,
        recent_transactions: Optional[List[dict]] = None,
        refund_original_amount: Optional[int] = None) -> "CBAuthResult":
    """
    Moteur de règles GIE CB principal — flux complet.
    Évalue toutes les règles CB applicables à une transaction.
    """
    warnings = []
    card_info = identify_card(pan, aid_hex)

    # Détection mode sans contact via POS entry mode
    if pos_entry_mode and pos_entry_mode[:2] in ("07", "91", "92"):
        is_contactless = True

    # Détection e-commerce via POS entry mode
    if pos_entry_mode and pos_entry_mode[:2] in ("01", "81"):
        is_ecommerce = True

    def _reject(rc, cb_rc, msg, si, cl_chk, mcc_r, cap_chk, decline, vel="N/A", rout="N/A", tdsr=None, pin_chk=None):
        return CBAuthResult(
            allowed=False, response_code=rc, cb_response_code=cb_rc,
            response_message=msg, service_indicator=si,
            sca_exemption=None, floor_limit_applied=0,
            is_contactless=is_contactless, contactless_check=cl_chk,
            mcc_rule=mcc_r, cap_check=cap_chk, tap_params=CB_TAP,
            warnings=warnings + [msg],
            cb_decline_reason=decline,
            velocity_check=vel, routing_info=rout,
            threeds_result=tdsr, pin_check=pin_chk,
        )

    # ── 0. MCC restreint ──────────────────────────────────────────────────────
    mcc_ok, mcc_decline, mcc_msg = check_mcc_restriction(mcc)
    if not mcc_ok:
        return _reject("57", "57", mcc_msg,
                        card_info.service_indicator, "N/A", "MCC_BLOCKED",
                        "REJECTED", mcc_decline)

    # ── 0.5. PIN status ───────────────────────────────────────────────────────
    pin_ok, pin_rc, pin_msg = check_pin_status(pin_tries_remaining)
    pin_check_str = pin_msg
    if not pin_ok:
        return _reject(pin_rc, pin_rc, pin_msg,
                        card_info.service_indicator, "N/A", "N/A",
                        "REJECTED", "R14",
                        pin_chk=pin_msg)
    if pin_msg.startswith("WARN"):
        warnings.append(pin_msg)

    # ── 0.7. Vélocité ─────────────────────────────────────────────────────────
    vel_ok, vel_decline, vel_msg, vel_stats = check_velocity(
        recent_transactions, amount, transaction_type)
    velocity_check_str = vel_msg
    if not vel_ok:
        return _reject("65", "65", vel_msg,
                        card_info.service_indicator, "N/A", "N/A",
                        "REJECTED", vel_decline,
                        vel=vel_msg)

    # ── 0.8. Règles remboursement ─────────────────────────────────────────────
    if transaction_type in ("20", "refund", "REFUND"):
        ref_ok, ref_decline, ref_msg = check_refund_rules(amount, refund_original_amount)
        if not ref_ok:
            return _reject("57", "57", ref_msg,
                            card_info.service_indicator, "N/A", "REFUND_CHECK",
                            "REJECTED", ref_decline,
                            vel=velocity_check_str)

    # ── 0.9. Routage domestique ───────────────────────────────────────────────
    routing = check_cb_routing(pan, aid_hex, country_code)
    routing_info = "{preferred_network} ({routing_reason})".format(**routing)

    # ── 1. Contrôle CAP — plafond global ─────────────────────────────────────
    if amount > CB_CAP["referral_threshold"]:
        return _reject("01", "01",
                        "Référer à l'émetteur — plafond CB CAP dépassé",
                        card_info.service_indicator, "N/A", "CAP_EXCEEDED",
                        "REFERRAL", "R05",
                        vel=velocity_check_str, rout=routing_info)

    # ── 2. Règles sans contact ────────────────────────────────────────────────
    cl_check = "N/A"
    if is_contactless:
        cl_ok, cl_code, cl_msg = check_contactless(
            amount, contactless_cumul, consecutive_offline)
        if not cl_ok:
            return _reject("62", cl_code,
                            CB_RESPONSE_CODES.get(cl_code, cl_msg),
                            "06", "FAILED", "N/A", "OK",
                            "R07",
                            vel=velocity_check_str, rout=routing_info)
        cl_check = "PASSED ({:.2f}€ / {:.2f}€ cumul)".format(
            amount/100, (contactless_cumul + amount)/100)
        card_info.service_indicator = "06"

    # ── 3. Floor limit MCC ───────────────────────────────────────────────────
    floor = get_floor_limit(mcc)
    mcc_rule = "MCC={} FloorLimit={:.2f}€".format(mcc or "DEFAULT", floor/100)
    if floor == 0:
        warnings.append("MCC {} — autorisation en ligne obligatoire (floor = 0)".format(mcc))

    # ── 4. SCA exemption + 3DS2 ECI ──────────────────────────────────────────
    sca = get_sca_exemption(amount, transaction_type, is_recurring)
    threeds_sca_ok, threeds_result_str, threeds_warns = evaluate_threeds_result(threeds_eci)
    warnings.extend(threeds_warns)

    if threeds_sca_ok is False and amount > CB_CONTACTLESS["low_value_threshold"]:
        warnings.append("SCA DSP2 non satisfaite (ECI=07) — 1A recommandé")
        if sca in ("NONE", "TRA"):
            return _reject("57", "1A",
                            "Authentification forte requise — ECI=07 non satisfait",
                            card_info.service_indicator, cl_check, mcc_rule,
                            "REJECTED", "R09",
                            vel=velocity_check_str, rout=routing_info,
                            tdsr=threeds_result_str, pin_chk=pin_check_str)

    if sca == "NONE" and amount > CB_CONTACTLESS["low_value_threshold"]:
        if not is_ecommerce or threeds_eci is None:
            warnings.append("SCA complète requise pour ce montant")

    # ── 5. Vérification TAP4 (cumul hors ligne) ───────────────────────────────
    if consecutive_offline >= CB_TAP["TAP4_max_offline_count"]:
        warnings.append("TAP4: Nombre max transactions hors ligne ({}) atteint — forcer en ligne".format(
            CB_TAP["TAP4_max_offline_count"]))

    # ── 6. High value check ──────────────────────────────────────────────────
    if amount >= CB_CAP["high_value_threshold"]:
        warnings.append("Montant élevé CB ({:.2f}€) — contrôle renforcé".format(amount/100))

    # ── 7. Service indicator final (flux complet) ─────────────────────────────
    si = get_cb_service_indicator(
        transaction_type, is_contactless, is_ecommerce, is_recurring,
        is_preauth, card_info.scheme)

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
        velocity_check=velocity_check_str,
        routing_info=routing_info,
        threeds_result=threeds_result_str,
        pin_check=pin_check_str,
    )
