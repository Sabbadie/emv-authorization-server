"""
Format de réponse TPA — inclut champs GIE CB (CB1–CBA).
Découpe la réponse d'autorisation en champs structurés numérotés.
"""

from datetime import datetime
from config import Config


TPA_FIELD_DEFINITIONS = {
    # ── Champs ISO 8583 standard ──────────────────────────────────────────────
    "F00":  {"name": "MTI",                    "description": "Message Type Indicator",                  "format": "n4"},
    "F02":  {"name": "PAN",                    "description": "Numéro de carte (masqué)",                "format": "LLVAR"},
    "F03":  {"name": "CODE_TRAITEMENT",        "description": "Processing Code",                         "format": "n6"},
    "F04":  {"name": "MONTANT",                "description": "Montant de la transaction (centimes)",    "format": "n12"},
    "F04A": {"name": "MONTANT_FORMATE",        "description": "Montant formaté lisible",                 "format": "an"},
    "F07":  {"name": "HORODATAGE_TRANSMISSION","description": "Date/heure de transmission (MMDDHHmmss)", "format": "n10"},
    "F11":  {"name": "STAN",                   "description": "Numéro de trace système",                 "format": "n6"},
    "F12":  {"name": "HEURE_LOCALE",           "description": "Heure locale transaction (HHmmss)",       "format": "n6"},
    "F13":  {"name": "DATE_LOCALE",            "description": "Date locale transaction (MMDD)",           "format": "n4"},
    "F14":  {"name": "DATE_EXPIRATION",        "description": "Date d'expiration carte (YYMM)",           "format": "n4"},
    "F22":  {"name": "MODE_ENTREE_POS",        "description": "Mode de saisie POS",                      "format": "n3"},
    "F37":  {"name": "RRN",                    "description": "Retrieval Reference Number",               "format": "an12"},
    "F38":  {"name": "CODE_AUTORISATION",      "description": "Code d'autorisation émetteur",             "format": "an6"},
    "F39":  {"name": "CODE_REPONSE",           "description": "Code de réponse ISO 8583",                 "format": "an2"},
    "F39L": {"name": "LIBELLE_REPONSE",        "description": "Libellé du code de réponse",               "format": "ans"},
    "F41":  {"name": "ID_TERMINAL",            "description": "Identifiant terminal",                     "format": "ans8"},
    "F42":  {"name": "ID_COMMERCANT",          "description": "Identifiant commerçant",                   "format": "ans15"},
    "F43":  {"name": "NOM_COMMERCANT",         "description": "Nom et localisation commerçant",           "format": "ans40"},
    "F49":  {"name": "CODE_DEVISE",            "description": "Code devise ISO 4217",                     "format": "n3"},
    "F49L": {"name": "LIBELLE_DEVISE",         "description": "Libellé de la devise",                     "format": "ans"},
    "F55":  {"name": "DONNEES_EMV",            "description": "Données ICC / Issuer Auth Data (Tag 91)",  "format": "LLLVAR hex"},
    # ── Champs propriétaires tranches/EMV ─────────────────────────────────────
    "FE1":  {"name": "TRANCHE_MONTANT",        "description": "Tranche de montant TPA",                   "format": "ans"},
    "FE2":  {"name": "NIVEAU_RISQUE",          "description": "Niveau de risque de la tranche",           "format": "ans"},
    "FE3":  {"name": "CHEMIN_AUTORISATION",    "description": "Chemin d'autorisation (ONLINE/OFFLINE)",   "format": "ans"},
    "FE4":  {"name": "ARQC",                   "description": "Application Request Cryptogram",           "format": "b8 hex"},
    "FE5":  {"name": "ARPC",                   "description": "Authorization Response Cryptogram",        "format": "b8 hex"},
    "FE6":  {"name": "DONNEES_AUTH_EMETTEUR",  "description": "Issuer Authentication Data (Tag 91)",      "format": "b hex"},
    "FE7":  {"name": "ATC",                    "description": "Application Transaction Counter",          "format": "n"},
    "FE8":  {"name": "STATUT_TRANSACTION",     "description": "Statut final de la transaction",           "format": "ans"},
    "FE9":  {"name": "ID_TRANSACTION",         "description": "Identifiant interne de la transaction",    "format": "uuid"},
    # ── Champs GIE CB ─────────────────────────────────────────────────────────
    "CB1":  {"name": "CB_TYPE_CARTE",          "description": "Type de carte GIE CB (CB/VISA CB/MC CB…)", "format": "ans"},
    "CB2":  {"name": "CB_SCHEMA",              "description": "Schéma de paiement CB (VISA/MC/CB/MAESTRO)","format": "ans"},
    "CB3":  {"name": "CB_AID",                 "description": "Application Identifier détecté",           "format": "b hex"},
    "CB4":  {"name": "CB_INDICATEUR_SERVICE",  "description": "Indicateur de service GIE CB",             "format": "n2"},
    "CB4L": {"name": "CB_INDICATEUR_LIBELLE",  "description": "Libellé indicateur de service CB",         "format": "ans"},
    "CB5":  {"name": "CB_MODE_SANS_CONTACT",   "description": "Transaction sans contact NFC CB",          "format": "bool"},
    "CB6":  {"name": "CB_CUMUL_SC",            "description": "Cumul hors ligne sans contact (centimes)", "format": "n"},
    "CB6L": {"name": "CB_CUMUL_SC_FORMATE",    "description": "Cumul sans contact formaté",               "format": "an"},
    "CB7":  {"name": "CB_REGLE_APPLIQUEE",     "description": "Règle CB appliquée (MCC / CAP / TAP)",     "format": "ans"},
    "CB8":  {"name": "CB_EXEMPTION_SCA",       "description": "Exemption SCA DSP2 appliquée",             "format": "ans"},
    "CB9":  {"name": "CB_FLOOR_LIMIT",         "description": "Floor limit CB pour ce MCC (centimes)",    "format": "n"},
    "CB9L": {"name": "CB_FLOOR_LIMIT_FORMATE", "description": "Floor limit CB formaté",                   "format": "an"},
    "CBA":  {"name": "CB_CODE_RETOUR",         "description": "Code retour GIE CB",                       "format": "an2"},
    "CBAL": {"name": "CB_CODE_RETOUR_LIBELLE", "description": "Libellé code retour CB",                   "format": "ans"},
    "CBB":  {"name": "CB_MOTIF_REFUS",         "description": "Code motif de refus CB (Rxx)",             "format": "ans"},
    "CBC":  {"name": "CB_CAP_CHECK",           "description": "Contrôle CAP (Card Acceptor Parameters)",  "format": "ans"},
    "CBD":  {"name": "CB_CONSECUTIFS_OFFLINE", "description": "Transactions hors ligne consécutives",     "format": "n"},
    # ── Métadonnées ───────────────────────────────────────────────────────────
    "FF0":  {"name": "AVERTISSEMENTS",         "description": "Avertissements de traitement",             "format": "list"},
    "FF1":  {"name": "HORODATAGE_TRAITEMENT",  "description": "Date/heure de traitement serveur",         "format": "iso8601"},
    "FF2":  {"name": "VERSION_SERVEUR",        "description": "Version du serveur d'autorisation",        "format": "an"},
}

