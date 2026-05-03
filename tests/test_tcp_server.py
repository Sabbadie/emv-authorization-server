"""
Tests unitaires et d'intégration — emv/tcp_server.py

Couvre :
  - encode_message / decode_message
  - process_request (format natif + ISO 8583)
  - _error_response
  - TCPAuthorizationServer (start/stop, connexion réelle, multi-clients)
"""

import json
import socket
import struct
import time
import threading

import pytest

from emv.tcp_server import (
    encode_message, decode_message,
    recv_message, send_message,
    process_request, _error_response,
    TCPAuthorizationServer,
)
from models.card import card_db, CardStatus
from models.transaction import transaction_log

PAN_ACTIVE  = "4111111111111111"
PAN_BLOCKED = "4000000000000028"
PAN_EXPIRED = "4000000000000010"
PAN_INSUF   = "4000000000000036"
PAN_UNKNOWN = "9999999999999999"

TEST_TCP_PORT = 18583


def _reset_active_card():
    card = card_db.get_card(PAN_ACTIVE)
    if card:
        card.status = CardStatus.ACTIVE
        card.balance = 500000
        card.daily_spent = 0
        card.daily_limit = 200000
        card.contactless_cumul = 0
        card.consecutive_offline = 0


def _clear_txn_log(*pans):
    for pan in pans:
        ids = transaction_log._pan_index.pop(pan, [])
        for tid in ids:
            transaction_log._transactions.pop(tid, None)


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaire de connexion bas niveau pour les tests d'intégration
# ─────────────────────────────────────────────────────────────────────────────

def tcp_roundtrip(port: int, payload: dict, host: str = "127.0.0.1") -> dict:
    """Envoie une requête et retourne la réponse via TCP."""
    sock = socket.create_connection((host, port), timeout=5)
    try:
        body = json.dumps(payload).encode("utf-8")
        sock.sendall(struct.pack(">I", len(body)) + body)
        header = b""
        while len(header) < 4:
            chunk = sock.recv(4 - len(header))
            assert chunk, "Connexion fermée"
            header += chunk
        length = struct.unpack(">I", header)[0]
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            assert chunk, "Connexion fermée"
            data += chunk
        return json.loads(data.decode("utf-8"))
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : serveur TCP démarré sur port de test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tcp_server():
    srv = TCPAuthorizationServer(host="127.0.0.1", port=TEST_TCP_PORT)
    srv.start()
    time.sleep(0.2)
    yield srv
    srv.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Tests de sérialisation
# ─────────────────────────────────────────────────────────────────────────────

class TestEncoding:
    def test_encode_roundtrip(self):
        msg = {"approved": True, "code": "00"}
        encoded = encode_message(msg)
        length = struct.unpack(">I", encoded[:4])[0]
        body = encoded[4:]
        assert len(body) == length
        assert json.loads(body) == msg

    def test_encode_adds_4_byte_prefix(self):
        msg = {"x": 1}
        encoded = encode_message(msg)
        assert len(encoded) == 4 + len(json.dumps(msg).encode())

    def test_decode_valid_json(self):
        data = b'{"a": 1, "b": "hello"}'
        assert decode_message(data) == {"a": 1, "b": "hello"}

    def test_decode_unicode(self):
        msg = {"name": "Montréal — café"}
        encoded = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        assert decode_message(encoded) == msg

    def test_encode_produces_bytes(self):
        assert isinstance(encode_message({"k": "v"}), bytes)

    def test_empty_dict_encodes(self):
        encoded = encode_message({})
        assert len(encoded) >= 4

    def test_nested_dict_roundtrip(self):
        msg = {"fields": {"pan": "4111", "amount": 5000}, "approved": True}
        assert decode_message(encode_message(msg)[4:]) == msg

    def test_large_message(self):
        msg = {"data": "A" * 10000}
        encoded = encode_message(msg)
        length = struct.unpack(">I", encoded[:4])[0]
        assert length == len(json.dumps(msg).encode())


