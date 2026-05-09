"""Local Chaldean numerology — no API call required.

Used by the UI to populate `self.numerology` and `son.numerology` blocks so
the rules in `base_seeds.yaml` (root_number, name_number) actually fire when
people are entered through the Streamlit form (which does not fetch natal
data from VedAstro by default).

Chaldean letter values (no 9 — considered sacred / not assigned):
    1 = A I J Q Y
    2 = B K R
    3 = C G L S
    4 = D M T
    5 = E H N X
    6 = U V W
    7 = O Z
    8 = F P
"""
from __future__ import annotations

# Chaldean letter → digit
_CHALDEAN_LETTER: dict[str, int] = {}
for digit, letters in {
    1: "AIJQY",
    2: "BKR",
    3: "CGLS",
    4: "DMT",
    5: "EHNX",
    6: "UVW",
    7: "OZ",
    8: "FP",
}.items():
    for ch in letters:
        _CHALDEAN_LETTER[ch] = digit

# Chaldean root → ruling planet (mirrors models.PLANET_NUMBER inverse)
_CHALDEAN_PLANET: dict[int, str] = {
    1: "Sun",
    2: "Moon",
    3: "Jupiter",
    4: "Rahu",
    5: "Mercury",
    6: "Venus",
    7: "Ketu",
    8: "Saturn",
    9: "Mars",
}


def name_number(name: str) -> int:
    """Sum of Chaldean letter values for the full name (compound number).

    Non-letter characters are ignored. Returns 0 for an empty name.
    """
    return sum(_CHALDEAN_LETTER.get(ch.upper(), 0) for ch in name if ch.isalpha())


def root_number(value: int) -> int:
    """Reduce to a single digit (1..9). Zero wraps to 9 (no zero in Chaldean)."""
    n = abs(int(value))
    while n >= 10:
        n = sum(int(d) for d in str(n))
    return n or 9


def ruling_planet(root: int) -> str:
    """Map a Chaldean root digit (1..9) to the ruling planet."""
    return _CHALDEAN_PLANET.get(root, "Unknown")


def chaldean_profile(name: str) -> dict[str, object]:
    """Return the full {name, name_number, root_number, ruling_planet} block.

    Shape mirrors what `data/snapshot.yaml` already stores under
    `self.numerology` / `son.numerology`.
    """
    nn = name_number(name)
    rn = root_number(nn) if nn else 0
    return {
        "name": name,
        "name_number": nn,
        "root_number": rn,
        "ruling_planet": ruling_planet(rn) if rn else "Unknown",
    }
