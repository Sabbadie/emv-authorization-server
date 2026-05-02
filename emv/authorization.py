"""
EMV Authorization Logic
Handles the full authorization decision process including:
- Card validation
- Risk checks
- Cryptogram verification
- Response generation
"""

import uuid
import logging
from datetime import datetime

from emv.tlv import parse, find_tag, extract_emv_fields
from emv.crypto import verify_arqc, generate_issuer_auth_data, CryptoError
from emv.data_elements import CRYPTOGRAM_TYPE
from models.card import CardStatus, card_db
from models.transaction import Transaction, TransactionStatus, transaction_log
from config import Config

logger = logging.getLogger(__name__)


class AuthorizationResult:
    def __init__(self, approved, response_code, auth_code=None,
                 issuer_auth_data=None, arpc=None, message=None,
                 transaction=None):
        self.approved = approved
        self.response_code = response_code
        self.auth_code = auth_code
        self.issuer_auth_data = issuer_auth_data
        self.arpc = arpc
        self.message = message or Config.RESPONSE_CODES.get(response_code, "Unknown")
        self.transaction = transaction

    def to_dict(self):
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
        if self.transaction:
            result["transaction"] = self.transaction.to_dict()
        return result


def generate_auth_code():
    return str(uuid.uuid4().int)[:6].zfill(6)


def _parse_emv_field55(field_55_hex):
    """Parse ISO 8583 field 55 (EMV data) and extract key data elements."""
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
            "all_fields": fields,
        }
    except Exception as e:
        logger.error("Failed to parse EMV field 55: %s", str(e))
        return None


def _build_arqc_data(emv_parsed, amount, currency_code):
    """
    Build the data block used to compute ARQC.
    Per CDOL1: 9F02 + 9F03 + 9F1A + 95 + 5F2A + 9A + 9C + 9F37
    """
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
    """
    Analyze Terminal Verification Results (TVR) for risk flags.
    Returns list of active flags.
    """
    if not tvr_bytes or len(tvr_bytes) < 5:
        return []

    flags = []
    b1, b2, b3, b4, b5 = tvr_bytes[0], tvr_bytes[1], tvr_bytes[2], tvr_bytes[3], tvr_bytes[4]

    if b1 & 0x80: flags.append("Offline data authentication not performed")
    if b1 & 0x40: flags.append("SDA failed")
    if b1 & 0x20: flags.append("ICC data missing")
    if b1 & 0x10: flags.append("Card appears on terminal exception file")
    if b1 & 0x08: flags.append("DDA failed")
    if b1 & 0x04: flags.append("CDA failed")
    if b2 & 0x80: flags.append("ICC and terminal have different application versions")
    if b2 & 0x40: flags.append("Expired application")
    if b2 & 0x20: flags.append("Application not yet effective")
    if b2 & 0x10: flags.append("Requested service not allowed for card product")
    if b2 & 0x08: flags.append("New card")
    if b3 & 0x80: flags.append("Cardholder verification was not successful")
    if b3 & 0x40: flags.append("Unrecognized CVM")
    if b3 & 0x20: flags.append("PIN try limit exceeded")
    if b3 & 0x10: flags.append("PIN entry required and PIN pad not present or not working")
    if b3 & 0x08: flags.append("PIN entry required, PIN pad present, but PIN was not entered")
    if b3 & 0x04: flags.append("Online PIN entered")
    if b4 & 0x80: flags.append("Transaction exceeds floor limit")
    if b4 & 0x40: flags.append("Lower consecutive offline limit exceeded")
    if b4 & 0x20: flags.append("Upper consecutive offline limit exceeded")
    if b4 & 0x10: flags.append("Transaction selected randomly for online processing")
    if b4 & 0x08: flags.append("Merchant forced transaction online")
    if b5 & 0x80: flags.append("Default TDOL used")
    if b5 & 0x40: flags.append("Issuer authentication failed")
    if b5 & 0x20: flags.append("Script processing failed before final GENERATE AC")
    if b5 & 0x10: flags.append("Script processing failed after final GENERATE AC")

    return flags


