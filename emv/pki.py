"""
PKI Simulée — Certificats Émetteurs CB — C2
==========================================
Hiérarchie CB simplifiée :

  CA Root Key (1 clé globale)
      └─ Issuer Key (1 par grande plage BIN : 4xxx, 5xxx, 6xxx, autres)
             └─ ICC Key (1 par PAN, générée à la demande et mise en cache)

Format des certificats : simplifié EMV Book 2 Annex B (non certifié CB réel).
Taille des clés RSA : 1024 bits (simulation — non production).

Tags EMV utilisés :
  0x8F  — CA Public Key Index
  0x90  — Issuer Public Key Certificate
  0x9F32 — Issuer Public Key Exponent
  0x9F46 — ICC Public Key Certificate
  0x9F47 — ICC Public Key Exponent
  0x9F48 — ICC Leftover Public Key Remainder

Utilisation par E3 (DDA/CDA) :
  from emv.pki import get_icc_key_pair, get_issuer_key_pair, get_ca_key_pair
"""

import os
import hashlib
import logging
from functools import lru_cache
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes, serialization
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning("Module 'cryptography' non disponible — PKI simulée désactivée")

# ── Constantes ────────────────────────────────────────────────────────────────
RSA_EXPONENT  = 65537
RSA_KEY_SIZE  = 1024      # Simulation — use 2048+ en production
CA_KEY_INDEX  = 0x05      # Index de clé CA (tag 8F)

# ── Génération des clés ───────────────────────────────────────────────────────

