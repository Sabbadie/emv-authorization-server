"""
Gestion des réponses par montant (tranches TPA).
Définit des règles d'autorisation selon le montant de la transaction.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class AmountTier:
    name: str
    label: str
    min_amount: int
    max_amount: int
    require_online: bool
    require_arqc: bool
    require_pin: bool
    auto_approve_offline: bool
    risk_level: str
    floor_limit: int
    velocity_check: bool
    max_daily_count: Optional[int]
    description: str

    def matches(self, amount: int) -> bool:
        return self.min_amount <= amount <= self.max_amount


AMOUNT_TIERS: List[AmountTier] = [
    AmountTier(
        name="MICRO",
        label="Micropaiement",
        min_amount=0,
        max_amount=500,
        require_online=False,
        require_arqc=False,
        require_pin=False,
        auto_approve_offline=True,
        risk_level="LOW",
        floor_limit=500,
        velocity_check=False,
        max_daily_count=10,
        description="Transactions ≤ 5,00 — autorisation hors ligne sans ARQC",
    ),
    AmountTier(
        name="SMALL",
        label="Petit montant",
        min_amount=501,
        max_amount=5000,
        require_online=False,
        require_arqc=False,
        require_pin=True,
        auto_approve_offline=True,
        risk_level="LOW",
        floor_limit=5000,
        velocity_check=True,
        max_daily_count=20,
        description="Transactions 5,01–50,00 — hors ligne avec PIN",
    ),
    AmountTier(
        name="STANDARD",
        label="Montant standard",
        min_amount=5001,
        max_amount=50000,
        require_online=True,
        require_arqc=True,
        require_pin=True,
        auto_approve_offline=False,
        risk_level="MEDIUM",
        floor_limit=0,
        velocity_check=True,
        max_daily_count=None,
        description="Transactions 50,01–500,00 — autorisation en ligne requise + ARQC",
    ),
    AmountTier(
        name="HIGH",
        label="Montant élevé",
        min_amount=50001,
        max_amount=200000,
        require_online=True,
        require_arqc=True,
        require_pin=True,
        auto_approve_offline=False,
        risk_level="HIGH",
        floor_limit=0,
        velocity_check=True,
        max_daily_count=5,
        description="Transactions 500,01–2 000,00 — contrôle renforcé + limite 5/jour",
    ),
    AmountTier(
        name="VERY_HIGH",
        label="Montant très élevé",
        min_amount=200001,
        max_amount=500000,
        require_online=True,
        require_arqc=True,
        require_pin=True,
        auto_approve_offline=False,
        risk_level="VERY_HIGH",
        floor_limit=0,
        velocity_check=True,
        max_daily_count=2,
        description="Transactions 2 000,01–5 000,00 — approbation manuelle recommandée",
    ),
    AmountTier(
        name="CRITICAL",
        label="Montant critique",
        min_amount=500001,
        max_amount=999999999,
        require_online=True,
        require_arqc=True,
        require_pin=True,
        auto_approve_offline=False,
        risk_level="CRITICAL",
        floor_limit=0,
        velocity_check=True,
        max_daily_count=1,
        description="Transactions > 5 000,00 — référer à l'émetteur",
    ),
]

_custom_tiers: List[AmountTier] = []


def get_tier(amount: int) -> AmountTier:
    for tier in _custom_tiers:
        if tier.matches(amount):
            return tier
    for tier in AMOUNT_TIERS:
        if tier.matches(amount):
            return tier
    return AMOUNT_TIERS[-1]


def get_all_tiers() -> List[AmountTier]:
    tiers = list(_custom_tiers) + list(AMOUNT_TIERS)
    return sorted(tiers, key=lambda t: t.min_amount)


def add_custom_tier(tier_data: dict) -> AmountTier:
    tier = AmountTier(
        name=tier_data["name"].upper(),
        label=tier_data.get("label", tier_data["name"]),
        min_amount=int(tier_data["min_amount"]),
        max_amount=int(tier_data["max_amount"]),
        require_online=bool(tier_data.get("require_online", True)),
        require_arqc=bool(tier_data.get("require_arqc", True)),
        require_pin=bool(tier_data.get("require_pin", True)),
        auto_approve_offline=bool(tier_data.get("auto_approve_offline", False)),
        risk_level=tier_data.get("risk_level", "MEDIUM"),
        floor_limit=int(tier_data.get("floor_limit", 0)),
        velocity_check=bool(tier_data.get("velocity_check", True)),
        max_daily_count=tier_data.get("max_daily_count"),
        description=tier_data.get("description", ""),
    )
    _custom_tiers.append(tier)
    return tier


def delete_custom_tier(name: str) -> bool:
    global _custom_tiers
    before = len(_custom_tiers)
    _custom_tiers = [t for t in _custom_tiers if t.name != name.upper()]
    return len(_custom_tiers) < before


@dataclass
class AmountDecision:
    tier: AmountTier
    allowed: bool
    response_code: str
    response_message: str
    auth_path: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "tier_name": self.tier.name,
            "tier_label": self.tier.label,
            "risk_level": self.tier.risk_level,
            "allowed": self.allowed,
            "response_code": self.response_code,
            "response_message": self.response_message,
            "auth_path": self.auth_path,
            "require_online": self.tier.require_online,
            "require_arqc": self.tier.require_arqc,
            "require_pin": self.tier.require_pin,
            "warnings": self.warnings,
        }


def evaluate_amount(amount: int, transaction_type: str,
                    daily_count: int = 0, has_arqc: bool = False) -> AmountDecision:
    tier = get_tier(amount)
    warnings = []

    if tier.name == "CRITICAL":
        return AmountDecision(
            tier=tier,
            allowed=False,
            response_code="01",
            response_message="Référer à l'émetteur — montant critique",
            auth_path="REFERRAL",
            warnings=["Montant dépasse le seuil critique"],
        )

    if tier.max_daily_count is not None and daily_count >= tier.max_daily_count:
        return AmountDecision(
            tier=tier,
            allowed=False,
            response_code="65",
            response_message="Limite de fréquence journalière atteinte pour ce montant",
            auth_path="DECLINE",
            warnings=["Quota journalier atteint pour la tranche {}".format(tier.name)],
        )

    if tier.require_arqc and not has_arqc and not tier.auto_approve_offline:
        warnings.append("ARQC requis pour cette tranche mais absent")

    if tier.risk_level in ("VERY_HIGH", "HIGH"):
        warnings.append("Tranche à risque élevé — contrôle renforcé appliqué")

    if tier.auto_approve_offline and amount <= tier.floor_limit:
        auth_path = "OFFLINE"
    elif tier.require_online:
        auth_path = "ONLINE"
    else:
        auth_path = "OFFLINE"

    return AmountDecision(
        tier=tier,
        allowed=True,
        response_code="00",
        response_message="Autorisation accordée",
        auth_path=auth_path,
        warnings=warnings,
    )