CB_SERVICE_INDICATOR_LABELS = {
    "01": "Paiement national CB",
    "02": "Paiement international VISA",
    "03": "Paiement international MC",
    "04": "Retrait DAB national CB",
    "05": "Retrait DAB international",
    "06": "Paiement sans contact NFC",
    "07": "Paiement en ligne e-commerce",
    "08": "Paiement récurrent",
    "09": "Paiement différé",
    "10": "Préautorisation",
    "11": "Annulation",
    "12": "Remboursement",
}

CB_RESPONSE_CODE_LABELS = {
    "00": "Autorisation accordée",
    "01": "Contacter l'émetteur",
    "05": "Ne pas honorer",
    "1A": "Authentification forte requise (SCA DSP2)",
    "51": "Provision insuffisante",
    "54": "Carte expirée",
    "62": "Carte avec restriction",
    "65": "Fréquence dépassée",
    "A5": "Cumul sans contact dépassé — insérer la carte",
    "P1": "Plafond sans contact dépassé",
    "P2": "Cumul hors ligne dépassé",
}

CB_DECLINE_REASON_LABELS = {
    "R01": "Solde insuffisant",
    "R02": "Carte bloquée par l'émetteur",
    "R03": "Carte perdue",
    "R04": "Carte volée",
    "R05": "Limite journalière dépassée",
    "R07": "Plafond sans contact cumulé dépassé",
    "R08": "Nombre de transactions hors ligne dépassé",
    "R09": "SCA requise — authentification forte obligatoire",
}

SCA_EXEMPTION_LABELS = {
    "LVP":  "Low Value Payment (≤30€)",
    "MIT":  "Merchant Initiated Transaction",
    "TRA":  "Transaction Risk Analysis (<250€)",
    "TTP":  "Trusted Third Party",
    "NONE": "Aucune — SCA complète requise",
}


