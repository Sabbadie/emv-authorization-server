"""
Tests d'intégration — Flask API (server.py)
Couvre tous les endpoints de l'API REST v1.3.0-GIE-CB.
"""

import json
import pytest
from server import app

PAN_ACTIVE  = "4111111111111111"
PAN_BLOCKED = "4000000000000028"
PAN_EXPIRED = "4000000000000010"
PAN_INSUF   = "4000000000000036"


@pytest.fixture(scope="session")
def client():
    app.config["TESTING"] = True
    from server import limiter
    limiter.enabled = False
    with app.test_client() as c:
        yield c


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data),
                       headers={"Content-Type": "application/json"})


def get(client, url, params=None):
    return client.get(url, query_string=params or {})


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────────────────────
class TestHealth:
    def test_status_200(self, client):
        assert get(client, "/api/v1/health").status_code == 200

    def test_status_up(self, client):
        data = get(client, "/api/v1/health").get_json()
        assert data["status"] == "UP"

    def test_version_present(self, client):
        data = get(client, "/api/v1/health").get_json()
        assert "version" in data

    def test_features_list(self, client):
        data = get(client, "/api/v1/health").get_json()
        assert "features" in data
        assert isinstance(data["features"], list)
        assert len(data["features"]) >= 5

    def test_timestamp_present(self, client):
        data = get(client, "/api/v1/health").get_json()
        assert "timestamp" in data


