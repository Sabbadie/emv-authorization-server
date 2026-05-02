"""
Format de réponse TPA (Terminal Payment Application).
Découpe la réponse d'autorisation en champs structurés numérotés,
conformément au format TPA utilisé par les terminaux de paiement.
"""

from datetime import datetime
from config import Config


TPA_FIELD_DEFINITIONS = {
    "F00": {"name": "MTI",                          "description": "Message Type Indicator",              "format": "n4"},
    "F02": {"name": "PAN",                           "description": "Numéro de carte (masqué)",            "format": "LLVAR"},
    "F03": {"name": "CODE_TRAITEMENT",               "description": "Processing Code",                     "format": "n6"},
    "F04": {"name": "MONTANT",                       "description": "Montant de la transaction (centimes)","format": "n12"},
    "F04A": {"name": "MONTANT_FORMATE",              "description": "Montant formaté lisible",             "format": "an"},
    "F07": {"name": "HORODATAGE_TRANSMISSION",       "description": "Date/heure de transmission (MMDDHHmmss)", "format": "n10"},
    "F11": {"name": "STAN",                          "description": "Numéro de trace système",             "format": "n6"},
    "F12": {"name": "HEURE_LOCALE",                  "description": "Heure locale transaction (HHmmss)",  "format": "n6"},
    "F13": {"name": "DATE_LOCALE",                   "description": "Date locale transaction (MMDD)",      "format": "n4"},
    "F14": {"name": "DATE_EXPIRATION",               "description": "Date d'expiration carte (YYMM)",      "format": "n4"},
    "F22": {"name": "MODE_ENTREE_POS",               "description": "Mode de saisie POS",                  "format": "n3"},
    "F37": {"name": "RRN",                           "description": "Retrieval Reference Number",          "format": "an12"},
    "F38": {"name": "CODE_AUTORISATION",             "description": "Code d'autorisation émetteur",        "format": "an6"},
    "F39": {"name": "CODE_REPONSE",                  "description": "Code de réponse ISO 8583",            "format": "an2"},
    "F39L": {"name": "LIBELLE_REPONSE",              "description": "Libellé du code de réponse",          "format": "ans"},
    "F41": {"name": "ID_TERMINAL",                   "description": "Identifiant terminal",                "format": "ans8"},
    "F42": {"name": "ID_COMMERCANT",                 "description": "Identifiant commerçant",              "format": "ans15"},
    "F43": {"name": "NOM_COMMERCANT",                "description": "Nom et localisation commerçant",      "format": "ans40"},
    "F49": {"name": "CODE_DEVISE",                   "description": "Code devise ISO 4217",                "format": "n3"},
    "F49L": {"name": "LIBELLE_DEVISE",               "description": "Libellé de la devise",                "format": "ans"},
    "F55": {"name": "DONNEES_EMV",                   "description": "Données ICC (champ 55 ISO 8583)",     "format": "LLLVAR hex"},
    "FE1": {"name": "TRANCHE_MONTANT",               "description": "Tranche de montant TPA",              "format": "ans"},
    "FE2": {"name": "NIVEAU_RISQUE",                 "description": "Niveau de risque de la tranche",      "format": "ans"},
    "FE3": {"name": "CHEMIN_AUTORISATION",           "description": "Chemin d'autorisation (ONLINE/OFFLINE/DECLINE)", "format": "ans"},
    "FE4": {"name": "ARQC",                          "description": "Application Request Cryptogram",      "format": "b8 hex"},
    "FE5": {"name": "ARPC",                          "description": "Authorization Response Cryptogram",   "format": "b8 hex"},
    "FE6": {"name": "DONNEES_AUTH_EMETTEUR",         "description": "Issuer Authentication Data (Tag 91)","format": "b hex"},
    "FE7": {"name": "ATC",                           "description": "Application Transaction Counter",     "format": "n"},
    "FE8": {"name": "STATUT_TRANSACTION",            "description": "Statut final de la transaction",      "format": "ans"},
    "FE9": {"name": "ID_TRANSACTION",                "description": "Identifiant interne de la transaction","format": "uuid"},
    "FF0": {"name": "AVERTISSEMENTS",                "description": "Avertissements de traitement",        "format": "list"},
    "FF1": {"name": "HORODATAGE_TRAITEMENT",         "description": "Date/heure de traitement serveur",    "format": "iso8601"},
    "FF2": {"name": "VERSION_SERVEUR",               "description": "Version du serveur d'autorisation",   "format": "an"},
}


