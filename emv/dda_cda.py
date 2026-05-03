"""
DDA / CDA — Authentification Offline Dynamique — E3
====================================================
DDA  (Dynamic Data Authentication) : EMV Book 2 §6.3
CDA  (Combined DDA/Application Cryptogram) : EMV Book 2 §6.5

DDA :
  1. Terminal génère les données DDOL (Dynamic Data Object List)
  2. Carte signe les données avec sa clé privée ICC → SDAD (tag 9F4B)
  3. Terminal vérifie avec la clé publique ICC (issue des certificats PKI)
  4. Si OK → Offline Data Auth réussie

CDA :
  Idem DDA mais le cryptogramme AC est aussi inclus dans la signature.
  Tag 9F27 (Cryptogram Information Data) : bit 0x40 = CDA

Utilise emv.pki pour obtenir les clés RSA par PAN.
"""

import os
import hmac
import hashlib
import logging
import struct
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from emv.pki import (get_icc_key_pair, get_issuer_key_pair,
                          build_icc_cert, build_issuer_cert, is_available)
    from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
    from cryptography.hazmat.primitives import hashes
    _PKI_AVAILABLE = True
except ImportError:
    _PKI_AVAILABLE = False
    logger.warning("PKI non disponible — DDA/CDA désactivés")


# ── Constantes ────────────────────────────────────────────────────────────────
DDOL_DEFAULT_TAGS = [
    "9F37",  # Unpredictable Number (4 octets)
]
CID_ARQC   = 0x80   # Application Cryptogram (ARQC)
CID_TC     = 0x40   # Transaction Certificate (TC / approuvé offline)
CID_AAC    = 0x00   # Application Authentication Cryptogram (refus offline)
CID_CDA    = 0x10   # CDA requested bit


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_dynamic_data(unpredictable_number: bytes,
                        additional_data: bytes = None) -> bytes:
    """
    Construit les données dynamiques à signer pour DDA.
    Format simplifié : LEN || Unpredictable Number || Additional Data
    """
    un = unpredictable_number[:4].ljust(4, b'\x00')
    add = additional_data or b""
    payload = un + add
    return bytes([len(payload)]) + payload


def _build_cda_data(unpredictable_number: bytes,
                    arqc: bytes,
                    pan_hash: bytes = None) -> bytes:
    """
    Construit les données à signer pour CDA.
    Format : LEN || UN || ARQC || PAN_HASH (optionnel)
    """
    un      = unpredictable_number[:4].ljust(4, b'\x00')
    arqc_b  = (arqc or b'\x00' * 8)[:8]
    ph      = (pan_hash or b"")[:8]
    payload = un + arqc_b + ph
    return bytes([len(payload)]) + payload


# ── DDA ───────────────────────────────────────────────────────────────────────

def sign_dda(pan: str,
             unpredictable_number: bytes = None,
             additional_data: bytes = None) -> dict:
    """
    Simule la signature DDA par la carte (ICC private key).

    Paramètres :
      pan                  — PAN de la carte
      unpredictable_number — 4 octets aléatoires du terminal (tag 9F37)
      additional_data      — données DDOL supplémentaires

    Retourne :
      sdad_hex      — Signed Dynamic Application Data (tag 9F4B)
      un_hex        — Unpredictable Number utilisé
      data_hex      — données signées (pour debug)
      success       — bool
    """
    if not _PKI_AVAILABLE or not is_available():
        return {
            "success": False,
            "reason": "PKI non disponible",
            "sdad_hex": None,
        }
    un = unpredictable_number or os.urandom(4)
    data = _build_dynamic_data(un, additional_data)
    try:
        icc_priv, _ = get_icc_key_pair(pan)
        signature   = icc_priv.sign(data, rsa_padding.PKCS1v15(), hashes.SHA256())
        logger.debug("DDA signed: PAN=...%s UN=%s", pan[-4:], un.hex())
        return {
            "success":   True,
            "sdad_hex":  signature.hex().upper(),
            "un_hex":    un.hex().upper(),
            "data_hex":  data.hex().upper(),
            "signed_at": _now_iso(),
            "auth_type": "DDA",
        }
    except Exception as exc:
        logger.error("DDA sign error: %s", exc)
        return {"success": False, "reason": str(exc), "sdad_hex": None}


def verify_dda(pan: str,
               sdad_hex: str,
               unpredictable_number_hex: str,
               additional_data: bytes = None) -> dict:
    """
    Vérifie une signature DDA reçue du terminal.

    Retourne success=True si la signature est valide.
    """
    if not _PKI_AVAILABLE or not is_available():
        return {"success": False, "reason": "PKI non disponible", "valid": False}
    try:
        sdad = bytes.fromhex(sdad_hex)
        un   = bytes.fromhex(unpredictable_number_hex)
        data = _build_dynamic_data(un, additional_data)
        _, icc_pub = get_icc_key_pair(pan)
        icc_pub.verify(sdad, data, rsa_padding.PKCS1v15(), hashes.SHA256())
        logger.debug("DDA verified OK: PAN=...%s", pan[-4:])
        return {
            "success": True,
            "valid":   True,
            "auth_type": "DDA",
            "verified_at": _now_iso(),
        }
    except Exception as exc:
        logger.warning("DDA verify FAILED: PAN=...%s error=%s", pan[-4:], exc)
        return {"success": True, "valid": False, "reason": str(exc)}


# ── CDA ───────────────────────────────────────────────────────────────────────

