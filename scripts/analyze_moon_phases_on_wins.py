"""Analyse moon phases on historical jackpot-win days.

Reads the jackpot-wins CSVs produced by analyze_pots_and_wins.py,
computes the moon phase at each draw time, tallies phase frequencies,
and writes a ranked JSON to data/historical/analysis/moon_phase_win_stats.json.

Usage::
    python scripts/analyze_moon_phases_on_wins.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

# Allow running as a script without `pip install -e .`
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lucky_numbers.moon_phase import (
    ALL_PHASES,
    moon_phase_at_date,
)

ANALYSIS = ROOT / "data" / "historical" / "analysis"
OUT_FILE = ANALYSIS / "moon_phase_win_stats.json"

# Draw-time and UTC offset per game
GAMES: list[dict] = [
    {
        "name": "austria_lotto_6aus45",
        "wins_csv": ANALYSIS / "austria_lotto_6aus45_jackpot_wins.csv",
        "draw_time": "20:00",       # CET local (UTC+1 standard / UTC+2 summer)
        "utc_offset": 1.0,          # approximate — good enough for phase bucket
    },
    {
        "name": "euromillions",
        "wins_csv": ANALYSIS / "euromillions_jackpot_wins.csv",
        "draw_time": "21:30",       # CET local
        "utc_offset": 1.0,
    },
]


def _load_win_dates(csv_path: Path) -> list[str]:
    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found — skipping.")
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [row["date"] for row in reader if row.get("date")]


def analyse_game(game: dict) -> dict:
    """Return per-phase counts, percentages and win dates for one game."""
    dates = _load_win_dates(game["wins_csv"])
    print(f"\n  {game['name']}: {len(dates)} jackpot-win dates")

    counts: dict[str, int] = defaultdict(int)
    detail: list[dict] = []

    for iso_date in dates:
        mp = moon_phase_at_date(iso_date, game["draw_time"], game["utc_offset"])
        counts[mp.phase] += 1
        detail.append({
            "date": iso_date,
            "phase": mp.phase,
            "illumination": mp.illumination,
            "age_days": mp.age_days,
        })

    total = len(dates) or 1
    expected_pct = 100.0 / len(ALL_PHASES)   # ~12.5 % for 8 phases

    phases_ranked = []
    for phase in ALL_PHASES:
        cnt = counts.get(phase, 0)
        pct = 100.0 * cnt / total
        phases_ranked.append({
            "phase": phase,
            "count": cnt,
            "pct": round(pct, 2),
            "expected_pct": round(expected_pct, 2),
            "above_expected": round(pct - expected_pct, 2),
        })
    phases_ranked.sort(key=lambda x: -x["pct"])

    # Print summary
    print(f"  {'Phase':<20}  {'Count':>5}  {'%':>6}  {'vs expected':>11}")
    print(f"  {'-'*20}  {'-'*5}  {'-'*6}  {'-'*11}")
    for p in phases_ranked:
        arrow = "▲" if p["above_expected"] > 0 else "▼"
        print(
            f"  {p['phase']:<20}  {p['count']:>5}  {p['pct']:>5.1f}%  "
            f"  {arrow}{abs(p['above_expected']):>5.1f}%"
        )

    return {
        "game": game["name"],
        "total_wins": len(dates),
        "draw_time": game["draw_time"],
        "phases": phases_ranked,
        "detail": detail,
    }


def main() -> None:
    print("=== Moon phase analysis on jackpot-win days ===")
    results = [analyse_game(g) for g in GAMES]

    ANALYSIS.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Stats written to {OUT_FILE}")


if __name__ == "__main__":
    main()
