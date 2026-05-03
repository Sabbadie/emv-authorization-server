"""
Conversion multi-devises — E8
Taux de change statiques (référence BCE simulée — mise à jour manuelle).
10 devises supportées, conversion via pivot EUR.
"""
from datetime import datetime

# ── Taux de change en vigueur (vers EUR comme pivot) ──────────────────────────
# Dernière mise à jour fictive : 03/05/2026
EXCHANGE_RATES: dict = {
    "978": {"code": "EUR", "name": "Euro",              "symbol": "€",   "rate_to_eur": 1.000000},
    "840": {"code": "USD", "name": "US Dollar",         "symbol": "$",   "rate_to_eur": 0.924000},
    "826": {"code": "GBP", "name": "Livre Sterling",    "symbol": "£",   "rate_to_eur": 1.168000},
    "756": {"code": "CHF", "name": "Franc Suisse",      "symbol": "CHF", "rate_to_eur": 1.043000},
    "392": {"code": "JPY", "name": "Yen japonais",      "symbol": "¥",   "rate_to_eur": 0.006070},
    "124": {"code": "CAD", "name": "Dollar canadien",   "symbol": "C$",  "rate_to_eur": 0.674000},
    "036": {"code": "AUD", "name": "Dollar australien", "symbol": "A$",  "rate_to_eur": 0.594000},
    "504": {"code": "MAD", "name": "Dirham marocain",   "symbol": "MAD", "rate_to_eur": 0.093000},
    "788": {"code": "TND", "name": "Dinar tunisien",    "symbol": "TND", "rate_to_eur": 0.296000},
    "012": {"code": "DZD", "name": "Dinar algérien",    "symbol": "DZD", "rate_to_eur": 0.006940},
}

RATES_DATE = "2026-05-03"


def get_rates() -> dict:
    """Retourne tous les taux de change disponibles, croisés entre toutes les devises."""
    result = {}
    for code, info in EXCHANGE_RATES.items():
        cross = {}
        for other_code, other_info in EXCHANGE_RATES.items():
            if other_code != code:
                rate = info["rate_to_eur"] / other_info["rate_to_eur"]
                cross[other_code] = {
                    "rate":  round(rate, 6),
                    "code":  other_info["code"],
                    "name":  other_info["name"],
                }
        result[code] = {
            "code":           info["code"],
            "name":           info["name"],
            "symbol":         info["symbol"],
            "rate_to_eur":    info["rate_to_eur"],
            "cross_rates":    cross,
        }
    return {
        "rates":        result,
        "base":         "EUR",
        "date":         RATES_DATE,
        "currencies":   len(EXCHANGE_RATES),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def get_currency_info(currency_code: str) -> dict | None:
    return EXCHANGE_RATES.get(str(currency_code).zfill(3))


def convert(amount_centimes: int, from_currency: str,
            to_currency: str) -> dict:
    """
    Convertit un montant (en centimes) d'une devise source vers une devise cible.
    La conversion utilise l'EUR comme pivot.

    Args:
        amount_centimes: montant en centimes de la devise source
        from_currency:   code ISO 4217 numérique (ex: "978" pour EUR)
        to_currency:     code ISO 4217 numérique cible

    Returns:
        dict avec original_amount, converted_amount, rate, etc.

    Raises:
        ValueError: devise inconnue
    """
    from_c = str(from_currency).zfill(3)
    to_c   = str(to_currency).zfill(3)

    if from_c not in EXCHANGE_RATES:
        raise ValueError(f"Devise source inconnue : {from_c}")
    if to_c not in EXCHANGE_RATES:
        raise ValueError(f"Devise cible inconnue : {to_c}")

    from_info = EXCHANGE_RATES[from_c]
    to_info   = EXCHANGE_RATES[to_c]

    if from_c == to_c:
        return {
            "original_amount":    amount_centimes,
            "original_formatted": "{:.2f} {}".format(amount_centimes / 100, from_info["code"]),
            "converted_amount":   amount_centimes,
            "converted_formatted":"{:.2f} {}".format(amount_centimes / 100, to_info["code"]),
            "from_currency":      from_c,
            "from_code":          from_info["code"],
            "to_currency":        to_c,
            "to_code":            to_info["code"],
            "rate":               1.0,
            "rate_description":   "Même devise — pas de conversion",
            "note":               "same_currency",
        }

    # Conversion via EUR : amount × (from_rate / to_rate)
    rate = from_info["rate_to_eur"] / to_info["rate_to_eur"]
    converted_centimes = round(amount_centimes * rate)

    return {
        "original_amount":     amount_centimes,
        "original_formatted":  "{:.2f} {}".format(amount_centimes / 100, from_info["code"]),
        "converted_amount":    converted_centimes,
        "converted_formatted": "{:.2f} {}".format(converted_centimes / 100, to_info["code"]),
        "from_currency":       from_c,
        "from_code":           from_info["code"],
        "from_name":           from_info["name"],
        "to_currency":         to_c,
        "to_code":             to_info["code"],
        "to_name":             to_info["name"],
        "rate":                round(rate, 6),
        "rate_description":    "1 {} = {:.6f} {}".format(
            from_info["code"], rate, to_info["code"]),
        "rates_date":          RATES_DATE,
    }
