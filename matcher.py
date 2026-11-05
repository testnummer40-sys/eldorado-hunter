"""Verbindet Eldorado-Angebote mit Elvebredd-Werten (Fuzzy-Match)."""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import process, fuzz

from models import EldoradoOffer, ElvebreddValue


# Tags, die der Variante / den Modifiern entsprechen
VARIANT_WORDS = {
    "mega neon": "Mega Neon",
    "mega": "Mega Neon",
    "mn": "Mega Neon",
    "neon": "Neon",
    "normal": "Normal",
}
TAG_WORDS = {
    "fly": "Fly",
    "ride": "Ride",
    "fr": ("Fly", "Ride"),
    "fly ride": ("Fly", "Ride"),
    "flyride": ("Fly", "Ride"),
    "nfr": ("Neon", "Fly", "Ride"),
    "mfr": ("Mega Neon", "Fly", "Ride"),
}


def parse_title(title: str) -> tuple[str, str, list[str]]:
    """
    Zerlegt einen Eldorado-Titel wie
      'Adopt Me - Neon Fly Ride Shadow Dragon'
    in (pet_name, variant, tags).
    """
    t = title.lower()
    t = re.sub(r"adopt\s*me[\s\-:]*", "", t)
    t = re.sub(r"\(.*?\)", "", t)                 # Klammerinhalte raus
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    variant = "Normal"
    tags: list[str] = []

    # Mega Neon zuerst, damit "neon" allein nicht gewinnt
    for word in ("mega neon", "mn", "neon", "normal"):
        if re.search(rf"\b{re.escape(word)}\b", t):
            variant = VARIANT_WORDS[word]
            t = re.sub(rf"\b{re.escape(word)}\b", " ", t)
            break

    for word, mapped in TAG_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            if isinstance(mapped, tuple):
                for m in mapped:
                    if m in ("Neon", "Mega Neon"):
                        variant = m
                    elif m not in tags:
                        tags.append(m)
            else:
                if mapped not in tags:
                    tags.append(mapped)
            t = re.sub(rf"\b{re.escape(word)}\b", " ", t)

    pet_name = re.sub(r"\s+", " ", t).strip().title()
    return pet_name, variant, tags


def match_offer_to_value(
    offer: EldoradoOffer,
    values: dict[str, ElvebreddValue],
    min_score: int = 80,
) -> tuple[Optional[ElvebreddValue], int]:
    """Fuzzy-Match des Pet-Namens gegen alle Elvebredd-Einträge."""
    if not values:
        return None, 0
    keys = list(values.keys())
    best = process.extractOne(offer.pet_name, keys, scorer=fuzz.WRatio)
    if not best:
        return None, 0
    name, score, _ = best
    if score < min_score:
        return None, int(score)
    return values[name], int(score)