def sign_cda(pan: str,
             unpredictable_number: bytes = None,
             arqc_hex: str = None,
             cryptogram_info: int = None) -> dict:
    """
    Simule la signature CDA par la carte (ICC private key).
    Inclut l'ARQC dans la donnée signée.

    Paramètres :
      pan                  — PAN de la carte
      unpredictable_number — 4 octets aléatoires du terminal
      arqc_hex             — ARQC généré (tag 9F26, 8 octets)
      cryptogram_info      — CID byte (tag 9F27) — 0x40 si CDA

    Retourne :
      sdad_hex    — SDAD (tag 9F4B)
      cid         — Cryptogram Information Data
      success     — bool
    """
    if not _PKI_AVAILABLE or not is_available():
        return {"success": False, "reason": "PKI non disponible", "sdad_hex": None}
    un     = unpredictable_number or os.urandom(4)
    arqc_b = bytes.fromhex(arqc_hex) if arqc_hex else b'\x00' * 8
    ph     = hashlib.sha256(pan.encode()).digest()[:8]
    data   = _build_cda_data(un, arqc_b, ph)
    try:
        icc_priv, _ = get_icc_key_pair(pan)
        signature   = icc_priv.sign(data, rsa_padding.PKCS1v15(), hashes.SHA256())
        cid         = cryptogram_info if cryptogram_info is not None else (CID_ARQC | CID_CDA)
        logger.debug("CDA signed: PAN=...%s UN=%s ARQC=%s",
                     pan[-4:], un.hex(), arqc_hex or "N/A")
        return {
            "success":   True,
            "sdad_hex":  signature.hex().upper(),
            "un_hex":    un.hex().upper(),
            "arqc_hex":  arqc_hex,
            "cid_hex":   f"{cid:02X}",
            "data_hex":  data.hex().upper(),
            "signed_at": _now_iso(),
            "auth_type": "CDA",
        }
    except Exception as exc:
        logger.error("CDA sign error: %s", exc)
        return {"success": False, "reason": str(exc), "sdad_hex": None}


def verify_cda(pan: str,
               sdad_hex: str,
               unpredictable_number_hex: str,
               arqc_hex: str = None) -> dict:
    """
    Vérifie une signature CDA.
    """
    if not _PKI_AVAILABLE or not is_available():
        return {"success": False, "reason": "PKI non disponible", "valid": False}
    try:
        sdad   = bytes.fromhex(sdad_hex)
        un     = bytes.fromhex(unpredictable_number_hex)
        arqc_b = bytes.fromhex(arqc_hex) if arqc_hex else b'\x00' * 8
        ph     = hashlib.sha256(pan.encode()).digest()[:8]
        data   = _build_cda_data(un, arqc_b, ph)
        _, icc_pub = get_icc_key_pair(pan)
        icc_pub.verify(sdad, data, rsa_padding.PKCS1v15(), hashes.SHA256())
        logger.debug("CDA verified OK: PAN=...%s", pan[-4:])
        return {
            "success": True,
            "valid":   True,
            "auth_type": "CDA",
            "verified_at": _now_iso(),
        }
    except Exception as exc:
        logger.warning("CDA verify FAILED: PAN=...%s error=%s", pan[-4:], exc)
        return {"success": True, "valid": False, "reason": str(exc)}


# ── Détection type d'authentification offline ─────────────────────────────────

def detect_offline_auth_type(emv_parsed: dict) -> str:
    """
    Détermine le type d'authentification offline à partir du champ 55 parsé.
    Retourne 'CDA', 'DDA', 'SDA', ou 'NONE'.
    """
    # Tag 9F4B (SDAD) présent → DDA ou CDA
    sdad = emv_parsed.get("sdad") or emv_parsed.get("9F4B")
    if sdad:
        # Tag 9F27 bit 0x10 → CDA
        cid_raw = emv_parsed.get("cryptogram_info")
        if cid_raw:
            cid = cid_raw[0] if isinstance(cid_raw, (bytes, bytearray)) else cid_raw
            if cid & 0x10:
                return "CDA"
        return "DDA"
    # Tag 93 (Signed Static Application Data) → SDA
    ssad = emv_parsed.get("93") or emv_parsed.get("ssad")
    if ssad:
        return "SDA"
    return "NONE"


# ── Vérification complète (dispatch DDA/CDA) ─────────────────────────────────

def verify_offline_auth(pan: str, emv_parsed: dict,
                        skip: bool = False) -> dict:
    """
    Point d'entrée unifié : vérifie DDA ou CDA selon le champ 55.

    Retourne un dict avec auth_type, valid, et le détail.
    """
    if skip or not _PKI_AVAILABLE:
        return {"auth_type": "SKIPPED", "valid": True,
                "reason": "skip=True ou PKI indisponible"}

    auth_type = detect_offline_auth_type(emv_parsed)

    if auth_type == "NONE":
        return {"auth_type": "NONE", "valid": True,
                "reason": "Aucun tag SDAD/SSAD présent — SDA offline non requis"}

    sdad_raw = (emv_parsed.get("sdad") or emv_parsed.get("9F4B") or b"")
    sdad_hex = sdad_raw.hex() if isinstance(sdad_raw, (bytes, bytearray)) else sdad_raw
    un_raw   = emv_parsed.get("unpredictable_number") or emv_parsed.get("9F37") or b'\x00\x00\x00\x00'
    un_hex   = un_raw.hex() if isinstance(un_raw, (bytes, bytearray)) else un_raw

    if auth_type == "CDA":
        arqc_raw = emv_parsed.get("cryptogram") or b""
        arqc_hex = arqc_raw.hex() if isinstance(arqc_raw, (bytes, bytearray)) else None
        return verify_cda(pan, sdad_hex, un_hex, arqc_hex)
    else:
        return verify_dda(pan, sdad_hex, un_hex)


# ── API publique ───────────────────────────────────────────────────────────────

def is_available_dda_cda() -> bool:
    return _PKI_AVAILABLE and is_available()
