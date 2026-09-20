"""Pure-Python moon phase calculator.

Uses the known J2000 new-moon epoch and the mean synodic period to compute
the current (or any given) moon phase without external dependencies.

Reference epoch:
    New Moon on 2000-01-06 18:14 UTC  (JD 2451550.1)
Synodic period:
    29.530588 days
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import NamedTuple


# ── constants ────────────────────────────────────────────────────────────────

_KNOWN_NEW_MOON_JD = 2451550.1          # JD of new moon 2000-01-06 18:14 UTC
_SYNODIC_PERIOD    = 29.530588          # mean lunar month in days

# Eight standard phases with their start angle in degrees (0 = new moon)
_PHASES: list[tuple[str, float]] = [
    ("New Moon",        0.0),
    ("Waxing Crescent", 45.0),
    ("First Quarter",   90.0),
    ("Waxing Gibbous",  135.0),
    ("Full Moon",       180.0),
    ("Waning Gibbous",  225.0),
    ("Last Quarter",    270.0),
    ("Waning Crescent", 315.0),
]

# Emoji for each phase (used by the UI)
PHASE_EMOJI: dict[str, str] = {
    "New Moon":        "🌑",
    "Waxing Crescent": "🌒",
    "First Quarter":   "🌓",
    "Waxing Gibbous":  "🌔",
    "Full Moon":       "🌕",
    "Waning Gibbous":  "🌖",
    "Last Quarter":    "🌗",
    "Waning Crescent": "🌘",
}

# All eight names in cycle order (used by analysis scripts)
ALL_PHASES: list[str] = [p[0] for p in _PHASES]


# ── public API ────────────────────────────────────────────────────────────────

class MoonPhase(NamedTuple):
    phase: str          # e.g. "Full Moon"
    illumination: float # 0.0 → 1.0
    age_days: float     # days since last new moon


def _datetime_to_jd(dt: datetime) -> float:
    """Convert a timezone-aware datetime to Julian Day Number."""
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # JD of Unix epoch (1970-01-01 12:00 UTC) = 2440587.5
    unix_seconds = dt.timestamp()
    return 2440587.5 + unix_seconds / 86400.0


def compute_moon_phase(dt: datetime | None = None) -> MoonPhase:
    """Return the moon phase for *dt* (defaults to now, UTC).

    Parameters
    ----------
    dt:
        The moment to evaluate.  Pass a timezone-aware datetime or None for
        the current UTC time.

    Returns
    -------
    MoonPhase
        Named tuple with ``phase`` (str), ``illumination`` (float 0-1),
        and ``age_days`` (float).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    jd = _datetime_to_jd(dt)
    days_since = jd - _KNOWN_NEW_MOON_JD
    age_days = days_since % _SYNODIC_PERIOD          # 0 … 29.53
    angle = (age_days / _SYNODIC_PERIOD) * 360.0    # 0° … 360°

    # Illumination: (1 - cos(angle)) / 2
    illumination = (1.0 - math.cos(math.radians(angle))) / 2.0

    # Find phase bucket
    phase_name = _PHASES[-1][0]  # default: waning crescent wraps around
    for name, start in reversed(_PHASES):
        if angle >= start:
            phase_name = name
            break

    return MoonPhase(
        phase=phase_name,
        illumination=round(illumination, 4),
        age_days=round(age_days, 2),
    )


def moon_phase_at_date(iso_date: str, time_str: str = "20:00",
                       utc_offset_hours: float = 1.0) -> MoonPhase:
    """Convenience wrapper for historical draw dates.

    Parameters
    ----------
    iso_date:
        Date in YYYY-MM-DD format.
    time_str:
        Local draw time in HH:MM format (default "20:00").
    utc_offset_hours:
        UTC offset in hours for the local time (default 1 for CET).
    """
    from datetime import timedelta

    d, t = iso_date.split("T")[0], time_str
    h, m = int(t.split(":")[0]), int(t.split(":")[1])
    naive = datetime(
        int(d[:4]), int(d[5:7]), int(d[8:10]), h, m, tzinfo=timezone.utc
    )
    # Shift to UTC
    utc_dt = naive - timedelta(hours=utc_offset_hours)
    return compute_moon_phase(utc_dt)


if __name__ == "__main__":
    mp = compute_moon_phase()
    emoji = PHASE_EMOJI.get(mp.phase, "")
    print(f"{emoji} {mp.phase}  |  illumination {mp.illumination:.1%}  |  age {mp.age_days:.1f} days")
