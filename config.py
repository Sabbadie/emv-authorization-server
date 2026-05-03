import os


class Config:
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    SECRET_KEY = os.getenv("SECRET_KEY", "emv-auth-server-secret-2024")

    # S1 — Authentification API Key
    # Si vide → pas d'auth requise (mode dev).  Définir EMV_API_KEY en prod.
    API_KEY = os.getenv("EMV_API_KEY", "")

    # S2 — Rate limiting
    RATE_LIMIT_DEFAULT   = os.getenv("RATE_LIMIT_DEFAULT",   "300 per minute")
    RATE_LIMIT_AUTHORIZE = os.getenv("RATE_LIMIT_AUTHORIZE", "30 per minute")
    RATE_LIMIT_BATCH     = os.getenv("RATE_LIMIT_BATCH",     "5 per minute")

    CURRENCY_CODES = {
        "840": "USD",
        "978": "EUR",
        "826": "GBP",
        "756": "CHF",
        "392": "JPY",
        "124": "CAD",
        "036": "AUD",
        "504": "MAD",
        "788": "TND",
        "012": "DZD",
    }

    RESPONSE_CODES = {
        "00": "Approved or completed successfully",
        "01": "Refer to card issuer",
        "02": "Refer to card issuer, special condition",
        "03": "Invalid merchant",
        "04": "Pick up card",
        "05": "Do not honor",
        "06": "Error",
        "07": "Pick up card, special condition",
        "12": "Invalid transaction",
        "13": "Invalid amount",
        "14": "Invalid card number",
        "15": "No such issuer",
        "30": "Format error",
        "41": "Lost card, pick up",
        "43": "Stolen card, pick up",
        "51": "Not sufficient funds",
        "54": "Expired card",
        "55": "Incorrect PIN",
        "57": "Transaction not permitted to cardholder",
        "58": "Transaction not permitted to terminal",
        "61": "Exceeds withdrawal amount limit",
        "62": "Restricted card",
        "65": "Exceeds withdrawal frequency limit",
        "75": "Allowable number of PIN tries exceeded",
        "91": "Issuer or switch inoperative",
        "96": "System malfunction",
    }

    MAX_TRANSACTION_AMOUNT = int(os.getenv("MAX_TRANSACTION_AMOUNT", 1000000))
    DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", 500000))

    MDK_AC  = bytes.fromhex(os.getenv("MDK_AC",  "0123456789ABCDEFFEDCBA9876543210"))
    MDK_ENC = bytes.fromhex(os.getenv("MDK_ENC", "FEDCBA98765432100123456789ABCDEF"))
    MDK_MAC = bytes.fromhex(os.getenv("MDK_MAC", "0123456789ABCDEFFEDCBA9876543210"))

    # Clés CVK (Card Verification Keys) pour CVV/CVC — TEST SEULEMENT
    CVK1 = bytes.fromhex(os.getenv("CVK1", "0123456789ABCDEF"))
    CVK2 = bytes.fromhex(os.getenv("CVK2", "FEDCBA9876543210"))

    ATC_MAX_REPLAY_WINDOW = 10

    # P2 — Persistance
    SNAPSHOT_ENABLED  = os.getenv("SNAPSHOT_ENABLED", "true").lower() == "true"
    SNAPSHOT_INTERVAL = int(os.getenv("SNAPSHOT_INTERVAL_SECS", 120))