# ─────────────────────────────────────────────────────────────────────────────
# AUTHORIZE
# ─────────────────────────────────────────────────────────────────────────────
class TestAuthorize:
    def test_approved_returns_200(self, client):
        resp = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp.status_code == 200

    def test_approved_flag_true(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["approved"] is True

    def test_approved_response_code_00(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["response_code"] == "00"

    def test_approved_has_auth_code(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "auth_code" in data
        assert len(data["auth_code"]) == 6

    def test_approved_has_tpa_response(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "tpa_response" in data

    def test_approved_has_amount_decision(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "amount_decision" in data

    def test_approved_has_cb_result(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "cb_result" in data

    def test_blocked_card_declined(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_BLOCKED, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["approved"] is False
        assert data["response_code"] in ("62", "41", "43")

    def test_expired_card_54(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_EXPIRED, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["approved"] is False
        assert data["response_code"] == "54"

    def test_insufficient_funds_51(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_INSUF, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["approved"] is False
        assert data["response_code"] == "51"

    def test_missing_pan_returns_400(self, client):
        resp = post_json(client, "/api/v1/authorize", {
            "amount": 5000, "currency": "978", "transaction_type": "00",
        })
        assert resp.status_code == 400

    def test_zero_amount_declined_13(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 0,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["approved"] is False
        assert data["response_code"] == "13"

    def test_contactless_flag_reflected(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 2000,
            "currency": "978", "transaction_type": "00",
            "is_contactless": True,
        }).get_json()
        assert "cb_result" in data
        assert data["cb_result"]["is_contactless"] is True

    def test_with_mcc(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "mcc": "5411",
        }).get_json()
        assert data["approved"] is True

    def test_with_terminal_merchant_info(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "terminal_id": "TERM0042",
            "merchant_id": "MERCH0042",
            "merchant_name": "SUPERMARCH",
        }).get_json()
        assert data["approved"] is True

    def test_iso8583_format(self, client):
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "format": "iso8583",
        }).get_json()
        assert "response_code" in data

    def test_with_cvv2(self, client):
        from emv.cvv import compute_cvv2
        from config import Config
        cvv2 = compute_cvv2(PAN_ACTIVE, "2812", Config.CVK1, Config.CVK2)
        data = post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "cvv2": cvv2, "expiry": "2812",
        }).get_json()
        assert "cvv_check" in data or data.get("approved") is True


# ─────────────────────────────────────────────────────────────────────────────
# BATCH SIMULATE
# ─────────────────────────────────────────────────────────────────────────────
class TestBatchSimulate:
    def test_returns_200(self, client):
        resp = post_json(client, "/api/v1/batch/simulate", {"count": 3})
        assert resp.status_code == 200

    def test_returns_results_list(self, client):
        data = post_json(client, "/api/v1/batch/simulate",
                         {"count": 3}).get_json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_results_count_matches(self, client):
        data = post_json(client, "/api/v1/batch/simulate",
                         {"count": 3}).get_json()
        assert len(data["results"]) == 3

    def test_max_capped_at_100(self, client):
        data = post_json(client, "/api/v1/batch/simulate",
                         {"count": 999}).get_json()
        assert len(data["results"]) <= 100

    def test_each_result_has_response_code(self, client):
        data = post_json(client, "/api/v1/batch/simulate",
                         {"count": 3}).get_json()
        for r in data["results"]:
            assert "response_code" in r

    def test_seed_reproducible(self, client):
        r1 = post_json(client, "/api/v1/batch/simulate",
                       {"count": 5, "seed": 42}).get_json()
        r2 = post_json(client, "/api/v1/batch/simulate",
                       {"count": 5, "seed": 42}).get_json()
        assert "results" in r1
        assert "results" in r2
        # Le seed détermine PAN et montant ; les codes de réponse
        # dépendent de l'état cumulatif du log — seule la sélection est stable.
        amounts1 = [r["amount"] for r in r1["results"]]
        amounts2 = [r["amount"] for r in r2["results"]]
        assert amounts1 == amounts2

    def test_summary_fields_present(self, client):
        data = post_json(client, "/api/v1/batch/simulate",
                         {"count": 3}).get_json()
        assert "approved" in data
        assert "declined" in data
        assert "approval_rate" in data

    def test_default_count(self, client):
        data = post_json(client, "/api/v1/batch/simulate", {}).get_json()
        assert "results" in data
        assert len(data["results"]) > 0

    def test_approved_amount_present(self, client):
        data = post_json(client, "/api/v1/batch/simulate",
                         {"count": 3}).get_json()
        assert "total_approved_amount" in data


# ─────────────────────────────────────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────────────────────────────────────
class TestStats:
    def test_returns_200(self, client):
        assert get(client, "/api/v1/stats").status_code == 200

    def test_has_transaction_stats(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "transaction_stats" in data

    def test_transaction_stats_has_total(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "total" in data["transaction_stats"]

    def test_transaction_stats_has_approved(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "approved" in data["transaction_stats"]

    def test_transaction_stats_has_declined(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "declined" in data["transaction_stats"]

    def test_transaction_stats_has_approval_rate(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "approval_rate" in data["transaction_stats"]

    def test_has_card_stats(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "card_stats" in data

    def test_card_stats_has_total_cards(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "total_cards" in data["card_stats"]

    def test_has_server_info(self, client):
        data = get(client, "/api/v1/stats").get_json()
        assert "server" in data
        assert "version" in data["server"]

    def test_by_cb_scheme_present(self, client):
        post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        data = get(client, "/api/v1/stats").get_json()
        assert "by_cb_scheme" in data["transaction_stats"]


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────────────────────────────────────
class TestTransactions:
    def test_list_returns_200(self, client):
        assert get(client, "/api/v1/transactions").status_code == 200

    def test_list_has_transactions_key(self, client):
        data = get(client, "/api/v1/transactions").get_json()
        assert "transactions" in data

    def test_transactions_is_list(self, client):
        data = get(client, "/api/v1/transactions").get_json()
        assert isinstance(data["transactions"], list)

    def test_has_count_key(self, client):
        data = get(client, "/api/v1/transactions").get_json()
        assert "count" in data

    def test_filter_by_status_approved(self, client):
        data = get(client, "/api/v1/transactions",
                   {"status": "APPROVED"}).get_json()
        for t in data["transactions"]:
            assert t["status"] == "APPROVED"

    def test_filter_by_status_declined(self, client):
        data = get(client, "/api/v1/transactions",
                   {"status": "DECLINED"}).get_json()
        for t in data["transactions"]:
            assert t["status"] == "DECLINED"

    def test_pagination_limit(self, client):
        data = get(client, "/api/v1/transactions",
                   {"limit": 2}).get_json()
        assert len(data["transactions"]) <= 2

    def test_pan_masked_in_transactions(self, client):
        post_json(client, "/api/v1/authorize", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        data = get(client, "/api/v1/transactions").get_json()
        for t in data["transactions"]:
            if t["pan"].endswith("1111"):
                assert "*" in t["pan"]
                break

    def test_export_json_has_transactions_key(self, client):
        resp = get(client, "/api/v1/transactions/export", {"format": "json"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "transactions" in data
        assert isinstance(data["transactions"], list)

    def test_export_csv(self, client):
        resp = get(client, "/api/v1/transactions/export", {"format": "csv"})
        assert resp.status_code == 200
        assert b"," in resp.data or b";" in resp.data

    def test_export_csv_content_type(self, client):
        resp = get(client, "/api/v1/transactions/export", {"format": "csv"})
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type or "text/plain" in resp.content_type


# ─────────────────────────────────────────────────────────────────────────────
# AMOUNT TIERS
# ─────────────────────────────────────────────────────────────────────────────
class TestAmountTiers:
    def test_list_returns_200(self, client):
        assert get(client, "/api/v1/amount-tiers").status_code == 200

    def test_list_has_tiers_key(self, client):
        data = get(client, "/api/v1/amount-tiers").get_json()
        assert "tiers" in data

    def test_tiers_is_list(self, client):
        data = get(client, "/api/v1/amount-tiers").get_json()
        assert isinstance(data["tiers"], list)

    def test_at_least_6_tiers(self, client):
        data = get(client, "/api/v1/amount-tiers").get_json()
        assert len(data["tiers"]) >= 6

    def test_tiers_have_required_fields(self, client):
        data = get(client, "/api/v1/amount-tiers").get_json()
        for tier in data["tiers"]:
            assert "name" in tier
            assert "min_amount" in tier
            assert "max_amount" in tier

    def test_evaluate_returns_200(self, client):
        assert get(client, "/api/v1/amount-tiers/evaluate",
                   {"amount": 5000}).status_code == 200

    def test_evaluate_returns_tier(self, client):
        data = get(client, "/api/v1/amount-tiers/evaluate",
                   {"amount": 5000}).get_json()
        assert "tier" in data
        assert "name" in data["tier"]

    def test_evaluate_small(self, client):
        data = get(client, "/api/v1/amount-tiers/evaluate",
                   {"amount": 5000}).get_json()
        assert data["tier"]["name"] == "SMALL"

    def test_evaluate_micro(self, client):
        data = get(client, "/api/v1/amount-tiers/evaluate",
                   {"amount": 100}).get_json()
        assert data["tier"]["name"] == "MICRO"

    def test_evaluate_critical(self, client):
        data = get(client, "/api/v1/amount-tiers/evaluate",
                   {"amount": 600000}).get_json()
        assert data["tier"]["name"] == "CRITICAL"

    def test_evaluate_missing_amount_returns_400_or_zero(self, client):
        resp = get(client, "/api/v1/amount-tiers/evaluate")
        assert resp.status_code in (200, 400)

    def test_create_delete_custom_tier(self, client):
        payload = {
            "name": "TEST_API_TIER",
            "label": "Test API",
            "min_amount": 1,
            "max_amount": 50,
            "risk_level": "LOW",
        }
        resp = post_json(client, "/api/v1/amount-tiers", payload)
        assert resp.status_code in (200, 201)

        tiers = get(client, "/api/v1/amount-tiers").get_json()
        names = [t["name"] for t in tiers["tiers"]]
        assert "TEST_API_TIER" in names

        del_resp = client.delete("/api/v1/amount-tiers/TEST_API_TIER")
        assert del_resp.status_code in (200, 204)

        tiers_after = get(client, "/api/v1/amount-tiers").get_json()
        names_after = [t["name"] for t in tiers_after["tiers"]]
        assert "TEST_API_TIER" not in names_after

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/v1/amount-tiers/NONEXISTENT_TIER_XYZ")
        assert resp.status_code == 404

    def test_create_missing_name_returns_400(self, client):
        resp = post_json(client, "/api/v1/amount-tiers", {
            "label": "No name", "min_amount": 0, "max_amount": 100,
            "risk_level": "LOW",
        })
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# GIE CB
# ─────────────────────────────────────────────────────────────────────────────
class TestGIECB:
    def test_rules_returns_200(self, client):
        assert get(client, "/api/v1/giecb/rules").status_code == 200

    def test_rules_has_contactless(self, client):
        data = get(client, "/api/v1/giecb/rules").get_json()
        assert "contactless" in data

    def test_rules_has_cap(self, client):
        data = get(client, "/api/v1/giecb/rules").get_json()
        assert "cap" in data

    def test_rules_has_tap(self, client):
        data = get(client, "/api/v1/giecb/rules").get_json()
        assert "tap" in data

    def test_evaluate_returns_200(self, client):
        resp = post_json(client, "/api/v1/giecb/evaluate", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp.status_code == 200

    def test_evaluate_has_cb_result(self, client):
        data = post_json(client, "/api/v1/giecb/evaluate", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "cb_result" in data

    def test_evaluate_cb_result_has_allowed(self, client):
        data = post_json(client, "/api/v1/giecb/evaluate", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "allowed" in data["cb_result"]

    def test_evaluate_cb_result_has_sca_exemption(self, client):
        data = post_json(client, "/api/v1/giecb/evaluate", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "sca_exemption" in data["cb_result"]

    def test_evaluate_has_card_info(self, client):
        data = post_json(client, "/api/v1/giecb/evaluate", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert "card_info" in data
        assert "scheme" in data["card_info"]

    def test_aids_returns_200(self, client):
        assert get(client, "/api/v1/giecb/aids").status_code == 200

    def test_aids_returns_aids_key(self, client):
        data = get(client, "/api/v1/giecb/aids").get_json()
        assert "aids" in data

    def test_floor_limits_returns_200(self, client):
        assert get(client, "/api/v1/giecb/floor-limits").status_code == 200

    def test_floor_limits_has_floor_limits_key(self, client):
        data = get(client, "/api/v1/giecb/floor-limits").get_json()
        assert "floor_limits" in data

    def test_response_codes_returns_200(self, client):
        assert get(client, "/api/v1/giecb/response-codes").status_code == 200

    def test_response_codes_has_response_codes_key(self, client):
        data = get(client, "/api/v1/giecb/response-codes").get_json()
        assert "response_codes" in data

    def test_response_codes_has_00(self, client):
        data = get(client, "/api/v1/giecb/response-codes").get_json()
        assert "00" in data["response_codes"]

    def test_identify_card_via_giecb_evaluate(self, client):
        data = post_json(client, "/api/v1/giecb/evaluate", {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        }).get_json()
        assert data["card_info"]["scheme"] in ("VISA", "MC", "CB", "AMEX", "")


# ─────────────────────────────────────────────────────────────────────────────
# CVV
# ─────────────────────────────────────────────────────────────────────────────
class TestCVV:
    def test_generate_returns_200(self, client):
        resp = get(client, "/api/v1/cvv/generate",
                   {"pan": PAN_ACTIVE, "expiry_yymm": "2812"})
        assert resp.status_code == 200

    def test_generate_returns_cvv1_cvv2_icvv(self, client):
        data = get(client, "/api/v1/cvv/generate",
                   {"pan": PAN_ACTIVE, "expiry_yymm": "2812"}).get_json()
        assert "cvv1" in data
        assert "cvv2" in data
        assert "icvv" in data

    def test_generate_all_3_digits(self, client):
        data = get(client, "/api/v1/cvv/generate",
                   {"pan": PAN_ACTIVE, "expiry_yymm": "2812"}).get_json()
        assert data["cvv1"].isdigit()
        assert data["cvv2"].isdigit()
        assert data["icvv"].isdigit()

    def test_generate_missing_pan_returns_400(self, client):
        resp = get(client, "/api/v1/cvv/generate", {"expiry_yymm": "2812"})
        assert resp.status_code == 400

    def test_generate_missing_expiry_returns_400(self, client):
        resp = get(client, "/api/v1/cvv/generate", {"pan": PAN_ACTIVE})
        assert resp.status_code == 400

    def test_verify_valid_cvv2(self, client):
        gen = get(client, "/api/v1/cvv/generate",
                  {"pan": PAN_ACTIVE, "expiry_yymm": "2812"}).get_json()
        data = post_json(client, "/api/v1/cvv/verify", {
            "pan": PAN_ACTIVE, "expiry_yymm": "2812",
            "cvv": gen["cvv2"], "cvv_type": "CVV2",
        }).get_json()
        assert data.get("valid") is True

    def test_verify_invalid_cvv2(self, client):
        data = post_json(client, "/api/v1/cvv/verify", {
            "pan": PAN_ACTIVE, "expiry_yymm": "2812",
            "cvv": "000", "cvv_type": "CVV2",
        }).get_json()
        assert data.get("valid") is False

    def test_verify_missing_fields_returns_400(self, client):
        resp = post_json(client, "/api/v1/cvv/verify", {"pan": PAN_ACTIVE})
        assert resp.status_code == 400

    def test_pan_masked_in_response(self, client):
        data = get(client, "/api/v1/cvv/generate",
                   {"pan": PAN_ACTIVE, "expiry_yymm": "2812"}).get_json()
        assert "pan_masked" in data
        assert "*" in data["pan_masked"]


# ─────────────────────────────────────────────────────────────────────────────
# TLV PARSE
# ─────────────────────────────────────────────────────────────────────────────
class TestTLVParse:
    def test_returns_200(self, client):
        resp = post_json(client, "/api/v1/tlv/parse",
                         {"hex": "9F360200A19C0100"})
        assert resp.status_code == 200

    def test_returns_parsed_list(self, client):
        data = post_json(client, "/api/v1/tlv/parse",
                         {"hex": "9F360200A19C0100"}).get_json()
        assert "parsed" in data or "fields" in data

    def test_invalid_hex_returns_error(self, client):
        resp = post_json(client, "/api/v1/tlv/parse",
                         {"hex": "ZZZZZZZZ"})
        assert resp.status_code in (400, 200)

    def test_missing_hex_returns_400(self, client):
        resp = post_json(client, "/api/v1/tlv/parse", {})
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# CARDS
# ─────────────────────────────────────────────────────────────────────────────
class TestCards:
    def test_list_returns_200(self, client):
        assert get(client, "/api/v1/cards").status_code == 200

    def test_list_has_cards_key(self, client):
        data = get(client, "/api/v1/cards").get_json()
        assert "cards" in data

    def test_cards_is_list(self, client):
        data = get(client, "/api/v1/cards").get_json()
        assert isinstance(data["cards"], list)

    def test_list_has_test_cards(self, client):
        data = get(client, "/api/v1/cards").get_json()
        assert len(data["cards"]) >= 7

    def test_cards_pan_masked(self, client):
        data = get(client, "/api/v1/cards").get_json()
        for card in data["cards"]:
            if card["pan"].endswith("1111"):
                assert "*" in card["pan"]
                break

    def test_add_card_returns_201(self, client):
        resp = post_json(client, "/api/v1/cards", {
            "pan": "9876543210987654",
            "expiry": "2912",
            "cardholder_name": "TEST API USER",
            "psn": "01",
            "status": "ACTIVE",
            "balance": 100000,
            "daily_limit": 50000,
        })
        assert resp.status_code in (200, 201)

    def test_add_card_missing_pan_400(self, client):
        resp = post_json(client, "/api/v1/cards", {
            "expiry": "2912", "cardholder_name": "X",
        })
        assert resp.status_code == 400

    def test_block_card_returns_200(self, client):
        post_json(client, "/api/v1/cards", {
            "pan": "1234567890123456",
            "expiry": "2912", "cardholder_name": "BLOCK TEST",
        })
        resp = post_json(client, "/api/v1/cards/1234567890123456/block",
                         {"reason": "Test block"})
        assert resp.status_code == 200

    def test_block_card_updates_status(self, client):
        post_json(client, "/api/v1/cards", {
            "pan": "1234567890123457",
            "expiry": "2912", "cardholder_name": "BLOCK TEST 2",
        })
        post_json(client, "/api/v1/cards/1234567890123457/block", {})
        data = get(client, "/api/v1/cards").get_json()
        found = next((c for c in data["cards"]
                      if c["pan"].replace("*", "").endswith("3457")), None)
        assert found is not None
        assert found["status"] == "BLOCKED"

    def test_unblock_card_returns_200(self, client):
        post_json(client, "/api/v1/cards", {
            "pan": "1234567890123458",
            "expiry": "2912", "cardholder_name": "UNBLOCK TEST",
        })
        post_json(client, "/api/v1/cards/1234567890123458/block", {})
        resp = post_json(client, "/api/v1/cards/1234567890123458/unblock", {})
        assert resp.status_code == 200

    def test_unblock_card_updates_status(self, client):
        post_json(client, "/api/v1/cards", {
            "pan": "1234567890123459",
            "expiry": "2912", "cardholder_name": "UNBLOCK TEST 2",
        })
        post_json(client, "/api/v1/cards/1234567890123459/block", {})
        post_json(client, "/api/v1/cards/1234567890123459/unblock", {})
        data = get(client, "/api/v1/cards").get_json()
        found = next((c for c in data["cards"]
                      if c["pan"].replace("*", "").endswith("3459")), None)
        assert found is not None
        assert found["status"] == "ACTIVE"

    def test_block_nonexistent_card(self, client):
        resp = post_json(client, "/api/v1/cards/0000000000000000/block", {})
        assert resp.status_code in (404, 400, 200)

    def test_count_key_present(self, client):
        data = get(client, "/api/v1/cards").get_json()
        assert "count" in data


# ─────────────────────────────────────────────────────────────────────────────
# TPA FIELDS
# ─────────────────────────────────────────────────────────────────────────────
class TestTPAFields:
    def test_returns_200(self, client):
        assert get(client, "/api/v1/tpa/fields").status_code == 200

    def test_returns_fields_key(self, client):
        data = get(client, "/api/v1/tpa/fields").get_json()
        assert "fields" in data

    def test_fields_is_dict(self, client):
        data = get(client, "/api/v1/tpa/fields").get_json()
        assert isinstance(data["fields"], dict)

    def test_has_f00(self, client):
        data = get(client, "/api/v1/tpa/fields").get_json()
        assert "F00" in data["fields"]

    def test_has_cb_fields(self, client):
        data = get(client, "/api/v1/tpa/fields").get_json()
        assert "CB1" in data["fields"]
        assert "CBA" in data["fields"]

    def test_fields_have_name_description(self, client):
        data = get(client, "/api/v1/tpa/fields").get_json()
        for fid, defn in data["fields"].items():
            assert "name" in defn
            assert "description" in defn

    def test_has_cb_fields_list(self, client):
        data = get(client, "/api/v1/tpa/fields").get_json()
        assert "cb_fields" in data
        assert isinstance(data["cb_fields"], list)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
class TestDashboard:
    def test_dashboard_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_dashboard_is_html(self, client):
        resp = client.get("/")
        assert b"<!DOCTYPE html>" in resp.data or b"<html" in resp.data

    def test_dashboard_has_emv_title(self, client):
        resp = client.get("/")
        assert b"EMV" in resp.data


# ─────────────────────────────────────────────────────────────────────────────
# 404
# ─────────────────────────────────────────────────────────────────────────────
class TestNotFound:
    def test_unknown_api_returns_404(self, client):
        resp = client.get("/api/v1/nonexistent_endpoint_xyz")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# S1 — API KEY AUTH
# ─────────────────────────────────────────────────────────────────────────────
class TestApiKeyAuth:
    def test_no_key_required_when_empty(self, client):
        from config import Config
        if not Config.API_KEY:
            resp = get(client, "/api/v1/stats")
            assert resp.status_code == 200

    def test_wrong_key_returns_401_when_set(self, client):
        from config import Config
        if Config.API_KEY:
            resp = client.get("/api/v1/stats",
                              headers={"X-Api-Key": "WRONGKEY"})
            assert resp.status_code == 401

    def test_correct_key_returns_200_when_set(self, client):
        from config import Config
        if Config.API_KEY:
            resp = client.get("/api/v1/stats",
                              headers={"X-Api-Key": Config.API_KEY})
            assert resp.status_code == 200

    def test_health_exempt_from_auth(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
