"""
Tests C3 — Tokenisation HCE / NFC CB-PAY
"""
import pytest
from emv.tokenization import (
    create_token, get_token, get_tokens_by_pan, is_token,
    use_token, suspend_token, resume_token, delete_token,
    get_all_tokens, get_token_stats,
    _luhn_valid, TOKEN_PREFIX,
    STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_DELETED,
)


PAN  = "4111111111111111"
PAN2 = "5500000000000004"


# ── Tests LUHN ────────────────────────────────────────────────────────────────

class TestLuhn:

    def test_luhn_valid_known(self):
        assert _luhn_valid("4111111111111111")
        assert _luhn_valid("5500000000000004")

    def test_luhn_invalid(self):
        assert not _luhn_valid("4111111111111112")

    def test_generated_token_luhn_valid(self):
        tok = create_token(PAN)
        assert _luhn_valid(tok["token"])


# ── Tests create_token ────────────────────────────────────────────────────────

class TestCreateToken:

    def test_token_prefix(self):
        tok = create_token(PAN)
        assert tok["token"].startswith(TOKEN_PREFIX)

    def test_token_length_16(self):
        tok = create_token(PAN)
        assert len(tok["token"]) == 16

    def test_token_luhn_valid(self):
        tok = create_token(PAN)
        assert _luhn_valid(tok["token"])

    def test_token_id_format(self):
        tok = create_token(PAN)
        assert tok["id"].startswith("TOK-")

    def test_default_status_active(self):
        tok = create_token(PAN)
        assert tok["status"] == STATUS_ACTIVE

    def test_default_domain(self):
        tok = create_token(PAN)
        assert tok["domain"] == "HCE_MOBILE"

    def test_custom_domain(self):
        tok = create_token(PAN, domain="ECOMMERCE")
        assert tok["domain"] == "ECOMMERCE"

    def test_invalid_domain_fallback(self):
        tok = create_token(PAN, domain="INVALID_DOMAIN")
        assert tok["domain"] == "ANY"

    def test_pan_not_in_metadata(self):
        tok = create_token(PAN)
        assert PAN not in str(tok)
        assert tok.get("pan") is None

    def test_pan_last4_present(self):
        tok = create_token(PAN)
        assert tok["pan_last4"] == PAN[-4:]

    def test_two_tokens_different(self):
        tok1 = create_token(PAN)
        tok2 = create_token(PAN)
        assert tok1["token"] != tok2["token"]
        assert tok1["id"] != tok2["id"]

    def test_max_uses_stored(self):
        tok = create_token(PAN, max_uses=5)
        assert tok["max_uses"] == 5

    def test_created_at_present(self):
        tok = create_token(PAN)
        assert tok["created_at"] is not None

    def test_device_info_stored(self):
        tok = create_token(PAN, device_info="iPhone 15 Pro")
        assert tok["device_info"] == "iPhone 15 Pro"


# ── Tests get_token ────────────────────────────────────────────────────────────

class TestGetToken:

    def test_get_by_token_value(self):
        tok = create_token(PAN)
        found = get_token(tok["token"])
        assert found is not None
        assert found["id"] == tok["id"]

    def test_get_by_token_id(self):
        tok = create_token(PAN)
        found = get_token(tok["id"])
        assert found is not None
        assert found["token"] == tok["token"]

    def test_unknown_token_returns_none(self):
        assert get_token("4999000000000000") is None
        assert get_token("TOK-UNKNOWN") is None


# ── Tests is_token ─────────────────────────────────────────────────────────────

class TestIsToken:

    def test_known_token_detected(self):
        tok = create_token(PAN)
        assert is_token(tok["token"])

    def test_real_pan_not_detected(self):
        assert not is_token(PAN)

    def test_random_string_not_detected(self):
        assert not is_token("1234567890123456")


# ── Tests get_tokens_by_pan ────────────────────────────────────────────────────

