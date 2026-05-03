"""
ISO 8583 Message Parser and Builder
Supports Financial Transaction Message formats 0100/0110 (Authorization Request/Response)
"""

import struct
import json
from datetime import datetime

ISO8583_FIELDS = {
    2:  {"name": "Primary Account Number (PAN)", "type": "LLVAR", "encoding": "ascii"},
    3:  {"name": "Processing Code", "type": "n", "length": 6},
    4:  {"name": "Amount, Transaction", "type": "n", "length": 12},
    5:  {"name": "Amount, Settlement", "type": "n", "length": 12},
    6:  {"name": "Amount, Cardholder Billing", "type": "n", "length": 12},
    7:  {"name": "Transmission Date & Time", "type": "n", "length": 10},
    11: {"name": "System Trace Audit Number", "type": "n", "length": 6},
    12: {"name": "Local Transaction Time", "type": "n", "length": 6},
    13: {"name": "Local Transaction Date", "type": "n", "length": 4},
    14: {"name": "Expiration Date", "type": "n", "length": 4},
    15: {"name": "Settlement Date", "type": "n", "length": 4},
    18: {"name": "Merchant Type", "type": "n", "length": 4},
    22: {"name": "Point of Service Entry Mode", "type": "n", "length": 3},
    23: {"name": "Card Sequence Number", "type": "n", "length": 3},
    25: {"name": "Point of Service Condition Code", "type": "n", "length": 2},
    32: {"name": "Acquiring Institution ID Code", "type": "LLVAR", "encoding": "ascii"},
    35: {"name": "Track 2 Data", "type": "LLVAR", "encoding": "ascii"},
    37: {"name": "Retrieval Reference Number", "type": "an", "length": 12},
    38: {"name": "Authorization Identification Response", "type": "an", "length": 6},
    39: {"name": "Response Code", "type": "an", "length": 2},
    41: {"name": "Card Acceptor Terminal ID", "type": "ans", "length": 8},
    42: {"name": "Card Acceptor ID Code", "type": "ans", "length": 15},
    43: {"name": "Card Acceptor Name/Location", "type": "ans", "length": 40},
    49: {"name": "Currency Code, Transaction", "type": "n", "length": 3},
    52: {"name": "Personal ID Number (PIN) Data", "type": "b", "length": 8},
    55: {"name": "ICC Data (EMV)", "type": "LLLVAR", "encoding": "hex"},
    58: {"name": "National Point of Service Geographic Data", "type": "LLVAR", "encoding": "ascii"},
    60: {"name": "Additional POS Information", "type": "LLLVAR", "encoding": "ascii"},
    90: {"name": "Original Data Elements", "type": "n", "length": 42},
    95: {"name": "Replacement Amounts", "type": "n", "length": 42},
    98: {"name": "Payee", "type": "ans", "length": 25},
    100: {"name": "Receiving Institution ID Code", "type": "LLVAR", "encoding": "ascii"},
    102: {"name": "Account Identification 1", "type": "LLVAR", "encoding": "ascii"},
    103: {"name": "Account Identification 2", "type": "LLVAR", "encoding": "ascii"},
    128: {"name": "MAC 2", "type": "b", "length": 8},
}

MTI_DESCRIPTIONS = {
    "0100": "Authorization Request",
    "0110": "Authorization Response",
    "0200": "Financial Transaction Request",
    "0210": "Financial Transaction Response",
    "0400": "Reversal Request",
    "0410": "Reversal Response",
    "0420": "Reversal Advice",
    "0430": "Reversal Advice Response",
    "0800": "Network Management Request",
    "0810": "Network Management Response",
}

REVERSAL_RESPONSE_CODES = {
    "00": "Redressement accepté",
    "25": "Transaction originale introuvable",
    "40": "Transaction non redressable",
    "56": "Aucune réponse précédente (déjà redressé)",
    "61": "Montant de redressement supérieur au montant original",
}

PROCESSING_CODES = {
    "00": "Purchase",
    "01": "Cash Advance",
    "09": "Purchase with Cashback",
    "10": "Account Funding",
    "20": "Refund / Credit",
    "22": "Balance Inquiry",
    "28": "Payment",
    "30": "Account Inquiry",
    "40": "Cash Disbursement",
}


