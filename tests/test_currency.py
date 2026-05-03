"""
Tests — E8 Conversion multi-devises
Couvre : get_rates, convert (même devise, EUR↔USD, taux, arrondi),
         cas d'erreur, endpoints REST.
"""
import pytest
from emv.currency import convert, get_rates, EXCHANGE_RATES, get_currency_info


# ── get_rates ─────────────────────────────────────────────────────────────────

class TestGetRates:
    def test_returns_all_currencies(self):
        data = get_rates()
        assert "rates" in data
        assert "978" in data["rates"]   # EUR
        assert "840" in data["rates"]   # USD

    def test_currencies_count(self):
        data = get_rates()
        assert data["currencies"] == len(EXCHANGE_RATES)

    def test_each_rate_has_cross(self):
        data = get_rates()
        eur = data["rates"]["978"]
        assert "cross_rates" in eur
        assert "840" in eur["cross_rates"]

    def test_base_is_eur(self):
        data = get_rates()
        assert data["base"] == "EUR"

    def test_eur_rate_to_self(self):
        # EUR → EUR doit donner 1.0 via cross
        data = get_rates()
        eur = data["rates"]["978"]
        assert eur["rate_to_eur"] == 1.0

    def test_generated_at_present(self):
        data = get_rates()
        assert "generated_at" in data


# ── get_currency_info ─────────────────────────────────────────────────────────

class TestGetCurrencyInfo:
    def test_eur_info(self):
        info = get_currency_info("978")
        assert info["code"] == "EUR"
        assert info["symbol"] == "€"

    def test_usd_info(self):
        info = get_currency_info("840")
        assert info["code"] == "USD"

    def test_unknown_currency(self):
        info = get_currency_info("000")
        assert info is None

    def test_short_code_padded(self):
        info = get_currency_info("12")   # DZD = "012"
        assert info is not None
        assert info["code"] == "DZD"


# ── convert — même devise ─────────────────────────────────────────────────────

class TestConvertSameCurrency:
    def test_same_currency_no_change(self):
        r = convert(5000, "978", "978")
        assert r["converted_amount"] == 5000

    def test_same_currency_rate_is_one(self):
        r = convert(5000, "978", "978")
        assert r["rate"] == 1.0

    def test_same_currency_note(self):
        r = convert(5000, "978", "978")
        assert r.get("note") == "same_currency"


# ── convert — EUR → USD ───────────────────────────────────────────────────────

class TestConvertEurToUsd:
    def test_convert_returns_positive(self):
        r = convert(10000, "978", "840")
        assert r["converted_amount"] > 0

    def test_convert_from_to_codes(self):
        r = convert(10000, "978", "840")
        assert r["from_code"] == "EUR"
        assert r["to_code"] == "USD"

    def test_convert_rate_present(self):
        r = convert(10000, "978", "840")
        assert "rate" in r
        assert r["rate"] > 0

    def test_convert_formatted_present(self):
        r = convert(10000, "978", "840")
        assert "EUR" in r["original_formatted"]
        assert "USD" in r["converted_formatted"]

    def test_convert_eur_to_usd_less_than_eur(self):
        # 1 EUR = ~1.08 USD, so 100 EUR should give ~108 USD (in centimes)
        r = convert(10000, "978", "840")  # 100 EUR
        # USD rate < 1 relative to EUR, so 10000 EUR centimes → more USD centimes
        assert r["converted_amount"] != 10000


# ── convert — USD → EUR ───────────────────────────────────────────────────────

class TestConvertUsdToEur:
    def test_usd_to_eur(self):
        r = convert(10000, "840", "978")  # 100 USD → EUR
        assert r["converted_amount"] > 0
        assert r["from_code"] == "USD"
        assert r["to_code"] == "EUR"

    def test_round_trip_approximate(self):
        # EUR → USD → EUR should be approximately the same
        r1 = convert(10000, "978", "840")
        r2 = convert(r1["converted_amount"], "840", "978")
        # Allow 2% tolerance for rounding
        assert abs(r2["converted_amount"] - 10000) <= 200


# ── convert — autres paires ────────────────────────────────────────────────────

class TestConvertOtherPairs:
    def test_gbp_to_chf(self):
        r = convert(5000, "826", "756")
        assert r["converted_amount"] > 0
        assert r["from_code"] == "GBP"
        assert r["to_code"] == "CHF"

    def test_jpy_large_amount(self):
        r = convert(100000, "392", "978")  # 1000 JPY → EUR
        assert r["converted_amount"] > 0

    def test_mad_to_eur(self):
        r = convert(50000, "504", "978")  # 500 MAD → EUR
        assert r["from_code"] == "MAD"


# ── convert — erreurs ─────────────────────────────────────────────────────────

class TestConvertErrors:
    def test_unknown_from_currency(self):
        with pytest.raises(ValueError, match="source"):
            convert(1000, "000", "978")

    def test_unknown_to_currency(self):
        with pytest.raises(ValueError, match="cible"):
            convert(1000, "978", "000")

    def test_both_unknown(self):
        with pytest.raises(ValueError):
            convert(1000, "111", "222")


# ── Endpoints REST ────────────────────────────────────────────────────────────

class TestCurrencyEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client

    def test_get_rates_endpoint(self):
        r = self.client.get("/api/v1/currency/rates")
        assert r.status_code == 200
        data = r.get_json()
        assert "rates" in data
        assert "978" in data["rates"]

    def test_convert_endpoint_eur_to_usd(self):
        r = self.client.post("/api/v1/currency/convert",
                             json={"amount": 5000, "from_currency": "978",
                                   "to_currency": "840"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["from_code"] == "EUR"
        assert data["to_code"] == "USD"
        assert data["converted_amount"] > 0

    def test_convert_endpoint_same_currency(self):
        r = self.client.post("/api/v1/currency/convert",
                             json={"amount": 5000, "from_currency": "978",
                                   "to_currency": "978"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["converted_amount"] == 5000

    def test_convert_endpoint_invalid_amount(self):
        r = self.client.post("/api/v1/currency/convert",
                             json={"amount": "abc", "from_currency": "978",
                                   "to_currency": "840"})
        assert r.status_code == 400

    def test_convert_endpoint_zero_amount(self):
        r = self.client.post("/api/v1/currency/convert",
                             json={"amount": 0, "from_currency": "978",
                                   "to_currency": "840"})
        assert r.status_code == 400

    def test_convert_endpoint_unknown_currency(self):
        r = self.client.post("/api/v1/currency/convert",
                             json={"amount": 1000, "from_currency": "000",
                                   "to_currency": "978"})
        assert r.status_code == 400

    def test_convert_endpoint_rate_description(self):
        r = self.client.post("/api/v1/currency/convert",
                             json={"amount": 10000, "from_currency": "978",
                                   "to_currency": "840"})
        data = r.get_json()
        assert "rate_description" in data
        assert "EUR" in data["rate_description"]