class TestGetTokensByPan:

    def test_returns_list(self):
        create_token(PAN)
        tokens = get_tokens_by_pan(PAN)
        assert isinstance(tokens, list)
        assert len(tokens) >= 1

    def test_pan_with_spaces(self):
        tok = create_token("4111 1111 1111 1111")
        tokens = get_tokens_by_pan("4111111111111111")
        assert any(t["id"] == tok["id"] for t in tokens)

    def test_different_pans_isolated(self):
        tok1 = create_token(PAN)
        tok2 = create_token(PAN2)
        tokens_pan1 = get_tokens_by_pan(PAN)
        tokens_pan2 = get_tokens_by_pan(PAN2)
        ids_pan1 = [t["id"] for t in tokens_pan1]
        ids_pan2 = [t["id"] for t in tokens_pan2]
        assert tok1["id"] in ids_pan1
        assert tok2["id"] in ids_pan2
        assert tok2["id"] not in ids_pan1


# ── Tests use_token ────────────────────────────────────────────────────────────

class TestUseToken:

    def test_use_increments_count(self):
        tok = create_token(PAN)
        use_token(tok["token"])
        found = get_token(tok["id"])
        assert found["use_count"] == 1

    def test_use_sets_last_used(self):
        tok = create_token(PAN)
        use_token(tok["token"])
        found = get_token(tok["id"])
        assert found["last_used_at"] is not None

    def test_max_uses_suspends_token(self):
        tok = create_token(PAN, max_uses=2)
        use_token(tok["token"])
        use_token(tok["token"])
        found = get_token(tok["id"])
        assert found["status"] == STATUS_SUSPENDED

    def test_deleted_token_not_usable(self):
        tok = create_token(PAN)
        delete_token(tok["id"])
        result = use_token(tok["token"])
        assert result is False


# ── Tests lifecycle suspend/resume/delete ─────────────────────────────────────

class TestLifecycle:

    def test_suspend(self):
        tok = create_token(PAN)
        s = suspend_token(tok["id"])
        assert s["status"] == STATUS_SUSPENDED
        assert s["suspended_at"] is not None

    def test_resume(self):
        tok = create_token(PAN)
        suspend_token(tok["id"])
        r = resume_token(tok["id"])
        assert r["status"] == STATUS_ACTIVE
        assert r["suspended_at"] is None

    def test_delete(self):
        tok = create_token(PAN)
        d = delete_token(tok["id"])
        assert d["status"] == STATUS_DELETED
        assert d["deleted_at"] is not None

    def test_suspend_by_token_value(self):
        tok = create_token(PAN)
        s = suspend_token(tok["token"])
        assert s is not None
        assert s["status"] == STATUS_SUSPENDED

    def test_delete_by_token_value(self):
        tok = create_token(PAN)
        d = delete_token(tok["token"])
        assert d is not None
        assert d["status"] == STATUS_DELETED

    def test_unknown_suspend_returns_none(self):
        assert suspend_token("TOK-UNKNOWN") is None

    def test_deleted_excluded_by_default_listing(self):
        tok = create_token(PAN)
        delete_token(tok["id"])
        tokens = get_all_tokens()
        ids = [t["id"] for t in tokens]
        assert tok["id"] not in ids


# ── Tests listing & stats ─────────────────────────────────────────────────────

class TestListingAndStats:

    def test_get_all_tokens_returns_list(self):
        create_token(PAN)
        tokens = get_all_tokens()
        assert isinstance(tokens, list)
        assert len(tokens) > 0

    def test_filter_by_domain(self):
        create_token(PAN, domain="ECOMMERCE")
        tokens = get_all_tokens(domain="ECOMMERCE")
        for t in tokens:
            assert t["domain"] == "ECOMMERCE"

    def test_filter_by_status(self):
        tok = create_token(PAN)
        suspend_token(tok["id"])
        tokens = get_all_tokens(status=STATUS_SUSPENDED)
        for t in tokens:
            assert t["status"] == STATUS_SUSPENDED

    def test_stats_structure(self):
        stats = get_token_stats()
        assert "total" in stats
        assert "active" in stats
        assert "suspended" in stats
        assert "deleted" in stats
        assert "by_domain" in stats

    def test_stats_counts_consistent(self):
        stats = get_token_stats()
        assert stats["total"] >= stats["active"] + stats["suspended"]

    def test_limit_offset(self):
        for _ in range(5):
            create_token(PAN)
        page1 = get_all_tokens(limit=2, offset=0)
        page2 = get_all_tokens(limit=2, offset=2)
        assert len(page1) <= 2
        if page1 and page2:
            assert page1[0]["id"] != page2[0]["id"]
