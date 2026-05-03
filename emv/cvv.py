"""
CVV/CVC Computation and Verification — EMV / Visa / Mastercard
Implémente :
  - CVV1  (piste 2, stocké en bande magnétique)
  - CVV2  (imprimé au dos de la carte, MOTO/e-commerce)
  - iCVV  (puce EMV, code dynamique)

Algorithme standard :
  1. Construire le bloc de données : PAN (19 chiffres) + date d'expiration YYMM + code de service (3 chiffres)
  2. Séparer en deux blocs de 8 octets (encode BCD, pad 0 à droite)
  3. DES-ECB chiffrer le bloc gauche avec CVK-1
  4. XOR résultat avec bloc droit
  5. 3DES-ECB chiffrer le résultat avec CVK-1 || CVK-2
  6. Décimaliser : pour chaque nibble, prendre le chiffre si 0-9, sinon (nibble - 10 + 0 → 0-5)
  7. Prendre les N premiers chiffres décimalisés

Codes de service par type de CVV :
  CVV1  : "101"
  CVV2  : "999"
  iCVV  : "999" avec service code "099" (dépend de l'émetteur)
"""

from Crypto.Cipher import DES, DES3


class CVVError(Exception):
    pass


def _compute_cvv_raw(pan: str, expiry_yymm: str, service_code: str,
                     cvk1: bytes, cvk2: bytes) -> str:
    """
    Calcul CVV/CVC brut.

    pan         : PAN sous forme de chaîne de chiffres (sans espaces)
    expiry_yymm : date d'expiration au format YYMM (ex. "2812")
    service_code: code de service 3 chiffres (ex. "101")
    cvk1, cvk2  : clés de vérification CVV (8 octets chacune)

    Retourne une chaîne de 32 chiffres décimalisés (on prendra les N premiers).
    """
    if len(cvk1) != 8 or len(cvk2) != 8:
        raise CVVError("CVK1 et CVK2 doivent être de 8 octets chacune")

    pan_clean = str(pan).replace(" ", "").replace("-", "")
    if not pan_clean.isdigit():
        raise CVVError("PAN doit contenir uniquement des chiffres")

    expiry = str(expiry_yymm).replace(" ", "")
    if len(expiry) != 4:
        raise CVVError("expiry_yymm doit être au format YYMM (4 chiffres)")

    svc = str(service_code).zfill(3)

    # Construction du champ de données : PAN || expiry || service_code
    # padde à 32 nibbles (16 octets BCD), rempli de '0' à droite
    data_str = (pan_clean + expiry + svc).ljust(32, '0')[:32]

    try:
        data_bytes = bytes.fromhex(data_str)
    except ValueError as e:
        raise CVVError("Erreur encodage données CVV : {}".format(str(e)))

    left_block = data_bytes[:8]
    right_block = data_bytes[8:]

    cipher_left = DES.new(cvk1, DES.MODE_ECB)
    step1 = cipher_left.encrypt(left_block)

    step2 = bytes(a ^ b for a, b in zip(step1, right_block))

    triple_key = cvk1 + cvk2
    if len(triple_key) == 16:
        triple_key = triple_key + cvk1
    cipher_3des = DES3.new(triple_key, DES3.MODE_ECB)
    result = cipher_3des.encrypt(step2)

    hex_result = result.hex().upper()
    digits = ""
    pass1 = ""
    pass2 = ""
    for ch in hex_result:
        nibble = int(ch, 16)
        if nibble <= 9:
            pass1 += str(nibble)
        else:
            pass2 += str(nibble - 10)

    decimalized = pass1 + pass2
    return decimalized


def compute_cvv1(pan: str, expiry_yymm: str, cvk1: bytes, cvk2: bytes,
                 service_code: str = "101", digits: int = 3) -> str:
    """
    Calcule CVV1 (piste 2 — authentification mag stripe).
    service_code par défaut "101" (international, PIN requis).
    """
    raw = _compute_cvv_raw(pan, expiry_yymm, service_code, cvk1, cvk2)
    return raw[:digits]


def compute_cvv2(pan: str, expiry_yymm: str, cvk1: bytes, cvk2: bytes,
                 digits: int = 3) -> str:
    """
    Calcule CVV2 (imprimé, e-commerce/MOTO).
    Code de service fixé à "999".
    """
    raw = _compute_cvv_raw(pan, expiry_yymm, "999", cvk1, cvk2)
    return raw[:digits]


def compute_icvv(pan: str, expiry_yymm: str, cvk1: bytes, cvk2: bytes,
                 digits: int = 3) -> str:
    """
    Calcule iCVV (puce EMV — différent du CVV1 pour détecter la copie piste).
    Code de service fixé à "999", iCVV doit être DIFFÉRENT de CVV1.
    """
    raw = _compute_cvv_raw(pan, expiry_yymm, "999", cvk1, cvk2)
    return raw[:digits]


def verify_cvv(provided: str, pan: str, expiry_yymm: str,
               cvk1: bytes, cvk2: bytes,
               cvv_type: str = "CVV2", service_code: str = "101") -> bool:
    """
    Vérifie un CVV fourni par le porteur.

    cvv_type : "CVV1", "CVV2", "iCVV"
    Retourne True si le CVV est correct, False sinon.
    """
    if not provided or not provided.strip().isdigit():
        return False
    digits = len(provided.strip())
    try:
        if cvv_type == "CVV1":
            expected = compute_cvv1(pan, expiry_yymm, cvk1, cvk2,
                                    service_code=service_code, digits=digits)
        elif cvv_type == "CVV2":
            expected = compute_cvv2(pan, expiry_yymm, cvk1, cvk2, digits=digits)
        elif cvv_type == "iCVV":
            expected = compute_icvv(pan, expiry_yymm, cvk1, cvk2, digits=digits)
        else:
            return False
        return provided.strip() == expected
    except CVVError:
        return False


def generate_cvv_set(pan: str, expiry_yymm: str,
                     cvk1: bytes, cvk2: bytes) -> dict:
    """
    Génère l'ensemble CVV1 + CVV2 + iCVV pour une carte.
    Utilisé à l'initialisation des cartes de test.
    """
    try:
        return {
            "cvv1": compute_cvv1(pan, expiry_yymm, cvk1, cvk2),
            "cvv2": compute_cvv2(pan, expiry_yymm, cvk1, cvk2),
            "icvv": compute_icvv(pan, expiry_yymm, cvk1, cvk2),
        }
    except CVVError as e:
        return {"error": str(e)}