class ISO8583Message:
    def __init__(self, mti="0100"):
        self.mti = mti
        self.fields = {}

    def set_field(self, field_num, value):
        self.fields[field_num] = value

    def get_field(self, field_num):
        return self.fields.get(field_num)

    @property
    def pan(self):
        return self.fields.get(2, "")

    @property
    def processing_code(self):
        return self.fields.get(3, "000000")

    @property
    def amount(self):
        try:
            return int(self.fields.get(4, "0"))
        except (ValueError, TypeError):
            return 0

    @property
    def currency_code(self):
        return self.fields.get(49, "840")

    @property
    def terminal_id(self):
        return self.fields.get(41, "").strip()

    @property
    def merchant_id(self):
        return self.fields.get(42, "").strip()

    @property
    def merchant_name(self):
        loc = self.fields.get(43, "")
        return loc[:25].strip() if loc else ""

    @property
    def emv_data(self):
        return self.fields.get(55)

    @property
    def expiry(self):
        return self.fields.get(14, "")

    @property
    def pos_entry_mode(self):
        return self.fields.get(22, "051")

    @property
    def rrn(self):
        return self.fields.get(37, "")

    @property
    def transaction_type(self):
        pc = self.processing_code
        return pc[:2] if pc else "00"

    def to_dict(self):
        result = {"mti": self.mti, "fields": {}}
        for field_num, value in sorted(self.fields.items()):
            field_info = ISO8583_FIELDS.get(field_num, {})
            result["fields"][str(field_num)] = {
                "name": field_info.get("name", "Field {}".format(field_num)),
                "value": value if not isinstance(value, bytes) else value.hex().upper(),
            }
        return result

    def to_response(self, response_code, auth_code=None, field_55_response=None):
        """Construit le message de réponse correspondant à ce MTI."""
        response_mti = {
            "0100": "0110",
            "0200": "0210",
            "0400": "0410",
            "0420": "0430",
            "0800": "0810",
        }.get(self.mti, "0110")

        resp = ISO8583Message(mti=response_mti)
        for fnum in [2, 3, 4, 7, 11, 12, 13, 18, 22, 25, 37, 41, 42, 49]:
            if fnum in self.fields:
                resp.set_field(fnum, self.fields[fnum])

        # Field 90 (Original Data Elements) — écho pour les reversals
        if self.mti in ("0400", "0420") and 90 in self.fields:
            resp.set_field(90, self.fields[90])

        resp.set_field(39, response_code)
        if auth_code:
            resp.set_field(38, str(auth_code).zfill(6)[:6])
        if field_55_response:
            resp.set_field(55, field_55_response)

        return resp

    @property
    def original_transaction_id(self):
        """Extrait l'ID de transaction originale depuis le champ 90 ou le champ custom."""
        return self.fields.get(125)  # champ custom pour l'ID interne

    @property
    def reversal_amount(self):
        """Montant de redressement depuis le champ 95 (Replacement Amounts)."""
        val = self.fields.get(95)
        if val:
            try:
                return int(str(val)[:12])
            except (ValueError, TypeError):
                pass
        return None

    @property
    def is_reversal(self):
        return self.mti in ("0400", "0420")

    @property
    def is_advice(self):
        return self.mti in ("0420", "0430")


def parse_from_dict(data):
    """Parse an ISO 8583 message from a dictionary representation."""
    msg = ISO8583Message(mti=data.get("mti", "0100"))
    fields = data.get("fields", {})
    for field_num_str, value in fields.items():
        try:
            field_num = int(field_num_str)
            if isinstance(value, dict):
                msg.set_field(field_num, value.get("value", value))
            else:
                msg.set_field(field_num, value)
        except (ValueError, TypeError):
            continue
    return msg


def build_authorization_request(pan, amount, currency_code, processing_code="000000",
                                 expiry=None, terminal_id=None, merchant_id=None,
                                 merchant_name=None, emv_data=None, stan=None):
    """Build a standard ISO 8583 0100 authorization request."""
    msg = ISO8583Message(mti="0100")
    msg.set_field(2, pan)
    msg.set_field(3, processing_code)
    msg.set_field(4, str(amount).zfill(12))

    now = datetime.utcnow()
    msg.set_field(7, now.strftime("%m%d%H%M%S"))
    msg.set_field(11, stan or str(now.microsecond)[:6].zfill(6))
    msg.set_field(12, now.strftime("%H%M%S"))
    msg.set_field(13, now.strftime("%m%d"))

    if expiry:
        msg.set_field(14, expiry)

    msg.set_field(22, "051")
    msg.set_field(25, "00")

    if terminal_id:
        msg.set_field(41, terminal_id[:8].ljust(8))
    if merchant_id:
        msg.set_field(42, merchant_id[:15].ljust(15))
    if merchant_name:
        msg.set_field(43, merchant_name[:40].ljust(40))

    msg.set_field(49, str(currency_code).zfill(3))

    if emv_data:
        msg.set_field(55, emv_data)

    return msg
