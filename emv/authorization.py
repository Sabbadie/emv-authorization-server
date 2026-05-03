"""
EMV Authorization Logic — avec règles GIE CB, tranches montant et réponse TPA
"""

import uuid
import logging
from datetime import datetime

from emv.tlv import parse, find_tag, extract_emv_fields
from emv.crypto import verify_arqc, CryptoError
from emv.data_elements import CRYPTOGRAM_TYPE
from emv.amount_rules import get_tier, evaluate_amount
from emv.giecb import evaluate_cb_rules, identify_card, CB_RESPONSE_CODES
from emv.bin_blacklist import bin_blacklist
from models.card import CardStatus, card_db
from models.transaction import Transaction, TransactionStatus, transaction_log
from models.tpa_response import TPAResponse
from config import Config

logger = logging.getLogger(__name__)


class AuthorizationResult:
    def __init__(self, approved, response_code, auth_code=None,
                 issuer_auth_data=None, arpc=None, message=None,
                 transaction=None, amount_decision=None, cb_result=None):
        self.approved = approved
        self.response_code = response_code
        self.auth_code = auth_code
        self.issuer_auth_data = issuer_auth_data
        self.arpc = arpc
        self.message = message or Config.RESPONSE_CODES.get(response_code, "Unknown")
        self.transaction = transaction
        self.amount_decision = amount_decision
        self.cb_result = cb_result
        self._tpa = None

    @property
    def tpa(self):
        if self._tpa is None and self.transaction:
            self._tpa = TPAResponse(
                self.transaction, self,
                self.amount_decision, self.cb_result)
        return self._tpa

    def to_dict(self, include_tpa=True):
        result = {
            "approved": self.approved,
            "response_code": self.response_code,
            "message": self.message,
        }
        if self.auth_code:
            result["auth_code"] = self.auth_code
        if self.issuer_auth_data:
            result["issuer_auth_data"] = self.issuer_auth_data
        if self.arpc:
            result["arpc"] = self.arpc
        if self.amount_decision:
            result["amount_decision"] = self.amount_decision.to_dict()
        if self.cb_result:
            result["cb_result"] = self.cb_result.to_dict()
        if self.transaction:
            result["transaction"] = self.transaction.to_dict()
        if include_tpa and self.tpa:
            result["tpa_response"] = self.tpa.to_dict(include_definitions=True)
        return result


def generate_auth_code():
    return str(uuid.uuid4().int)[:6].zfill(6)


def _parse_emv_field55(field_55_hex):
    if not field_55_hex or not str(field_55_hex).strip():
        return None
    try:
        tlv_list = parse(field_55_hex)
        fields = extract_emv_fields(field_55_hex)

        def get_value(tag_hex):
            tag = int(tag_hex, 16)
            tlv = find_tag(tlv_list, tag)
            return tlv.value if tlv else None

        return {
            "amount_authorized": get_value("9F02"),
            "amount_other": get_value("9F03"),
            "terminal_country_code": get_value("9F1A"),
            "tvr": get_value("95"),
            "transaction_date": get_value("9A"),
            "transaction_type": get_value("9C"),
            "transaction_currency": get_value("5F2A"),
            "unpredictable_number": get_value("9F37"),
            "atc": get_value("9F36"),
            "cryptogram": get_value("9F26"),
            "cryptogram_info": get_value("9F27"),
            "issuer_app_data": get_value("9F10"),
            "pan_sequence": get_value("5F34"),
            "terminal_capabilities": get_value("9F33"),
            "cvm_results": get_value("9F34"),
            "aid_card": get_value("4F"),
            "aid_terminal": get_value("9F06"),
            "app_version_card": get_value("9F08"),
            "app_version_terminal": get_value("9F09"),
            "aip": get_value("82"),
            # Champs CB spécifiques
            "consecutive_txn_limit": get_value("9F53"),
            "cumulative_total_limit": get_value("9F54"),
            "all_fields": fields,
        }
    except Exception as e:
        logger.error("Failed to parse EMV field 55: %s", str(e))
        return None


