"""
Tests unitaires — emv/amount_rules.py
Couvre : AmountTier.matches, get_tier, get_all_tiers,
         add_custom_tier, delete_custom_tier, evaluate_amount,
         AmountDecision.to_dict
"""

import pytest
from emv.amount_rules import (
    AmountTier, AmountDecision, AMOUNT_TIERS,
    get_tier, get_all_tiers,
    add_custom_tier, delete_custom_tier,
    evaluate_amount, _custom_tiers,
)


@pytest.fixture(autouse=True)
def clean_custom_tiers():
    """Vide les tranches personnalisées avant et après chaque test."""
    _custom_tiers.clear()
    yield
    _custom_tiers.clear()


class TestAmountTierMatches:
    def test_within_range(self):
        tier = AMOUNT_TIERS[0]
        assert tier.matches(tier.min_amount) is True
        assert tier.matches(tier.max_amount) is True
        assert tier.matches((tier.min_amount + tier.max_amount) // 2) is True

    def test_below_range(self):
        tier = AMOUNT_TIERS[2]
        assert tier.matches(tier.min_amount - 1) is False

    def test_above_range(self):
        tier = AMOUNT_TIERS[0]
        assert tier.matches(tier.max_amount + 1) is False

    def test_exact_boundary_min(self):
        tier = AMOUNT_TIERS[1]
        assert tier.matches(tier.min_amount) is True

    def test_exact_boundary_max(self):
        tier = AMOUNT_TIERS[1]
        assert tier.matches(tier.max_amount) is True

    def test_zero_amount_matches_micro(self):
        assert AMOUNT_TIERS[0].matches(0) is True


class TestGetTier:
    @pytest.mark.parametrize("amount,expected_name", [
        (0,      "MICRO"),
        (250,    "MICRO"),
        (500,    "MICRO"),
        (501,    "SMALL"),
        (5000,   "SMALL"),
        (5001,   "STANDARD"),
        (50000,  "STANDARD"),
        (50001,  "HIGH"),
        (200000, "HIGH"),
        (200001, "VERY_HIGH"),
        (500000, "VERY_HIGH"),
        (500001, "CRITICAL"),
        (999999, "CRITICAL"),
    ])
    def test_tier_boundaries(self, amount, expected_name):
        tier = get_tier(amount)
        assert tier.name == expected_name, \
            f"Montant {amount} doit être dans la tranche {expected_name}, obtenu {tier.name}"

    def test_very_large_amount_critical(self):
        tier = get_tier(10_000_000)
        assert tier.name == "CRITICAL"

    def test_custom_tier_takes_priority(self):
        add_custom_tier({"name": "PROMO", "label": "Promo", "min_amount": 1000,
                         "max_amount": 2000, "risk_level": "LOW"})
        tier = get_tier(1500)
        assert tier.name == "PROMO"


class TestGetAllTiers:
    def test_minimum_6_builtin_tiers(self):
        tiers = get_all_tiers()
        assert len(tiers) >= 6

    def test_sorted_by_min_amount(self):
        tiers = get_all_tiers()
        amounts = [t.min_amount for t in tiers]
        assert amounts == sorted(amounts)

    def test_all_tier_names_unique(self):
        tiers = get_all_tiers()
        names = [t.name for t in tiers]
        assert len(names) == len(set(names))

    def test_custom_tier_included(self):
        add_custom_tier({"name": "MYTEST", "label": "Test", "min_amount": 0,
                         "max_amount": 10, "risk_level": "LOW"})
        tiers = get_all_tiers()
        names = [t.name for t in tiers]
        assert "MYTEST" in names


class TestAddCustomTier:
    def test_creates_tier(self):
        tier = add_custom_tier({
            "name": "CUSTOM",
            "label": "Custom test",
            "min_amount": 999,
            "max_amount": 1999,
            "risk_level": "MEDIUM",
        })
        assert tier.name == "CUSTOM"
        assert tier.min_amount == 999
        assert tier.max_amount == 1999

    def test_name_uppercased(self):
        tier = add_custom_tier({"name": "lowercase", "label": "L", "min_amount": 0,
                                 "max_amount": 100, "risk_level": "LOW"})
        assert tier.name == "LOWERCASE"

    def test_default_online_true(self):
        tier = add_custom_tier({"name": "T", "label": "T", "min_amount": 0,
                                 "max_amount": 100, "risk_level": "LOW"})
        assert tier.require_online is True

    def test_explicit_offline(self):
        tier = add_custom_tier({"name": "T", "label": "T", "min_amount": 0,
                                 "max_amount": 100, "risk_level": "LOW",
                                 "require_online": False, "auto_approve_offline": True})
        assert tier.require_online is False
        assert tier.auto_approve_offline is True

    def test_optional_max_daily_count(self):
        tier = add_custom_tier({"name": "T", "label": "T", "min_amount": 0,
                                 "max_amount": 100, "risk_level": "LOW",
                                 "max_daily_count": 5})
        assert tier.max_daily_count == 5

    def test_no_max_daily_count(self):
        tier = add_custom_tier({"name": "T", "label": "T", "min_amount": 0,
                                 "max_amount": 100, "risk_level": "LOW"})
        assert tier.max_daily_count is None


class TestDeleteCustomTier:
    def test_delete_existing_returns_true(self):
        add_custom_tier({"name": "DEL_ME", "label": "D", "min_amount": 0,
                         "max_amount": 100, "risk_level": "LOW"})
        assert delete_custom_tier("DEL_ME") is True

    def test_tier_removed_from_list(self):
        add_custom_tier({"name": "DEL_ME2", "label": "D", "min_amount": 0,
                         "max_amount": 100, "risk_level": "LOW"})
        delete_custom_tier("DEL_ME2")
        names = [t.name for t in get_all_tiers()]
        assert "DEL_ME2" not in names

    def test_delete_nonexistent_returns_false(self):
        assert delete_custom_tier("DOES_NOT_EXIST") is False

    def test_cannot_delete_builtin_tier(self):
        assert delete_custom_tier("STANDARD") is False

    def test_case_insensitive_delete(self):
        add_custom_tier({"name": "CASE_TIER", "label": "C", "min_amount": 0,
                         "max_amount": 100, "risk_level": "LOW"})
        assert delete_custom_tier("case_tier") is True


class TestEvaluateAmount:
    def test_micro_offline_path(self):
        decision = evaluate_amount(100, "00")
        assert decision.allowed is True
        assert decision.auth_path == "OFFLINE"
        assert decision.tier.name == "MICRO"

    def test_small_offline_path(self):
        decision = evaluate_amount(2000, "00")
        assert decision.allowed is True
        assert decision.auth_path == "OFFLINE"

    def test_standard_online_path(self):
        decision = evaluate_amount(10000, "00")
        assert decision.allowed is True
        assert decision.auth_path == "ONLINE"

    def test_critical_referral_not_allowed(self):
        decision = evaluate_amount(600000, "00")
        assert decision.allowed is False
        assert decision.response_code == "01"
        assert decision.auth_path == "REFERRAL"

    def test_daily_limit_exceeded(self):
        tier = get_tier(10000)
        if tier.max_daily_count is not None:
            decision = evaluate_amount(10000, "00", daily_count=tier.max_daily_count)
            assert decision.allowed is False
            assert decision.response_code == "65"

    def test_high_risk_has_warning(self):
        decision = evaluate_amount(100000, "00")
        assert len(decision.warnings) > 0

    def test_arqc_missing_warning(self):
        decision = evaluate_amount(10000, "00", has_arqc=False)
        assert any("ARQC" in w or "arqc" in w.lower() for w in decision.warnings)

    def test_arqc_present_no_arqc_warning(self):
        decision = evaluate_amount(10000, "00", has_arqc=True)
        assert not any("ARQC requis" in w for w in decision.warnings)

    def test_response_code_00_when_allowed(self):
        decision = evaluate_amount(5000, "00")
        assert decision.response_code == "00"

    def test_response_message_not_empty(self):
        decision = evaluate_amount(5000, "00")
        assert decision.response_message != ""


class TestAmountDecisionToDict:
    def test_contains_required_keys(self):
        decision = evaluate_amount(5000, "00")
        d = decision.to_dict()
        expected_keys = [
            "tier_name", "tier_label", "risk_level",
            "allowed", "response_code", "response_message",
            "auth_path", "require_online", "require_arqc",
            "require_pin", "warnings",
        ]
        for key in expected_keys:
            assert key in d, f"Clé manquante : {key}"

    def test_tier_name_matches(self):
        decision = evaluate_amount(10000, "00")
        d = decision.to_dict()
        assert d["tier_name"] == "STANDARD"

    def test_warnings_is_list(self):
        decision = evaluate_amount(5000, "00")
        assert isinstance(decision.to_dict()["warnings"], list)

    def test_risk_level_not_empty(self):
        decision = evaluate_amount(5000, "00")
        assert decision.to_dict()["risk_level"] != ""
