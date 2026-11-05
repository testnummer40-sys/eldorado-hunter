"""Datenklassen für Eldorado-Angebote und Elvebredd-Werte."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional


@dataclass
class EldoradoOffer:
    """Ein einzelnes Angebot von Eldorado."""
    pet_name: str            # z. B. "Shadow Dragon"
    variant: str             # "Normal" | "Neon" | "Mega Neon"
    tags: list[str]          # ["Fly", "Ride", ...]
    price_eur: float         # Preis in EUR
    seller: str              # Verkäufer-Name
    url: str                 # Direktlink zum Angebot
    raw_title: str           # Rohtitel, für Debugging

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ElvebreddValue:
    """Ein Pet-Wert laut Elvebredd."""
    pet_name: str
    normal: Optional[float] = None
    neon: Optional[float] = None
    mega_neon: Optional[float] = None
    # Modifier-Faktoren (Daumenregeln von Elvebredd):
    # Fly ~ x2, Ride ~ x2, FlyRide ~ x4
    def value_for(self, variant: str, tags: list[str]) -> Optional[float]:
        base = {
            "Normal": self.normal,
            "Neon": self.neon,
            "Mega Neon": self.mega_neon,
        }.get(variant, self.normal)
        if base is None:
            return None
        mult = 1.0
        t = {x.lower() for x in tags}
        if "fly" in t:
            mult *= 2.0
        if "ride" in t:
            mult *= 2.0
        return base * mult


@dataclass
class Deal:
    """Fertige Deal-Zeile für das Dashboard."""
    offer: EldoradoOffer
    value: float                 # berechneter Elvebredd-Wert (inkl. Modifier)
    value_per_eur: float         # value / price_eur
    match_score: int             # 0..100 (fuzzy match-Qualität)
    is_alert: bool = False       # besonders günstig?
    first_seen: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        d = {
            "pet_name": self.offer.pet_name,
            "variant": self.offer.variant,
            "tags": self.offer.tags,
            "price_eur": self.offer.price_eur,
            "seller": self.offer.seller,
            "url": self.offer.url,
            "raw_title": self.offer.raw_title,
            "value": round(self.value, 4),
            "value_per_eur": round(self.value_per_eur, 4),
            "match_score": self.match_score,
            "is_alert": self.is_alert,
            "first_seen": self.first_seen,
        }
        return d
