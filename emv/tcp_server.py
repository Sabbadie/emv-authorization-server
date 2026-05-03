"""
Serveur TCP ISO 8583 — Interface socket pour terminaux de paiement.

Protocole fil de fer (wire protocol) :
  ┌───────────────────────────────────────────┐
  │  [4 octets big-endian: longueur payload]  │
  │  [payload UTF-8 JSON]                     │
  └───────────────────────────────────────────┘

Deux formats de requête acceptés :

1. Format natif (simplifié) :
   {"pan":"4111111111111111","amount":5000,"currency":"978",
    "transaction_type":"00","terminal_id":"TERM01"}

2. Format ISO 8583 dict (MTI 0100) :
   {"mti":"0100","fields":{"2":"4111111111111111","4":"000000005000","49":"978",...}}

La réponse est toujours un JSON plat :
   {"mti":"0110","approved":true,"response_code":"00","auth_code":"123456",
    "amount":5000,"pan_masked":"411111****1111","transaction_id":"...",
    "tier":"SMALL","cb_allowed":true}

En cas d'erreur de format : {"mti":"0110","approved":false,"response_code":"30","error":"..."}
"""

import json
import logging
import socket
import struct
import threading

from emv.authorization import authorize
from iso8583.message import parse_from_dict, build_authorization_request

logger = logging.getLogger(__name__)

LENGTH_PREFIX_FMT = ">I"
LENGTH_PREFIX_SIZE = struct.calcsize(LENGTH_PREFIX_FMT)
MAX_MESSAGE_SIZE = 64 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# Encodage / décodage sur le fil
# ─────────────────────────────────────────────────────────────────────────────

