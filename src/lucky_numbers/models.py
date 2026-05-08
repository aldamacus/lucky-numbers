"""Typed data models and constants."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Chaldean / Vedic planet → number mapping
PLANET_NUMBER: dict[str, int] = {
    "Sun": 1,
    "Moon": 2,
    "Jupiter": 3,
    "Rahu": 4,
    "Mercury": 5,
    "Venus": 6,
    "Ketu": 7,
    "Saturn": 8,
    "Mars": 9,
}

# Sign index (1-12) — used for sign-derived numerics
SIGN_INDEX: dict[str, int] = {
    "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
    "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
    "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12,
}


@dataclass
class Birth:
    date: date
    time: str               # "HH:MM"
    timezone: str           # "+HH:MM"
    location: str
    latitude: float
    longitude: float

    @property
    def day(self) -> int:    return self.date.day
    @property
    def month(self) -> int:  return self.date.month
    @property
    def year(self) -> int:   return self.date.year


@dataclass
class Person:
    name: str
    role: str
    birth: Birth
    numerology: dict[str, Any] = field(default_factory=dict)
    natal: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    """All facts the rule engine sees, in one place."""
    self_: Person
    son: Person
    transits: dict[str, dict[str, dict[str, Any]]]   # subject -> planet -> facts
    dasa: dict[str, dict[str, str]]                  # subject -> {mahadasa,bhukti,antara}

    def as_context(self) -> dict[str, Any]:
        """Flatten into the dict used by rule expressions."""
        return {
            "self": self._person_dict(self.self_),
            "son": self._person_dict(self.son),
            "transits": self.transits,
            "dasa": self.dasa,
        }

    @staticmethod
    def _person_dict(p: Person) -> dict[str, Any]:
        return {
            "name": p.name,
            "role": p.role,
            "birth": {
                "day": p.birth.day,
                "month": p.birth.month,
                "year": p.birth.year,
                "time": p.birth.time,
                "timezone": p.birth.timezone,
                "location": p.birth.location,
                "latitude": p.birth.latitude,
                "longitude": p.birth.longitude,
            },
            "numerology": p.numerology,
            "natal": p.natal,
        }


@dataclass
class AuditEntry:
    rule_id: str
    action: str
    numbers: list[int]
    weight: int
    reason: str


@dataclass
class GenerationResult:
    system: str
    main: list[int]
    magic: list[int]
    audit: list[AuditEntry]