def _generate_rsa_key(key_size: int = RSA_KEY_SIZE):
    """Génère une paire de clés RSA."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Module cryptography requis pour la PKI")
    return rsa.generate_private_key(RSA_EXPONENT, key_size)


def _serialize_public_key(private_key) -> bytes:
    """Sérialise la clé publique en DER."""
    return private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _get_modulus_bytes(private_key) -> bytes:
    """Retourne le modulus RSA comme bytes."""
    return private_key.public_key().public_numbers().n.to_bytes(
        RSA_KEY_SIZE // 8, "big"
    )


def _get_exponent_bytes(private_key) -> bytes:
    """Retourne l'exposant public RSA comme bytes (min 3 octets)."""
    e = private_key.public_key().public_numbers().e
    length = max(3, (e.bit_length() + 7) // 8)
    return e.to_bytes(length, "big")


# ── Cache des clés ────────────────────────────────────────────────────────────
_ca_key       = None
_issuer_keys  = {}   # bin_prefix → private_key
_icc_keys     = {}   # pan_hash → private_key


def _get_ca_key():
    """Retourne (ou génère) la clé CA root."""
    global _ca_key
    if _ca_key is None:
        logger.info("PKI : génération de la clé CA root (1024-bit)…")
        _ca_key = _generate_rsa_key()
        logger.info("PKI : clé CA prête")
    return _ca_key


def _get_issuer_key(bin_prefix: str):
    """Retourne (ou génère) la clé Issuer pour le préfixe BIN donné."""
    key = bin_prefix[0]   # groupement par premier chiffre
    if key not in _issuer_keys:
        logger.debug("PKI : génération de la clé Issuer pour BIN '%s'…", key)
        _issuer_keys[key] = _generate_rsa_key()
    return _issuer_keys[key]


def _get_icc_key(pan: str):
    """Retourne (ou génère) la clé ICC pour le PAN donné."""
    ph = hashlib.sha256(pan.encode()).hexdigest()[:16]
    if ph not in _icc_keys:
        logger.debug("PKI : génération de la clé ICC pour PAN ...%s", pan[-4:])
        _icc_keys[ph] = _generate_rsa_key()
    return _icc_keys[ph]


# ── Construction des certificats EMV ─────────────────────────────────────────

def _sign_data(private_key, data: bytes) -> bytes:
    """Signature RSA PKCS#1 v1.5 (EMV Book 2)."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Module cryptography requis")
    return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())


def _verify_signature(public_key, data: bytes, signature: bytes) -> bool:
    """Vérifie une signature RSA PKCS#1 v1.5."""
    if not _CRYPTO_AVAILABLE:
        return False
    try:
        public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def build_issuer_cert(pan: str) -> dict:
    """
    Construit un certificat Issuer PK simplifié (tag 90).
    Retourne un dict avec les tags EMV nécessaires.
    """
    if not _CRYPTO_AVAILABLE:
        return {"available": False}
    ca_key     = _get_ca_key()
    issuer_key = _get_issuer_key(pan[:1])

    issuer_mod  = _get_modulus_bytes(issuer_key)
    issuer_exp  = _get_exponent_bytes(issuer_key)

    # Données à signer : expiry simulé + modulus tronqué
    expiry = (datetime.utcnow().year % 100 + 5)  # +5 ans
    cert_data = bytes([expiry % 256, 0x01]) + issuer_mod[:14]  # 16 octets résumé
    signature  = _sign_data(ca_key, cert_data)

    return {
        "tag_8F":   bytes([CA_KEY_INDEX]),       # CA PK Index
        "tag_90":   signature,                    # Issuer PK Certificate
        "tag_9F32": issuer_exp,                  # Issuer PK Exponent
        "issuer_modulus": issuer_mod,
        "available": True,
    }


def build_icc_cert(pan: str) -> dict:
    """
    Construit un certificat ICC PK simplifié (tag 9F46).
    Retourne un dict avec les tags EMV nécessaires.
    """
    if not _CRYPTO_AVAILABLE:
        return {"available": False}
    issuer_key = _get_issuer_key(pan[:1])
    icc_key    = _get_icc_key(pan)

    icc_mod   = _get_modulus_bytes(icc_key)
    icc_exp   = _get_exponent_bytes(icc_key)

    cert_data = pan[-8:].encode() + icc_mod[:8]  # résumé 16 octets
    signature  = _sign_data(issuer_key, cert_data)

    return {
        "tag_9F46": signature,    # ICC PK Certificate
        "tag_9F47": icc_exp,      # ICC PK Exponent
        "tag_9F48": icc_mod[RSA_KEY_SIZE // 8 - 8:],  # Remainder (si longueur > N-36)
        "icc_modulus": icc_mod,
        "available": True,
    }


# ── API publique ───────────────────────────────────────────────────────────────

def get_ca_key_pair():
    """Retourne la paire de clés CA (private_key, public_key)."""
    k = _get_ca_key()
    return k, k.public_key()


def get_issuer_key_pair(pan: str):
    """Retourne la paire de clés Issuer pour ce PAN."""
    k = _get_issuer_key(pan[:1])
    return k, k.public_key()


def get_icc_key_pair(pan: str):
    """Retourne la paire de clés ICC pour ce PAN."""
    k = _get_icc_key(pan)
    return k, k.public_key()


def get_full_pki_info(pan: str) -> dict:
    """Retourne les informations PKI complètes pour un PAN (sans clés privées)."""
    if not _CRYPTO_AVAILABLE:
        return {"available": False, "reason": "cryptography non installé"}
    issuer_cert = build_issuer_cert(pan)
    icc_cert    = build_icc_cert(pan)
    ca_key      = _get_ca_key()
    return {
        "available":        True,
        "ca_key_index":     f"0x{CA_KEY_INDEX:02X}",
        "ca_modulus_hex":   _get_modulus_bytes(ca_key).hex().upper()[:32] + "…",
        "issuer_cert_hex":  issuer_cert["tag_90"].hex().upper()[:32] + "…",
        "icc_cert_hex":     icc_cert["tag_9F46"].hex().upper()[:32] + "…",
        "icc_exp_hex":      icc_cert["tag_9F47"].hex().upper(),
        "pan_last4":        pan[-4:],
    }


def is_available() -> bool:
    """Indique si la PKI est disponible (dépend de cryptography)."""
    return _CRYPTO_AVAILABLE