class TPAResponse:
    """
    Représente une réponse TPA découpée en champs structurés.
    """

    def __init__(self, transaction, auth_result, amount_decision=None):
        self.transaction = transaction
        self.auth_result = auth_result
        self.amount_decision = amount_decision
        self.fields = {}
        self._build()

    def _build(self):
        t = self.transaction
        ar = self.auth_result
        now = datetime.utcnow()

        self.fields["F00"] = "0110"

        pan = t.pan
        self.fields["F02"] = "*" * (len(pan) - 4) + pan[-4:] if len(pan) > 4 else pan

        txn_type = t.transaction_type or "00"
        self.fields["F03"] = txn_type.zfill(2) + "0000"

        self.fields["F04"] = str(t.amount).zfill(12)
        self.fields["F04A"] = "{:.2f}".format(t.amount / 100)

        self.fields["F07"] = now.strftime("%m%d%H%M%S")
        self.fields["F11"] = t.rrn[-6:] if t.rrn else "000000"
        self.fields["F12"] = now.strftime("%H%M%S")
        self.fields["F13"] = now.strftime("%m%d")

        self.fields["F22"] = t.pos_entry_mode or "051"
        self.fields["F37"] = t.rrn or ""

        if t.auth_code:
            self.fields["F38"] = t.auth_code.zfill(6)[:6]

        self.fields["F39"] = t.response_code or "96"
        self.fields["F39L"] = Config.RESPONSE_CODES.get(
            t.response_code or "96", "Inconnu")

        if t.terminal_id:
            self.fields["F41"] = t.terminal_id[:8].ljust(8)
        if t.merchant_id:
            self.fields["F42"] = t.merchant_id[:15].ljust(15)
        if t.merchant_name:
            self.fields["F43"] = t.merchant_name[:40]

        self.fields["F49"] = t.currency or "840"
        self.fields["F49L"] = Config.CURRENCY_CODES.get(t.currency or "840", "???")

        if t.arqc:
            self.fields["FE4"] = t.arqc
        if t.arpc:
            self.fields["FE5"] = t.arpc
        if t.issuer_auth_data:
            self.fields["FE6"] = t.issuer_auth_data
            self.fields["F55"] = t.issuer_auth_data

        if t.atc is not None:
            self.fields["FE7"] = str(t.atc)

        if self.amount_decision:
            self.fields["FE1"] = "{} — {}".format(
                self.amount_decision.tier.name,
                self.amount_decision.tier.label)
            self.fields["FE2"] = self.amount_decision.tier.risk_level
            self.fields["FE3"] = self.amount_decision.auth_path
            if self.amount_decision.warnings:
                self.fields["FF0"] = self.amount_decision.warnings

        self.fields["FE8"] = t.status
        self.fields["FE9"] = t.id
        self.fields["FF1"] = (t.processed_at or now.isoformat()) + "Z"
        self.fields["FF2"] = "EMV-AUTH-SERVER/1.1"

    def to_dict(self, include_definitions=False):
        result = {}
        for fid, value in self.fields.items():
            if include_definitions and fid in TPA_FIELD_DEFINITIONS:
                defn = TPA_FIELD_DEFINITIONS[fid]
                result[fid] = {
                    "name": defn["name"],
                    "description": defn["description"],
                    "format": defn["format"],
                    "value": value,
                }
            else:
                result[fid] = value
        return result

    def to_flat(self):
        """Retourne un dict plat champ → valeur, trié."""
        return {k: self.fields[k] for k in sorted(self.fields.keys())}

    def to_iso8583_like(self):
        """Retourne une représentation proche ISO 8583."""
        lines = []
        lines.append("┌─────────────────────────────────────────────────────────┐")
        lines.append("│  MESSAGE TYPE INDICATOR (MTI) : {}                      │".format(
            self.fields.get("F00", "0110")))
        lines.append("├──────┬──────────────────────────────┬───────────────────┤")
        lines.append("│ Chmp │ Nom                          │ Valeur            │")
        lines.append("├──────┼──────────────────────────────┼───────────────────┤")

        for fid in sorted(self.fields.keys()):
            val = self.fields[fid]
            if isinstance(val, list):
                val = "; ".join(str(v) for v in val)
            val_str = str(val)[:18]
            defn = TPA_FIELD_DEFINITIONS.get(fid, {})
            name = defn.get("name", fid)[:28]
            lines.append("│ {:<4} │ {:<28} │ {:<17} │".format(fid, name, val_str))

        lines.append("└──────┴──────────────────────────────┴───────────────────┘")
        return "\n".join(lines)