def _build_arqc_data(emv_parsed, amount, currency_code):
    fields = [
        emv_parsed.get("amount_authorized") or bytes(6),
        emv_parsed.get("amount_other") or bytes(6),
        emv_parsed.get("terminal_country_code") or bytes(2),
        emv_parsed.get("tvr") or bytes(5),
        emv_parsed.get("transaction_currency") or bytes(2),
        emv_parsed.get("transaction_date") or bytes(3),
        emv_parsed.get("transaction_type") or bytes(1),
        emv_parsed.get("unpredictable_number") or bytes(4),
        emv_parsed.get("atc") or bytes(2),
        emv_parsed.get("issuer_app_data") or bytes(0),
    ]
    return b"".join(fields)


def check_tvr(tvr_bytes):
    if not tvr_bytes or len(tvr_bytes) < 5:
        return []
    flags = []
    b1, b2, b3, b4, b5 = tvr_bytes
    if b1 & 0x80: flags.append("Offline data authentication not performed")
    if b1 & 0x40: flags.append("SDA failed")
    if b1 & 0x20: flags.append("ICC data missing")
    if b1 & 0x10: flags.append("Card appears on terminal exception file")
    if b1 & 0x08: flags.append("DDA failed")
    if b1 & 0x04: flags.append("CDA failed")
    if b2 & 0x80: flags.append("ICC and terminal have different application versions")
    if b2 & 0x40: flags.append("Expired application")
    if b2 & 0x20: flags.append("Application not yet effective")
    if b3 & 0x80: flags.append("Cardholder verification was not successful")
    if b3 & 0x20: flags.append("PIN try limit exceeded")
    if b4 & 0x80: flags.append("Transaction exceeds floor limit")
    if b5 & 0x40: flags.append("Issuer authentication failed")
    return flags