def encode_message(payload: dict) -> bytes:
    """Sérialise un dict en [longueur 4 octets][JSON UTF-8]."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = struct.pack(LENGTH_PREFIX_FMT, len(body))
    return header + body


def decode_message(data: bytes) -> dict:
    """Désérialise des bytes JSON en dict."""
    return json.loads(data.decode("utf-8"))


def recv_message(sock: socket.socket) -> dict:
    """
    Lit un message complet depuis un socket.
    Lève ConnectionError si la connexion est fermée proprement.
    Lève ValueError si le message est trop volumineux ou malformé.
    """
    header = _recv_exact(sock, LENGTH_PREFIX_SIZE)
    if not header:
        raise ConnectionError("Connexion fermée par le client")
    length = struct.unpack(LENGTH_PREFIX_FMT, header)[0]
    if length == 0:
        raise ValueError("Longueur de message nulle")
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message trop volumineux : {length} octets (max {MAX_MESSAGE_SIZE})")
    body = _recv_exact(sock, length)
    if not body:
        raise ConnectionError("Connexion fermée pendant la réception du corps")
    return decode_message(body)


def send_message(sock: socket.socket, payload: dict) -> None:
    """Envoie un dict JSON sur le socket avec préfixe de longueur."""
    sock.sendall(encode_message(payload))


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Lit exactement n octets depuis le socket."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return b""
        buf.extend(chunk)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Traitement d'une requête d'autorisation
# ─────────────────────────────────────────────────────────────────────────────

def _iso8583_to_auth_params(msg) -> dict:
    """Convertit un ISO8583Message en paramètres pour authorize()."""
    return {
        "pan":              msg.pan,
        "amount":           msg.amount,
        "currency":         msg.currency_code,
        "transaction_type": msg.transaction_type,
        "field_55":         msg.emv_data,
        "terminal_id":      msg.terminal_id or None,
        "merchant_id":      msg.merchant_id or None,
        "merchant_name":    msg.merchant_name or None,
        "pos_entry_mode":   msg.pos_entry_mode or "05",
        "skip_crypto":      True,
    }


def process_request(request: dict) -> dict:
    """
    Traite une requête d'autorisation ou de redressement
    (format natif ou ISO 8583 dict).
    Retourne un dict de réponse prêt à être sérialisé.
    """
    try:
        # ── Détection du format ──────────────────────────────────────────────
        if "mti" in request:
            iso_msg = parse_from_dict(request)

            # Redressements 0400 / 0420
            if iso_msg.mti in ("0400", "0420"):
                return _process_reversal_iso(iso_msg)

            if iso_msg.mti not in ("0100", "0200"):
                return _error_response("30", f"MTI non supporté : {iso_msg.mti}")
            params = _iso8583_to_auth_params(iso_msg)
            rrn = iso_msg.rrn
        else:
            pan   = request.get("pan", "")
            if not pan:
                return _error_response("30", "Champ 'pan' manquant")
            params = {
                "pan":              pan,
                "amount":           int(request.get("amount", 0)),
                "currency":         str(request.get("currency", "978")),
                "transaction_type": str(request.get("transaction_type", "00")),
                "field_55":         request.get("field_55"),
                "terminal_id":      request.get("terminal_id"),
                "merchant_id":      request.get("merchant_id"),
                "merchant_name":    request.get("merchant_name"),
                "pos_entry_mode":   request.get("pos_entry_mode", "05"),
                "mcc":              request.get("mcc"),
                "is_contactless":   bool(request.get("is_contactless", False)),
                "skip_crypto":      bool(request.get("skip_crypto", True)),
            }
            rrn = request.get("rrn", "")

        # ── Autorisation ────────────────────────────────────────────────────
        result = authorize(**{k: v for k, v in params.items() if v is not None})

        # ── Construction de la réponse ───────────────────────────────────────
        pan_raw = params["pan"].replace(" ", "")
        pan_masked = pan_raw[:6] + "*" * (len(pan_raw) - 10) + pan_raw[-4:]

        tier_name = None
        cb_allowed = None
        if result.amount_decision:
            tier_name = result.amount_decision.tier.name
        if result.cb_result:
            cb_allowed = result.cb_result.allowed

        resp = {
            "mti":             "0110",
            "rrn":             rrn,
            "approved":        result.approved,
            "response_code":   result.response_code,
            "amount":          params["amount"],
            "currency":        params.get("currency", "978"),
            "pan_masked":      pan_masked,
            "transaction_id":  result.transaction.id if result.transaction else None,
            "tier":            tier_name,
            "cb_allowed":      cb_allowed,
            "message":         result.message,
        }
        if result.approved and result.auth_code:
            resp["auth_code"] = result.auth_code
            if result.arpc:
                resp["arpc"] = result.arpc.hex().upper() if isinstance(result.arpc, bytes) else result.arpc
            if result.issuer_auth_data:
                resp["issuer_auth_data"] = result.issuer_auth_data

        return resp

    except json.JSONDecodeError as exc:
        return _error_response("30", f"JSON invalide : {exc}")
    except (KeyError, TypeError, ValueError) as exc:
        return _error_response("30", f"Requête malformée : {exc}")
    except Exception as exc:
        logger.exception("Erreur inattendue lors du traitement TCP")
        return _error_response("96", f"Erreur système : {exc}")


def _process_reversal_iso(iso_msg) -> dict:
    """
    Traite un redressement ISO 8583 (MTI 0400 ou 0420).
    Identifie la transaction originale par champ 37 (RRN) ou champ 125 (ID interne).
    """
    from emv.reversal import process_reversal

    rrn = iso_msg.rrn or None
    txn_id = iso_msg.fields.get(125)
    reversal_amount = iso_msg.reversal_amount
    terminal_id = iso_msg.terminal_id or None
    is_advice = iso_msg.mti == "0420"

    result = process_reversal(
        transaction_id=txn_id,
        rrn=rrn,
        reversal_amount=reversal_amount,
        reversal_rrn=None,
        terminal_id=terminal_id,
        is_advice=is_advice,
    )

    response_mti = "0430" if is_advice else "0410"
    resp = {
        "mti":            response_mti,
        "rrn":            rrn,
        "accepted":       result.accepted,
        "response_code":  result.response_code,
        "reversal_amount": result.reversal_amount,
        "message":        result.message,
        "is_advice":      result.is_advice,
    }
    if result.original_transaction:
        resp["original_transaction_id"] = result.original_transaction.id
        pan_raw = result.original_transaction.pan
        resp["pan_masked"] = pan_raw[:6] + "*" * (len(pan_raw) - 10) + pan_raw[-4:]

    return resp


def _error_response(code: str, error: str) -> dict:
    return {
        "mti":           "0110",
        "approved":      False,
        "response_code": code,
        "error":         error,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gestionnaire de connexion (1 thread par client)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_client(conn: socket.socket, addr) -> None:
    """Gère toute la durée de vie d'une connexion client."""
    logger.info("[TCP] Client connecté : %s:%d", addr[0], addr[1])
    try:
        while True:
            try:
                request = recv_message(conn)
            except ConnectionError:
                break
            except ValueError as exc:
                send_message(conn, _error_response("30", str(exc)))
                continue
            except Exception as exc:
                logger.warning("[TCP] Erreur de réception depuis %s : %s", addr, exc)
                break

            logger.debug("[TCP] Requête de %s : %s", addr, request)
            response = process_request(request)
            logger.info(
                "[TCP] %s → %s | RC=%s | Approuvé=%s",
                addr[0],
                request.get("pan", "?")[-4:],
                response.get("response_code"),
                response.get("approved"),
            )
            try:
                send_message(conn, response)
            except OSError as exc:
                logger.warning("[TCP] Erreur d'envoi vers %s : %s", addr, exc)
                break
    finally:
        conn.close()
        logger.info("[TCP] Client déconnecté : %s:%d", addr[0], addr[1])


# ─────────────────────────────────────────────────────────────────────────────
# Serveur TCP principal
# ─────────────────────────────────────────────────────────────────────────────

class TCPAuthorizationServer:
    """
    Serveur TCP d'autorisation EMV.

    Usage :
        server = TCPAuthorizationServer(host="0.0.0.0", port=8583)
        server.start()          # non bloquant (thread daemon)
        ...
        server.stop()
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8583):
        self.host = host
        self.port = port
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Démarre le serveur dans un thread daemon."""
        if self.running:
            return
        self._stop_event.clear()
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(32)
        self._server_sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._serve, daemon=True, name="tcp-auth-server")
        self._thread.start()
        logger.info("[TCP] Serveur d'autorisation démarré sur %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Arrête proprement le serveur."""
        self._stop_event.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("[TCP] Serveur d'autorisation arrêté")

    def _serve(self) -> None:
        """Boucle d'acceptation des connexions entrantes."""
        while not self._stop_event.is_set():
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(
                target=_handle_client, args=(conn, addr),
                daemon=True, name=f"tcp-client-{addr[0]}:{addr[1]}"
            )
            t.start()
