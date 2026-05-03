"""
Blackliste BIN/PAN — E7
Gère les BIN (préfixes) et PAN complets refusés globalement (fraude connue).
Code réponse ISO 8583 : 63 (violation de sécurité).
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BINBlacklist:
    def __init__(self):
        self._bins = {}   # prefix -> entry dict
        self._pans = {}   # pan    -> entry dict
        self._load_defaults()

    def _load_defaults(self):
        """
        Aucun BIN/PAN pré-blacklisté par défaut.
        Utiliser POST /api/v1/bin-blacklist/bins pour peupler la liste.
        """
        pass

    # ── BIN ──────────────────────────────────────────────────────────────────

    def add_bin(self, bin_prefix: str, reason: str = None,
                added_by: str = "API") -> dict:
        bin_prefix = str(bin_prefix).strip().upper()
        if not bin_prefix.isdigit():
            raise ValueError(f"Préfixe BIN invalide : {bin_prefix!r}")
        entry = {
            "prefix":   bin_prefix,
            "reason":   reason or "Blacklisté manuellement",
            "added_at": datetime.utcnow().isoformat(),
            "added_by": added_by,
        }
        self._bins[bin_prefix] = entry
        logger.info("BIN blacklisté : %s — %s", bin_prefix, entry["reason"])
        return entry

    def remove_bin(self, bin_prefix: str) -> bool:
        bin_prefix = str(bin_prefix).strip().upper()
        if bin_prefix in self._bins:
            del self._bins[bin_prefix]
            logger.info("BIN retiré de la blackliste : %s", bin_prefix)
            return True
        return False

    # ── PAN ──────────────────────────────────────────────────────────────────

    def add_pan(self, pan: str, reason: str = None,
                added_by: str = "API") -> dict:
        pan = pan.replace(" ", "")
        if not pan.isdigit() or len(pan) < 13:
            raise ValueError(f"PAN invalide : {pan!r}")
        masked = "*" * (len(pan) - 4) + pan[-4:]
        entry = {
            "pan_masked": masked,
            "reason":     reason or "Blacklisté manuellement",
            "added_at":   datetime.utcnow().isoformat(),
            "added_by":   added_by,
        }
        self._pans[pan] = entry
        logger.info("PAN blacklisté : %s — %s", masked, entry["reason"])
        return entry

    def remove_pan(self, pan: str) -> bool:
        pan = pan.replace(" ", "")
        if pan in self._pans:
            del self._pans[pan]
            return True
        return False

    # ── Vérification ─────────────────────────────────────────────────────────

    def is_blacklisted(self, pan: str) -> tuple:
        """
        Retourne (True, type, reason) si le PAN est blacklisté,
        sinon (False, None, None).
        """
        pan = pan.replace(" ", "")

        if pan in self._pans:
            return True, "PAN", self._pans[pan]["reason"]

        # Cherche le préfixe le plus long qui correspond
        for prefix in sorted(self._bins.keys(), key=len, reverse=True):
            if pan.startswith(prefix):
                return True, "BIN", self._bins[prefix]["reason"]

        return False, None, None

    # ── Lecture ──────────────────────────────────────────────────────────────

    def get_all(self) -> dict:
        return {
            "bins": list(self._bins.values()),
            "pans": list(self._pans.values()),
            "total_bins": len(self._bins),
            "total_pans": len(self._pans),
        }

    def get_bin(self, prefix: str) -> dict | None:
        return self._bins.get(prefix.strip().upper())

    def stats(self) -> dict:
        return {
            "total_bins": len(self._bins),
            "total_pans": len(self._pans),
            "total_entries": len(self._bins) + len(self._pans),
        }


bin_blacklist = BINBlacklist()