def authorize(pan, amount, currency, transaction_type,
              field_55=None, terminal_id=None, merchant_id=None,
              merchant_name=None, pos_entry_mode="05",
              skip_crypto=False, mcc=None, is_contactless=False):
    pan = pan.replace(" ", "")
    txn = Transaction(
        pan=pan, amount=amount, currency=currency,
        transaction_type=transaction_type,
        terminal_id=terminal_id, merchant_id=merchant_id,
        merchant_name=merchant_name, pos_entry_mode=pos_entry_mode,
    )

    txn.log_event("TRANSACTION_CREATED", "Transaction initiée", data={
        "pan_masked": "*" * (len(pan) - 4) + pan[-4:],
        "amount": amount,
        "amount_formatted": "{:.2f}".format(amount / 100),
        "currency": currency,
        "transaction_type": transaction_type,
        "terminal_id": terminal_id,
        "merchant_id": merchant_id,
        "pos_entry_mode": pos_entry_mode,
        "is_contactless": is_contactless,
        "has_emv_data": bool(field_55),
    })

    # ── 0. Vérification blackliste BIN/PAN (E7) ───────────────────────────────
    is_blocked, block_type, block_reason = bin_blacklist.is_blacklisted(pan)
    if is_blocked:
        txn.decline("63", f"BIN/PAN blacklisté ({block_type}) : {block_reason}")
        txn.log_event("BIN_BLACKLIST_CHECK",
                      f"PAN refusé — {block_type} blacklisté",
                      level="ERROR",
                      data={"block_type": block_type, "reason": block_reason})
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — blackliste BIN/PAN",
                      level="ERROR",
                      data={"response_code": "63", "block_type": block_type})
        transaction_log.add(txn)
        return AuthorizationResult(
            False, "63",
            message=f"BIN/PAN blacklisté : {block_reason}",
            transaction=txn)
    txn.log_event("BIN_BLACKLIST_CHECK", "PAN non blacklisté — OK",
                  data={"pan_suffix": pan[-4:]})

    # ── 1. Évaluation par tranche de montant ─────────────────────────────────
    has_arqc = bool(field_55)
    daily_count = len(transaction_log.get_by_pan(pan, limit=200))
    amount_decision = evaluate_amount(amount, transaction_type,
                                      daily_count=daily_count,
                                      has_arqc=has_arqc)
    txn.amount_tier = amount_decision.tier.name
    txn.risk_level = amount_decision.tier.risk_level
    txn.auth_path = amount_decision.auth_path

    txn.log_event("AMOUNT_EVALUATION",
                  f"Tranche: {amount_decision.tier.name} | Chemin: {amount_decision.auth_path}",
                  level="INFO" if amount_decision.allowed else "WARN",
                  data={
                      "tier": amount_decision.tier.name,
                      "tier_label": amount_decision.tier.label,
                      "risk_level": amount_decision.tier.risk_level,
                      "auth_path": amount_decision.auth_path,
                      "allowed": amount_decision.allowed,
                      "response_code": amount_decision.response_code,
                      "daily_count": daily_count,
                  })

    if not amount_decision.allowed:
        txn.decline(amount_decision.response_code,
                    amount_decision.response_message)
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — tranche montant",
                      level="ERROR",
                      data={"response_code": amount_decision.response_code,
                            "reason": amount_decision.response_message})
        transaction_log.add(txn)
        return AuthorizationResult(
            False, amount_decision.response_code,
            message=amount_decision.response_message,
            transaction=txn, amount_decision=amount_decision)

    # ── 2. Identification carte CB + règles GIE CB ────────────────────────────
    card = card_db.get_card(pan)
    aid_hex = None
    contactless_cumul = 0
    consecutive_offline = 0

    if card:
        aid_hex = card.aid
        contactless_cumul = card.contactless_cumul
        consecutive_offline = card.consecutive_offline

    # Extraire AID depuis champ 55 si présent
    if field_55:
        try:
            tlv_list = parse(field_55)
            aid_tag = find_tag(tlv_list, 0x4F)
            if aid_tag:
                aid_hex = aid_tag.value.hex().upper()
        except Exception:
            pass

    cb_result = evaluate_cb_rules(
        pan=pan, amount=amount, currency=currency,
        transaction_type=transaction_type,
        mcc=mcc, aid_hex=aid_hex,
        is_contactless=is_contactless,
        contactless_cumul=contactless_cumul,
        consecutive_offline=consecutive_offline,
        pos_entry_mode=pos_entry_mode,
    )

    # Enrichir la transaction avec les infos CB
    card_info = identify_card(pan, aid_hex)
    txn.cb_scheme = card_info.scheme
    txn.cb_brand = card_info.brand
    txn.cb_service_indicator = cb_result.service_indicator
    txn.cb_sca_exemption = cb_result.sca_exemption
    txn.cb_floor_limit = cb_result.floor_limit_applied
    txn.cb_is_contactless = cb_result.is_contactless
    txn.cb_response_code = cb_result.cb_response_code
    txn.cb_decline_reason = cb_result.cb_decline_reason

    txn.log_event("GIECB_EVALUATION",
                  f"Réseau: {card_info.scheme} | SCA: {cb_result.sca_exemption or 'none'}",
                  level="INFO" if cb_result.allowed else "WARN",
                  data={
                      "scheme": card_info.scheme,
                      "brand": card_info.brand,
                      "aid": aid_hex,
                      "allowed": cb_result.allowed,
                      "service_indicator": cb_result.service_indicator,
                      "sca_exemption": cb_result.sca_exemption,
                      "floor_limit": cb_result.floor_limit_applied,
                      "is_contactless": cb_result.is_contactless,
                      "contactless_cumul": contactless_cumul,
                      "consecutive_offline": consecutive_offline,
                      "cb_response_code": cb_result.cb_response_code,
                      "cb_decline_reason": cb_result.cb_decline_reason,
                  })

    if not cb_result.allowed:
        code = cb_result.response_code
        msg = CB_RESPONSE_CODES.get(cb_result.cb_response_code, cb_result.response_message)
        txn.decline(code, msg)
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — règles GIE CB",
                      level="ERROR",
                      data={"response_code": code, "reason": msg})
        transaction_log.add(txn)
        return AuthorizationResult(False, code, message=msg,
                                   transaction=txn, amount_decision=amount_decision,
                                   cb_result=cb_result)

    # ── 3. Validation état de la carte ───────────────────────────────────────
    txn.log_event("CARD_LOOKUP",
                  "Carte trouvée" if card else "Carte introuvable",
                  level="INFO" if card else "ERROR",
                  data={"found": bool(card),
                        "status": card.status if card else None,
                        "expiry": card.expiry if card else None})

    if not card:
        txn.decline("14", "Card not found")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — carte introuvable",
                      level="ERROR", data={"response_code": "14"})
        transaction_log.add(txn)
        return AuthorizationResult(False, "14", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)

    if card.status == CardStatus.LOST:
        txn.decline("41", "Lost card")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — carte déclarée perdue",
                      level="ERROR", data={"response_code": "41", "card_status": "LOST"})
        transaction_log.add(txn)
        return AuthorizationResult(False, "41", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)
    if card.status == CardStatus.STOLEN:
        txn.decline("43", "Stolen card")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — carte déclarée volée",
                      level="ERROR", data={"response_code": "43", "card_status": "STOLEN"})
        transaction_log.add(txn)
        return AuthorizationResult(False, "43", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)
    if card.status in (CardStatus.BLOCKED, CardStatus.RESTRICTED):
        txn.decline("62", "Card blocked/restricted")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — carte bloquée/restreinte",
                      level="ERROR",
                      data={"response_code": "62", "card_status": card.status})
        transaction_log.add(txn)
        return AuthorizationResult(False, "62", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)
    if card.is_expired():
        txn.decline("54", "Expired card")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — carte expirée",
                      level="ERROR",
                      data={"response_code": "54", "expiry": card.expiry})
        transaction_log.add(txn)
        return AuthorizationResult(False, "54", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)
    if amount <= 0:
        txn.decline("13", "Invalid amount")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — montant invalide",
                      level="ERROR", data={"response_code": "13", "amount": amount})
        transaction_log.add(txn)
        return AuthorizationResult(False, "13", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)
    if amount > Config.MAX_TRANSACTION_AMOUNT:
        txn.decline("61", "Amount exceeds maximum transaction limit")
        txn.log_event("AUTHORIZATION_DECISION", "Refusé — montant trop élevé",
                      level="ERROR",
                      data={"response_code": "61", "amount": amount,
                            "max_allowed": Config.MAX_TRANSACTION_AMOUNT})
        transaction_log.add(txn)
        return AuthorizationResult(False, "61", transaction=txn,
                                   amount_decision=amount_decision, cb_result=cb_result)

    # ── 4. Traitement EMV (champ 55) ─────────────────────────────────────────
    emv_parsed = None
    atc_int = 0
    arqc_hex = None
    issuer_auth_data_hex = None
    arpc_hex = None

    if field_55:
        emv_parsed = _parse_emv_field55(field_55)
        if emv_parsed is None:
            txn.error("Failed to parse EMV data (field 55)")
            txn.log_event("EMV_PARSING", "Échec du parsing du champ 55",
                          level="ERROR", data={"field_55_length": len(field_55)})
            transaction_log.add(txn)
            return AuthorizationResult(False, "30", transaction=txn,
                                       amount_decision=amount_decision, cb_result=cb_result)

        txn.log_event("EMV_PARSING", "Champ 55 parsé avec succès", data={
            "has_atc": bool(emv_parsed.get("atc")),
            "has_cryptogram": bool(emv_parsed.get("cryptogram")),
            "has_tvr": bool(emv_parsed.get("tvr")),
            "aid_card": (emv_parsed.get("aid_card") or b"").hex().upper() or None,
        })

        if emv_parsed.get("atc"):
            atc_int = int.from_bytes(emv_parsed["atc"], "big")
            txn.atc = atc_int
            if atc_int <= card.last_atc:
                txn.decline("05", "ATC replay detected")
                txn.log_event("ATC_CHECK", "ATC replay détecté — refus",
                              level="ERROR",
                              data={"atc_received": atc_int,
                                    "last_atc": card.last_atc})
                transaction_log.add(txn)
                return AuthorizationResult(False, "05", transaction=txn,
                                           amount_decision=amount_decision,
                                           cb_result=cb_result)
            txn.log_event("ATC_CHECK", f"ATC valide : {atc_int}",
                          data={"atc": atc_int, "last_atc": card.last_atc})

        if emv_parsed.get("cryptogram_info"):
            cid = emv_parsed["cryptogram_info"][0] & 0xC0
            if cid == 0x00:
                txn.decline("05", "Card requested offline decline (AAC)")
                txn.log_event("ARQC_VERIFICATION", "AAC reçu — décision hors-ligne refus",
                              level="ERROR", data={"cid": hex(cid)})
                transaction_log.add(txn)
                return AuthorizationResult(False, "05", transaction=txn,
                                           amount_decision=amount_decision,
                                           cb_result=cb_result)

        if emv_parsed.get("cryptogram") and not skip_crypto:
            arqc_bytes = emv_parsed["cryptogram"]
            arqc_hex = arqc_bytes.hex().upper()
            txn.arqc = arqc_hex
            try:
                arqc_data = _build_arqc_data(emv_parsed, amount, currency)
                valid = verify_arqc(
                    master_key=card.master_key_ac, pan=pan,
                    psn=card.psn, atc=atc_int,
                    transaction_data=arqc_data, arqc_received=arqc_bytes)
                txn.log_event("ARQC_VERIFICATION",
                              "ARQC valide" if valid else "ARQC invalide",
                              level="INFO" if valid else "ERROR",
                              data={"valid": valid, "arqc": arqc_hex})
                if not valid:
                    txn.decline("05", "Cryptogram verification failed")
                    txn.log_event("AUTHORIZATION_DECISION",
                                  "Refusé — cryptogramme invalide",
                                  level="ERROR",
                                  data={"response_code": "05"})
                    transaction_log.add(txn)
                    return AuthorizationResult(False, "05", transaction=txn,
                                               amount_decision=amount_decision,
                                               cb_result=cb_result)
            except CryptoError as e:
                logger.error("Crypto error: %s", str(e))
                txn.log_event("ARQC_VERIFICATION",
                              f"Erreur crypto (non bloquante) : {e}",
                              level="WARN")
        elif skip_crypto and emv_parsed.get("cryptogram"):
            txn.log_event("ARQC_VERIFICATION",
                          "Vérification ARQC ignorée (skip_crypto=True)",
                          level="WARN",
                          data={"arqc": emv_parsed["cryptogram"].hex().upper()})

        tvr = emv_parsed.get("tvr")
        if tvr:
            flags = check_tvr(tvr)
            critical = [f for f in flags if any(
                kw in f.lower() for kw in ["sda failed", "dda failed", "cda failed",
                                           "exception", "pin try"])]
            txn.log_event("TVR_ANALYSIS",
                          f"{len(critical)} flag(s) critique(s) sur {len(flags)}",
                          level="ERROR" if critical else "INFO",
                          data={"tvr": tvr.hex().upper() if tvr else None,
                                "all_flags": flags,
                                "critical_flags": critical})
            if critical:
                txn.decline("05", "Risk flag: " + critical[0])
                txn.log_event("AUTHORIZATION_DECISION",
                              "Refusé — flag TVR critique",
                              level="ERROR",
                              data={"response_code": "05",
                                    "flag": critical[0]})
                transaction_log.add(txn)
                return AuthorizationResult(False, "05", transaction=txn,
                                           amount_decision=amount_decision,
                                           cb_result=cb_result)
    else:
        txn.log_event("EMV_PARSING", "Aucun champ 55 — transaction non-EMV")

    # ── 5. Contrôle provision ─────────────────────────────────────────────────
    txn.log_event("BALANCE_CHECK",
                  "Solde suffisant" if card.can_spend(amount)
                  else "Solde insuffisant ou limite journalière dépassée",
                  level="INFO" if card.can_spend(amount) else "WARN",
                  data={
                      "balance": card.balance,
                      "daily_spent": card.daily_spent,
                      "daily_limit": card.daily_limit,
                      "amount": amount,
                      "can_spend": card.can_spend(amount),
                  })

    if transaction_type in ["00", "09", "01"]:
        if not card.can_spend(amount):
            code = "51" if card.balance < amount else "61"
            reason = "Insufficient funds" if code == "51" else "Daily limit exceeded"
            txn.decline(code, reason)
            txn.log_event("AUTHORIZATION_DECISION",
                          f"Refusé — {reason}",
                          level="ERROR",
                          data={"response_code": code, "reason": reason})
            transaction_log.add(txn)
            return AuthorizationResult(False, code, transaction=txn,
                                       amount_decision=amount_decision,
                                       cb_result=cb_result)

    # ── 6. Génération ARPC ────────────────────────────────────────────────────
    auth_code = generate_auth_code()
    if field_55 and arqc_hex and card:
        try:
            from emv.crypto import derive_udk, derive_session_key, generate_arpc
            udk = derive_udk(card.master_key_ac, pan, card.psn)
            session_key = derive_session_key(udk, atc_int, key_type="AC")
            arqc_bytes_val = bytes.fromhex(arqc_hex)
            arpc_bytes = generate_arpc(session_key, arqc_bytes_val, b'\x30\x30')
            arpc_hex = arpc_bytes.hex().upper()
            issuer_auth_data_hex = (arpc_bytes + b'\x30\x30').hex().upper()
            txn.log_event("ARPC_GENERATION", "ARPC généré avec succès",
                          data={"arpc": arpc_hex})
        except Exception as e:
            logger.error("Failed to generate ARPC: %s", str(e))
            txn.log_event("ARPC_GENERATION",
                          f"Génération ARPC échouée (non bloquante) : {e}",
                          level="WARN")

    # ── 7. Débitage et mise à jour compteurs CB ───────────────────────────────
    if transaction_type in ["00", "09"]:
        card.debit(amount)
    if atc_int > 0:
        card_db.update_atc(pan, atc_int)

    # Mise à jour compteurs sans contact CB
    if cb_result.is_contactless:
        if amount_decision.auth_path == "OFFLINE":
            card.update_contactless(amount)
        else:
            card.reset_contactless()

    txn.approve(auth_code, arpc=arpc_hex, issuer_auth_data=issuer_auth_data_hex)
    txn.log_event("AUTHORIZATION_DECISION", "Approuvé",
                  level="INFO",
                  data={
                      "response_code": "00",
                      "auth_code": auth_code,
                      "arpc_generated": bool(arpc_hex),
                      "balance_after": card.balance,
                      "daily_spent_after": card.daily_spent,
                  })
    transaction_log.add(txn)

    logger.info("Approved: ID=%s PAN=...%s Amt=%d Auth=%s Tier=%s Path=%s CB=%s SCA=%s",
                txn.id, pan[-4:], amount, auth_code,
                amount_decision.tier.name, amount_decision.auth_path,
                txn.cb_brand, cb_result.sca_exemption)

    # ── 8. Notification webhook (A1) ──────────────────────────────────────────
    try:
        from emv.webhooks import notify as _webhook_notify
        _webhook_notify("authorization.approved", {
            "transaction_id": txn.id,
            "rrn": txn.rrn,
            "pan_masked": "*" * (len(pan) - 4) + pan[-4:],
            "amount": amount,
            "currency": currency,
            "auth_code": auth_code,
            "tier": amount_decision.tier.name,
            "cb_scheme": txn.cb_scheme,
        })
    except Exception:
        pass

    return AuthorizationResult(
        True, "00", auth_code=auth_code,
        issuer_auth_data=issuer_auth_data_hex, arpc=arpc_hex,
        transaction=txn, amount_decision=amount_decision,
        cb_result=cb_result)