class TPAResponse:
    """Réponse TPA découpée en champs structurés, incluant champs GIE CB."""

    def __init__(self, transaction, auth_result, amount_decision=None, cb_result=None):
        self.transaction = transaction
        self.auth_result = auth_result
        self.amount_decision = amount_decision
        self.cb_result = cb_result
        self.fields = {}
        self._build()

    def _build(self):
        t = self.transaction
        now = datetime.utcnow()

        # ── ISO 8583 standard ─────────────────────────────────────────────────
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
        self.fields["F39L"] = Config.RESPONSE_CODES.get(t.response_code or "96", "Inconnu")
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

        # ── Tranches ──────────────────────────────────────────────────────────
        if self.amount_decision:
            self.fields["FE1"] = "{} — {}".format(
                self.amount_decision.tier.name, self.amount_decision.tier.label)
            self.fields["FE2"] = self.amount_decision.tier.risk_level
            self.fields["FE3"] = self.amount_decision.auth_path
            warnings = list(self.amount_decision.warnings)
        else:
            warnings = []

        self.fields["FE8"] = t.status
        self.fields["FE9"] = t.id

        # ── Champs GIE CB ─────────────────────────────────────────────────────
        cb_brand = getattr(t, "cb_brand", None)
        cb_scheme = getattr(t, "cb_scheme", None)
        cb_si = getattr(t, "cb_service_indicator", "01")
        cb_sca = getattr(t, "cb_sca_exemption", "NONE")
        cb_floor = getattr(t, "cb_floor_limit", 0)
        cb_is_cl = getattr(t, "cb_is_contactless", False)
        cb_rc = getattr(t, "cb_response_code", "00")
        cb_dr = getattr(t, "cb_decline_reason", None)
        cb_aid = getattr(t, "aid", None)
        cb_cumul = 0
        cb_consecutive = 0

        from models.card import card_db as _cdb
        _card = _cdb.get_card(t.pan)
        if _card:
            cb_cumul = _card.contactless_cumul
            cb_consecutive = _card.consecutive_offline
            if not cb_aid:
                cb_aid = _card.aid

        if cb_brand:
            self.fields["CB1"] = cb_brand
        if cb_scheme:
            self.fields["CB2"] = cb_scheme
        if cb_aid:
            self.fields["CB3"] = cb_aid
        self.fields["CB4"] = cb_si or "01"
        self.fields["CB4L"] = CB_SERVICE_INDICATOR_LABELS.get(cb_si or "01", "—")
        self.fields["CB5"] = "OUI" if cb_is_cl else "NON"
        self.fields["CB6"] = str(cb_cumul)
        self.fields["CB6L"] = "{:.2f}€".format(cb_cumul / 100)
        self.fields["CB9"] = str(cb_floor)
        self.fields["CB9L"] = "{:.2f}€".format(cb_floor / 100)
        self.fields["CBA"] = cb_rc or "00"
        self.fields["CBAL"] = CB_RESPONSE_CODE_LABELS.get(cb_rc or "00",
                               CB_DECLINE_REASON_LABELS.get(cb_rc or "00", "—"))
        if cb_dr:
            self.fields["CBB"] = cb_dr + " — " + CB_DECLINE_REASON_LABELS.get(cb_dr, "")
        self.fields["CBD"] = str(cb_consecutive)

        if self.cb_result:
            self.fields["CB7"] = self.cb_result.mcc_rule
            self.fields["CB8"] = (cb_sca or "NONE") + " — " + SCA_EXEMPTION_LABELS.get(
                cb_sca or "NONE", "")
            self.fields["CBC"] = self.cb_result.cap_check
            if self.cb_result.warnings:
                warnings.extend(self.cb_result.warnings)
        else:
            self.fields["CB8"] = (cb_sca or "NONE") + " — " + SCA_EXEMPTION_LABELS.get(
                cb_sca or "NONE", "")

        # ── Métadonnées ───────────────────────────────────────────────────────
        if warnings:
            self.fields["FF0"] = warnings
        self.fields["FF1"] = (t.processed_at or now.isoformat()) + "Z"
        self.fields["FF2"] = "EMV-AUTH-SERVER/1.2-GIE-CB"

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
        return {k: self.fields[k] for k in sorted(self.fields.keys())}

    def to_iso8583_like(self):
        lines = [
            "┌─────────────────────────────────────────────────────────────┐",
            "│  MESSAGE TYPE INDICATOR (MTI) : {}   GIE CB v1.2            │".format(
                self.fields.get("F00", "0110")),
            "├──────┬────────────────────────────────┬─────────────────────┤",
            "│ Chmp │ Nom                            │ Valeur              │",
            "├──────┼────────────────────────────────┼─────────────────────┤",
        ]
        for fid in sorted(self.fields.keys()):
            val = self.fields[fid]
            if isinstance(val, list):
                val = "; ".join(str(v) for v in val)
            val_str = str(val)[:20]
            defn = TPA_FIELD_DEFINITIONS.get(fid, {})
            name = defn.get("name", fid)[:30]
            lines.append("│ {:<4} │ {:<30} │ {:<19} │".format(fid, name, val_str))
        lines.append("└──────┴────────────────────────────────┴─────────────────────┘")
        return "\n".join(lines)