def authorize(pan, amount, currency, transaction_type,
              field_55=None, terminal_id=None, merchant_id=None,
              merchant_name=None, pos_entry_mode="05",
              skip_crypto=False):
    """
    Main authorization function.
    Returns AuthorizationResult.
    """
    pan = pan.replace(" ", "")
    txn = Transaction(
        pan=pan,
        amount=amount,
        currency=currency,
        transaction_type=transaction_type,
        terminal_id=terminal_id,
        merchant_id=merchant_id,
        merchant_name=merchant_name,
        pos_entry_mode=pos_entry_mode,
    )

    card = card_db.get_card(pan)
    if not card:
        txn.decline("14", "Card not found")
        transaction_log.add(txn)
        return AuthorizationResult(False, "14", transaction=txn)

    if card.status == CardStatus.LOST:
        txn.decline("41", "Lost card")
        transaction_log.add(txn)
        return AuthorizationResult(False, "41", transaction=txn)

    if card.status == CardStatus.STOLEN:
        txn.decline("43", "Stolen card")
        transaction_log.add(txn)
        return AuthorizationResult(False, "43", transaction=txn)

    if card.status == CardStatus.BLOCKED:
        txn.decline("62", "Card blocked")
        transaction_log.add(txn)
        return AuthorizationResult(False, "62", transaction=txn)

    if card.status == CardStatus.RESTRICTED:
        txn.decline("62", "Card restricted")
        transaction_log.add(txn)
        return AuthorizationResult(False, "62", transaction=txn)

    if card.is_expired():
        txn.decline("54", "Expired card")
        transaction_log.add(txn)
        return AuthorizationResult(False, "54", transaction=txn)

    if amount <= 0:
        txn.decline("13", "Invalid amount")
        transaction_log.add(txn)
        return AuthorizationResult(False, "13", transaction=txn)

    if amount > Config.MAX_TRANSACTION_AMOUNT:
        txn.decline("61", "Amount exceeds maximum transaction limit")
        transaction_log.add(txn)
        return AuthorizationResult(False, "61", transaction=txn)

    emv_parsed = None
    atc_int = 0
    arqc_hex = None
    issuer_auth_data_hex = None
    arpc_hex = None

    if field_55:
        emv_parsed = _parse_emv_field55(field_55)
        if emv_parsed is None:
            txn.error("Failed to parse EMV data (field 55)")
            transaction_log.add(txn)
            return AuthorizationResult(False, "30", transaction=txn)

        if emv_parsed.get("atc"):
            atc_int = int.from_bytes(emv_parsed["atc"], "big")
            txn.atc = atc_int

            if atc_int <= card.last_atc:
                logger.warning("ATC replay attack detected: received=%d last=%d",
                               atc_int, card.last_atc)
                txn.decline("05", "ATC replay detected")
                transaction_log.add(txn)
                return AuthorizationResult(False, "05", transaction=txn)

        if emv_parsed.get("cryptogram_info"):
            cid = emv_parsed["cryptogram_info"][0] & 0xC0
            crypto_type = CRYPTOGRAM_TYPE.get(cid, "Unknown")
            logger.info("Cryptogram type: %s", crypto_type)

            if cid == 0x00:
                txn.decline("05", "Card requested offline decline (AAC received)")
                transaction_log.add(txn)
                return AuthorizationResult(False, "05", transaction=txn)

        if emv_parsed.get("cryptogram") and not skip_crypto:
            arqc_bytes = emv_parsed["cryptogram"]
            arqc_hex = arqc_bytes.hex().upper()
            txn.arqc = arqc_hex
            psn = card.psn

            try:
                arqc_data = _build_arqc_data(emv_parsed, amount, currency)
                valid = verify_arqc(
                    master_key=card.master_key_ac,
                    pan=pan,
                    psn=psn,
                    atc=atc_int,
                    transaction_data=arqc_data,
                    arqc_received=arqc_bytes
                )
                if not valid:
                    logger.warning("ARQC verification failed for PAN ending %s", pan[-4:])
                    txn.decline("05", "Cryptogram verification failed")
                    transaction_log.add(txn)
                    return AuthorizationResult(False, "05", transaction=txn)
                logger.info("ARQC verified successfully")
            except CryptoError as e:
                logger.error("Crypto error during ARQC verification: %s", str(e))

        tvr = emv_parsed.get("tvr")
        if tvr:
            risk_flags = check_tvr(tvr)
            if risk_flags:
                logger.info("TVR risk flags: %s", risk_flags)
                critical_flags = [f for f in risk_flags if any(
                    kw in f.lower() for kw in ["stolen", "except", "pin try", "sda failed",
                                               "dda failed", "cda failed"]
                )]
                if critical_flags:
                    txn.decline("05", "Risk flag: " + critical_flags[0])
                    transaction_log.add(txn)
                    return AuthorizationResult(False, "05", transaction=txn)

    if transaction_type in ["00", "09", "01"]:
        if not card.can_spend(amount):
            if card.balance < amount:
                txn.decline("51", "Insufficient funds")
                transaction_log.add(txn)
                return AuthorizationResult(False, "51", transaction=txn)
            else:
                txn.decline("61", "Daily limit exceeded")
                transaction_log.add(txn)
                return AuthorizationResult(False, "61", transaction=txn)

    auth_code = generate_auth_code()

    if field_55 and arqc_hex and card:
        try:
            response_code_bytes = b'\x30\x30'
            from emv.crypto import derive_udk, derive_session_key, generate_arpc
            udk = derive_udk(card.master_key_ac, pan, card.psn)
            session_key = derive_session_key(udk, atc_int, key_type="AC")
            arqc_bytes = bytes.fromhex(arqc_hex)
            arpc_bytes = generate_arpc(session_key, arqc_bytes, response_code_bytes)
            arpc_hex = arpc_bytes.hex().upper()
            issuer_auth_data_bytes = arpc_bytes + response_code_bytes
            issuer_auth_data_hex = issuer_auth_data_bytes.hex().upper()
        except Exception as e:
            logger.error("Failed to generate ARPC: %s", str(e))

    if transaction_type in ["00", "09"]:
        card.debit(amount)
    if atc_int > 0:
        card_db.update_atc(pan, atc_int)

    txn.approve(auth_code, arpc=arpc_hex, issuer_auth_data=issuer_auth_data_hex)
    transaction_log.add(txn)

    logger.info("Transaction approved: ID=%s PAN=...%s Amount=%d Auth=%s",
                txn.id, pan[-4:], amount, auth_code)

    return AuthorizationResult(
        True, "00",
        auth_code=auth_code,
        issuer_auth_data=issuer_auth_data_hex,
        arpc=arpc_hex,
        transaction=txn
    )