# ─────────────────────────────────────────────────────────────────────────────
# Tests de process_request (sans socket réel)
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessRequest:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE, PAN_BLOCKED, PAN_EXPIRED, PAN_INSUF, PAN_UNKNOWN)
        _reset_active_card()

    def test_native_approved(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "skip_crypto": True,
        })
        assert resp["approved"] is True
        assert resp["response_code"] == "00"
        assert resp["mti"] == "0110"

    def test_native_has_auth_code(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "skip_crypto": True,
        })
        assert "auth_code" in resp
        assert len(resp["auth_code"]) == 6

    def test_native_pan_masked(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert "*" in resp["pan_masked"]
        assert resp["pan_masked"].endswith("1111")

    def test_native_tier_present(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["tier"] == "SMALL"

    def test_native_micro_offline(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 200,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is True
        assert resp["tier"] == "MICRO"

    def test_native_blocked_card(self):
        resp = process_request({
            "pan": PAN_BLOCKED, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] in ("62", "41", "43")

    def test_native_expired_card(self):
        resp = process_request({
            "pan": PAN_EXPIRED, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "54"

    def test_native_unknown_pan(self):
        resp = process_request({
            "pan": PAN_UNKNOWN, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "14"

    def test_native_zero_amount(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 0,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "13"

    def test_native_critical_amount(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 600000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "01"

    def test_native_contactless(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 1500,
            "currency": "978", "transaction_type": "00",
            "is_contactless": True,
        })
        assert resp["approved"] is True

    def test_native_missing_pan_error(self):
        resp = process_request({
            "amount": 5000, "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "30"
        assert "error" in resp

    def test_iso8583_dict_approved(self):
        resp = process_request({
            "mti": "0100",
            "fields": {
                "2":  PAN_ACTIVE,
                "3":  "000000",
                "4":  "000000005000",
                "7":  "0523143015",
                "11": "000042",
                "22": "051",
                "25": "00",
                "37": "123456789012",
                "41": "TERM0001",
                "49": "978",
            }
        })
        assert resp["approved"] is True
        assert resp["response_code"] == "00"
        assert resp["mti"] == "0110"

    def test_iso8583_rrn_echoed(self):
        resp = process_request({
            "mti": "0100",
            "fields": {
                "2":  PAN_ACTIVE,
                "3":  "000000",
                "4":  "000000005000",
                "37": "RRN123456789",
                "49": "978",
            }
        })
        assert resp.get("rrn") == "RRN123456789"

    def test_iso8583_blocked_card(self):
        resp = process_request({
            "mti": "0100",
            "fields": {
                "2":  PAN_BLOCKED,
                "3":  "000000",
                "4":  "000000005000",
                "49": "978",
            }
        })
        assert resp["approved"] is False

    def test_iso8583_unsupported_mti(self):
        resp = process_request({
            "mti": "0400",
            "fields": {"2": PAN_ACTIVE, "4": "000000005000", "49": "978"}
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "30"

    def test_response_always_has_mti_0110(self):
        for req in [
            {"pan": PAN_ACTIVE, "amount": 5000, "currency": "978", "transaction_type": "00"},
            {"pan": PAN_BLOCKED, "amount": 5000, "currency": "978", "transaction_type": "00"},
            {"mti": "0100", "fields": {"2": PAN_ACTIVE, "4": "000000005000", "49": "978"}},
        ]:
            resp = process_request(req)
            assert resp["mti"] == "0110"

    def test_cb_allowed_present(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert "cb_allowed" in resp

    def test_transaction_id_present(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp.get("transaction_id") is not None

    def test_message_field_present(self):
        resp = process_request({
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert "message" in resp


class TestErrorResponse:
    def test_returns_dict(self):
        r = _error_response("30", "test error")
        assert isinstance(r, dict)

    def test_mti_0110(self):
        r = _error_response("30", "test")
        assert r["mti"] == "0110"

    def test_approved_false(self):
        r = _error_response("30", "test")
        assert r["approved"] is False

    def test_response_code(self):
        r = _error_response("96", "system error")
        assert r["response_code"] == "96"

    def test_error_message(self):
        r = _error_response("30", "invalid format")
        assert "invalid format" in r["error"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests de recv_message via socket pair
# ─────────────────────────────────────────────────────────────────────────────

class TestRecvSendMessage:
    def _make_pair(self):
        """Crée une paire de sockets connectés."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port), timeout=2)
        conn, _ = srv.accept()
        srv.close()
        return client, conn

    def test_send_recv_roundtrip(self):
        client, conn = self._make_pair()
        try:
            msg = {"approved": True, "code": "00"}
            send_message(client, msg)
            received = recv_message(conn)
            assert received == msg
        finally:
            client.close()
            conn.close()

    def test_multiple_messages(self):
        client, conn = self._make_pair()
        try:
            messages = [{"n": i, "data": "x" * i} for i in range(5)]
            for m in messages:
                send_message(client, m)
            for expected in messages:
                assert recv_message(conn) == expected
        finally:
            client.close()
            conn.close()

    def test_connection_closed_raises(self):
        client, conn = self._make_pair()
        client.close()
        with pytest.raises((ConnectionError, OSError, struct.error)):
            recv_message(conn)
        conn.close()

    def test_large_payload(self):
        client, conn = self._make_pair()
        try:
            msg = {"data": "Z" * 50000}
            send_message(client, msg)
            received = recv_message(conn)
            assert received == msg
        finally:
            client.close()
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Tests d'intégration — serveur TCP réel
# ─────────────────────────────────────────────────────────────────────────────

class TestTCPServerIntegration:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE, PAN_BLOCKED, PAN_EXPIRED, PAN_INSUF, PAN_UNKNOWN)
        _reset_active_card()

    def test_server_is_running(self, tcp_server):
        assert tcp_server.running is True

    def test_server_accepts_connection(self, tcp_server):
        sock = socket.create_connection(("127.0.0.1", TEST_TCP_PORT), timeout=3)
        sock.close()

    def test_approved_transaction_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "skip_crypto": True,
        })
        assert resp["approved"] is True
        assert resp["response_code"] == "00"

    def test_response_code_00_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "skip_crypto": True,
        })
        assert resp["response_code"] == "00"

    def test_auth_code_6_digits(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
            "skip_crypto": True,
        })
        assert resp.get("auth_code", "").isdigit()
        assert len(resp.get("auth_code", "")) == 6

    def test_blocked_card_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_BLOCKED, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] in ("62", "41", "43")

    def test_expired_card_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_EXPIRED, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "54"

    def test_iso8583_format_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0100",
            "fields": {
                "2":  PAN_ACTIVE,
                "3":  "000000",
                "4":  "000000005000",
                "49": "978",
            }
        })
        assert resp["mti"] == "0110"
        assert resp["approved"] is True

    def test_contactless_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_ACTIVE, "amount": 1500,
            "currency": "978", "transaction_type": "00",
            "is_contactless": True, "skip_crypto": True,
        })
        assert resp["approved"] is True

    def test_missing_pan_returns_error(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "amount": 5000, "currency": "978",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "30"

    def test_multiple_sequential_requests(self, tcp_server):
        """Plusieurs requêtes sur la même connexion TCP."""
        sock = socket.create_connection(("127.0.0.1", TEST_TCP_PORT), timeout=5)
        try:
            requests = [
                {"pan": PAN_ACTIVE, "amount": 200,  "currency": "978", "transaction_type": "00", "skip_crypto": True},
                {"pan": PAN_ACTIVE, "amount": 5000, "currency": "978", "transaction_type": "00", "skip_crypto": True},
            ]
            responses = []
            for req in requests:
                body = json.dumps(req).encode()
                sock.sendall(struct.pack(">I", len(body)) + body)
                header = b""
                while len(header) < 4:
                    header += sock.recv(4 - len(header))
                length = struct.unpack(">I", header)[0]
                data = b""
                while len(data) < length:
                    data += sock.recv(length - len(data))
                responses.append(json.loads(data))
            assert len(responses) == 2
            for r in responses:
                assert r["mti"] == "0110"
        finally:
            sock.close()

    def test_concurrent_clients(self, tcp_server):
        """Plusieurs clients simultanés."""
        results = []
        errors = []

        def client_task(i):
            try:
                resp = tcp_roundtrip(TEST_TCP_PORT, {
                    "pan": PAN_ACTIVE, "amount": 5000,
                    "currency": "978", "transaction_type": "00",
                    "skip_crypto": True,
                })
                results.append(resp)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=client_task, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Erreurs : {errors}"
        assert len(results) == 5
        assert all(r["mti"] == "0110" for r in results)

    def test_mti_always_0110(self, tcp_server):
        for pan in [PAN_ACTIVE, PAN_BLOCKED, PAN_UNKNOWN]:
            resp = tcp_roundtrip(TEST_TCP_PORT, {
                "pan": pan, "amount": 5000,
                "currency": "978", "transaction_type": "00",
            })
            assert resp["mti"] == "0110"

    def test_pan_masked_in_response(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_ACTIVE, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert "*" in resp.get("pan_masked", "")

    def test_unknown_pan_over_tcp(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "pan": PAN_UNKNOWN, "amount": 5000,
            "currency": "978", "transaction_type": "00",
        })
        assert resp["approved"] is False
        assert resp["response_code"] == "14"


# ─────────────────────────────────────────────────────────────────────────────
# Tests du cycle de vie du serveur
# ─────────────────────────────────────────────────────────────────────────────

class TestTCPServerLifecycle:
    def test_start_stop(self):
        srv = TCPAuthorizationServer(host="127.0.0.1", port=18584)
        srv.start()
        time.sleep(0.1)
        assert srv.running is True
        srv.stop()
        time.sleep(0.1)
        assert srv.running is False

    def test_start_twice_is_idempotent(self):
        srv = TCPAuthorizationServer(host="127.0.0.1", port=18585)
        srv.start()
        time.sleep(0.1)
        srv.start()
        assert srv.running is True
        srv.stop()

    def test_stop_without_start_is_safe(self):
        srv = TCPAuthorizationServer(host="127.0.0.1", port=18586)
        srv.stop()

    def test_binds_to_configured_port(self):
        port = 18587
        srv = TCPAuthorizationServer(host="127.0.0.1", port=port)
        srv.start()
        time.sleep(0.1)
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            sock.close()
        finally:
            srv.stop()

    def test_rejects_connection_after_stop(self):
        srv = TCPAuthorizationServer(host="127.0.0.1", port=18588)
        srv.start()
        time.sleep(0.1)
        srv.stop()
        time.sleep(0.2)
        with pytest.raises((ConnectionRefusedError, OSError)):
            socket.create_connection(("127.0.0.1", 18588), timeout=1)
