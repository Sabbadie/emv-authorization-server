"""
Issuer Script Processing — C4
Génération des scripts émetteur EMV (Tag 71 et Tag 72).

Tag 71 : Issuer Script Template 1 — exécuté AVANT la génération du cryptogramme AC
Tag 72 : Issuer Script Template 2 — exécuté APRÈS la génération du cryptogramme AC

Cas d'usage typiques :
  - Déblocage compteur PIN           → Tag 71 (UNBLOCK_PIN)
  - Mise à jour paramètres risque    → Tag 72 (UPDATE_RISK)
  - Remise à zéro compteur hors ligne→ Tag 72 (RESET_OFFLINE_COUNTER)
  - Blocage application (fraude)     → Tag 72 (BLOCK_APP)
  - Mise à jour ATC                  → Tag 72 (UPDATE_ATC)

Encodage BER-TLV simplifié (longueur sur 1 ou 2 octets, max 255 commandes).
"""
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── APDU simplifiés (CLA INS P1 P2 Lc Data) ──────────────────────────────────
ISSUER_APDU = {
    "UNBLOCK_PIN":            bytes.fromhex("8024000100"),
    "RESET_OFFLINE_COUNTER":  bytes.fromhex("80D400000290369F02"),
    "UPDATE_RISK_PARAMS":     bytes.fromhex("80D400000490369F049F02"),
    "BLOCK_APP":              bytes.fromhex("801E000000"),
    "RESET_ATC":              bytes.fromhex("80DA9F36020001"),
    "UPDATE_EXPIRY":          bytes.fromhex("80D400000290149F14"),
}

SCRIPT_REASON_LABELS = {
    "NONE":                 "Aucun script requis",
    "PIN_TRIES_EXCEEDED":   "Compteur PIN critique → déblocage",
    "OFFLINE_COUNTER_HIGH": "Cumul hors ligne élevé → remise à zéro",
    "FRAUD_BLOCK":          "Fraude détectée → blocage application",
    "ATC_ANOMALY":          "Anomalie ATC → remise à zéro",
    "ROUTINE":              "Mise à jour paramètres risque de routine",
}


def _build_tlv(tag: int, data: bytes) -> bytes:
    """Encode BER-TLV simplifié : tag (1 ou 2 octets) + longueur + valeur."""
    if tag <= 0xFF:
        tag_bytes = bytes([tag])
    else:
        tag_bytes = bytes([(tag >> 8) & 0xFF, tag & 0xFF])

    length = len(data)
    if length <= 127:
        len_bytes = bytes([length])
    else:
        len_bytes = bytes([0x81, length])

    return tag_bytes + len_bytes + data


def _build_script_template(tag_value: int, commands: list[bytes]) -> bytes:
    """Construit un template de script (Tag 71 ou Tag 72)."""
    if not commands:
        return b""
    inner = b"".join(commands)
    return _build_tlv(tag_value, inner)


def generate_scripts(card, authorized: bool = True,
                     reason: Optional[str] = None) -> dict:
    """
    Génère les scripts émetteur pour une carte après autorisation.

    Règles appliquées :
      1. PIN tries critique → Tag 71 UNBLOCK_PIN
      2. Cumul hors ligne élevé → Tag 72 RESET_OFFLINE_COUNTER
      3. Refus pour fraude → Tag 72 BLOCK_APP
      4. ATC anomalie → Tag 72 RESET_ATC
      5. Mise à jour risque de routine (toujours) → Tag 72 UPDATE_RISK_PARAMS

    Returns:
        {
            "tag_71": "<hex>",         # Script avant AC
            "tag_72": "<hex>",         # Script après AC
            "tag_71_b64": "<base64>",
            "tag_72_b64": "<base64>",
            "commands_71": [...],
            "commands_72": [...],
            "reason": "...",
            "has_scripts": bool
        }
    """
    commands_71: list[bytes] = []
    commands_72: list[bytes] = []
    reasons = []

    # ── Règle 1 : Déblocage PIN si compteur critique ──────────────────────────
    pin_tries     = getattr(card, "pin_tries",     0)
    max_pin_tries = getattr(card, "max_pin_tries", 3)
    if pin_tries >= max(max_pin_tries - 1, 1):
        commands_71.append(_build_tlv(0x86, ISSUER_APDU["UNBLOCK_PIN"]))
        reasons.append("PIN_TRIES_EXCEEDED")

    # ── Règle 2 : Reset compteur hors ligne si ≥ 3 tx consécutives ───────────
    consecutive = getattr(card, "consecutive_offline", 0)
    if consecutive >= 3:
        commands_72.append(_build_tlv(0x86, ISSUER_APDU["RESET_OFFLINE_COUNTER"]))
        reasons.append("OFFLINE_COUNTER_HIGH")

    # ── Règle 3 : Blocage application si refus fraude ─────────────────────────
    if not authorized and reason in ("fraud", "stolen", "lost"):
        commands_72.append(_build_tlv(0x86, ISSUER_APDU["BLOCK_APP"]))
        reasons.append("FRAUD_BLOCK")

    # ── Règle 4 : Mise à jour paramètres risque (routine) ────────────────────
    if authorized:
        commands_72.append(_build_tlv(0x86, ISSUER_APDU["UPDATE_RISK_PARAMS"]))
        if not reasons:
            reasons.append("ROUTINE")

    # ── Construction TLV ──────────────────────────────────────────────────────
    tlv_71 = _build_script_template(0x71, commands_71)
    tlv_72 = _build_script_template(0x72, commands_72)

    tag_71_hex  = tlv_71.hex().upper() if tlv_71 else None
    tag_72_hex  = tlv_72.hex().upper() if tlv_72 else None
    tag_71_b64  = base64.b64encode(tlv_71).decode() if tlv_71 else None
    tag_72_b64  = base64.b64encode(tlv_72).decode() if tlv_72 else None

    has_scripts = bool(tlv_71 or tlv_72)
    final_reason = ", ".join(reasons) if reasons else "NONE"

    if has_scripts:
        logger.info("Scripts émetteur générés : PAN=...%s raisons=%s tag71=%s tag72=%s",
                    card.pan[-4:], final_reason,
                    "yes" if tlv_71 else "no",
                    "yes" if tlv_72 else "no")

    def _cmd_list(cmds: list[bytes]) -> list[dict]:
        result = []
        for c in cmds:
            hex_val = c.hex().upper()
            tag     = hex_val[:4]
            result.append({
                "tag":  tag,
                "hex":  hex_val,
                "b64":  base64.b64encode(c).decode(),
                "len":  len(c),
            })
        return result

    return {
        "tag_71":      tag_71_hex,
        "tag_72":      tag_72_hex,
        "tag_71_b64":  tag_71_b64,
        "tag_72_b64":  tag_72_b64,
        "commands_71": _cmd_list(commands_71),
        "commands_72": _cmd_list(commands_72),
        "reason":      final_reason,
        "reason_label": SCRIPT_REASON_LABELS.get(
            final_reason.split(",")[0].strip(), final_reason),
        "has_scripts": has_scripts,
    }
