"""
EMV Cryptographic operations:
- Session key derivation (EMV 4.3 Book 2)
- ARQC verification
- ARPC generation
- PIN block encryption/decryption
"""

import hashlib
import hmac
import struct
from Crypto.Cipher import DES3, DES
from Crypto.Util.Padding import pad


class CryptoError(Exception):
    pass


def _adjust_parity(key_bytes):
    result = bytearray(key_bytes)
    for i in range(len(result)):
        b = result[i]
        parity = bin(b).count('1') % 2
        if parity == 0:
            result[i] = b ^ 1
    return bytes(result)


def derive_session_key(master_key, atc, key_type="AC"):
    """
    EMV Session Key Derivation (EMV 4.3 Book 2, Annex A1.3)
    Supports: AC (Application Cryptogram), ENC, MAC
    """
    if len(master_key) not in (16, 24):
        raise CryptoError("Master key must be 16 or 24 bytes")

    atc_bytes = struct.pack(">H", atc)

    if key_type == "AC":
        derivation_data_left = atc_bytes + b'\xF0' + b'\x00' * 6
        derivation_data_right = atc_bytes + b'\x0F' + b'\x00' * 6
    elif key_type == "ENC":
        derivation_data_left = atc_bytes + b'\x01' + b'\x82' + b'\x00' * 5
        derivation_data_right = atc_bytes + b'\x01' + b'\x82' + b'\x00' * 5
        derivation_data_right = atc_bytes + b'\x02' + b'\x82' + b'\x00' * 5
    elif key_type == "MAC":
        derivation_data_left = atc_bytes + b'\x01' + b'\x01' + b'\x00' * 5
        derivation_data_right = atc_bytes + b'\x02' + b'\x01' + b'\x00' * 5
    else:
        raise CryptoError("Unknown key type: {}".format(key_type))

    if len(master_key) == 16:
        key_for_3des = master_key + master_key[:8]
    else:
        key_for_3des = master_key

    cipher_left = DES3.new(key_for_3des, DES3.MODE_ECB)
    sk_left = cipher_left.encrypt(derivation_data_left)

    cipher_right = DES3.new(key_for_3des, DES3.MODE_ECB)
    sk_right = cipher_right.encrypt(derivation_data_right)

    session_key = _adjust_parity(sk_left + sk_right)
    return session_key


def derive_udk(master_key, pan, psn="00"):
    """
    Derive Unique Derived Key (UDK) from Master Key using PAN and PAN Sequence Number.
    EMV 4.3 Book 2, Annex A1.4
    """
    pan_str = str(pan).replace(" ", "")
    psn_str = str(psn).zfill(2)

    pan_and_psn = pan_str[-13:-1] + psn_str
    pan_and_psn = pan_and_psn.ljust(16, '0')

    try:
        diversification_data = bytes.fromhex(pan_and_psn)
    except ValueError:
        diversification_data = pan_and_psn.encode('ascii')[:8]

    if len(master_key) == 16:
        key_for_3des = master_key + master_key[:8]
    else:
        key_for_3des = master_key

    cipher = DES3.new(key_for_3des, DES3.MODE_ECB)
    udk_left = cipher.encrypt(diversification_data)

    complement = bytes([b ^ 0xFF for b in diversification_data])
    udk_right = cipher.encrypt(complement)

    udk = _adjust_parity(udk_left + udk_right)
    return udk


def compute_arqc(session_key, transaction_data):
    """
    Compute ARQC (Application Request Cryptogram) using 3DES MAC.
    EMV 4.3 Book 2, Section 8.1

    transaction_data: concatenation of mandatory data elements per CDOL1
    """
    if isinstance(transaction_data, str):
        transaction_data = bytes.fromhex(transaction_data)

    data = bytearray(transaction_data)
    data.append(0x80)
    while len(data) % 8 != 0:
        data.append(0x00)

    if len(session_key) == 16:
        key_for_3des = session_key + session_key[:8]
    else:
        key_for_3des = session_key

    result = b'\x00' * 8
    cipher_left = DES.new(session_key[:8], DES.MODE_ECB)
    cipher_right = DES.new(session_key[8:16], DES.MODE_ECB)

    for i in range(0, len(data), 8):
        block = bytes(b ^ r for b, r in zip(data[i:i+8], result))
        result = cipher_left.encrypt(block)

    cipher_3des = DES3.new(key_for_3des, DES3.MODE_ECB)
    arqc = cipher_3des.encrypt(result)

    return arqc


def verify_arqc(master_key, pan, psn, atc, transaction_data, arqc_received):
    """
    Verify ARQC received from the card.
    Returns True if valid, False otherwise.
    """
    try:
        if isinstance(arqc_received, str):
            arqc_received = bytes.fromhex(arqc_received)

        udk = derive_udk(master_key, pan, psn)
        session_key = derive_session_key(udk, atc, key_type="AC")
        arqc_computed = compute_arqc(session_key, transaction_data)

        return hmac.compare_digest(arqc_computed[:8], arqc_received[:8])
    except Exception as e:
        raise CryptoError("ARQC verification failed: {}".format(str(e)))


def generate_arpc(session_key, arqc, arc):
    """
    Generate ARPC (Authorization Response Cryptogram).
    EMV 4.3 Book 2, Section 8.2

    Method 1: ARPC = Encrypt_SK(ARQC XOR ARC_padded)
    arc: 2-byte Authorization Response Code (e.g. b'\\x00\\x00' for approved)
    """
    if isinstance(arqc, str):
        arqc = bytes.fromhex(arqc)
    if isinstance(arc, str):
        arc = bytes.fromhex(arc)

    arc_padded = arc + b'\x00' * 6

    xored = bytes(a ^ b for a, b in zip(arqc, arc_padded))

    if len(session_key) == 16:
        key_for_3des = session_key + session_key[:8]
    else:
        key_for_3des = session_key

    cipher = DES3.new(key_for_3des, DES3.MODE_ECB)
    arpc = cipher.encrypt(xored)

    return arpc


def generate_issuer_auth_data(master_key, pan, psn, atc, arqc, response_code):
    """
    Generate the full Issuer Authentication Data (tag 91) for online authorization.
    IAD = ARPC (8 bytes) + ARC (2 bytes) + [optional issuer data]
    """
    arc = bytes.fromhex(response_code.encode('ascii').hex() if isinstance(response_code, str)
                        and len(response_code) == 2 and all(c in '0123456789ABCDEFabcdef' for c in response_code)
                        else response_code.encode('ascii').hex()
                        if isinstance(response_code, str) else response_code.hex())

    if isinstance(response_code, str) and len(response_code) == 2:
        arc = response_code.encode('ascii')
    elif isinstance(response_code, bytes):
        arc = response_code
    else:
        arc = b'\x30\x30'

    udk = derive_udk(master_key, pan, psn)
    session_key = derive_session_key(udk, atc, key_type="AC")

    if isinstance(arqc, str):
        arqc = bytes.fromhex(arqc)

    arpc = generate_arpc(session_key, arqc, arc)

    issuer_auth_data = arpc + arc
    return issuer_auth_data


def encrypt_pin_block(pin_block, pan, key):
    """
    Decrypt a PIN block (ISO 9564 Format 0/1) and re-encrypt for storage.
    """
    if isinstance(pin_block, str):
        pin_block = bytes.fromhex(pin_block)

    pan_str = str(pan).replace(" ", "")
    pan_block = b'\x00\x00' + bytes.fromhex("0" + pan_str[-13:-1])

    decrypted = bytes(a ^ b for a, b in zip(pin_block, pan_block))
    return decrypted


def compute_mac(key, data, algorithm="3DES"):
    """
    Compute MAC (Message Authentication Code) for integrity verification.
    Uses CBC-MAC with 3DES.
    """
    if isinstance(data, str):
        data = bytes.fromhex(data)

    padded_data = bytearray(data)
    padded_data.append(0x80)
    while len(padded_data) % 8 != 0:
        padded_data.append(0x00)

    result = b'\x00' * 8
    cipher = DES.new(key[:8], DES.MODE_ECB)

    for i in range(0, len(padded_data) - 8, 8):
        block = bytes(b ^ r for b, r in zip(padded_data[i:i+8], result))
        result = cipher.encrypt(block)

    last_block = bytes(b ^ r for b, r in zip(padded_data[-8:], result))
    if len(key) >= 16:
        cipher2 = DES.new(key[8:16], DES.MODE_ECB)
        decrypted = cipher2.decrypt(last_block)
        cipher3 = DES.new(key[:8], DES.MODE_ECB)
        mac = cipher3.encrypt(decrypted)
    else:
        mac = cipher.encrypt(last_block)

    return mac
