from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from lucky_numbers.vedastro_client import VedAstroClient


ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "historical"
ANALYSIS = HIST / "analysis"
OUT_DIR = HIST / "planet_adjustments" / "win_days"


@dataclass(frozen=True)
class Game:
    name: str
    wins_csv: Path
    out_jsonl: Path
    check_time: str


GAMES: list[Game] = [
    Game(
        name="austria_lotto_6aus45",
        wins_csv=ANALYSIS / "austria_lotto_6aus45_jackpot_wins.csv",
        out_jsonl=OUT_DIR / "austria_lotto_6aus45_jackpot_wins.jsonl",
        check_time="21:00",
    ),
    Game(
        name="euromillions",
        wins_csv=ANALYSIS / "euromillions_jackpot_wins.csv",
        out_jsonl=OUT_DIR / "euromillions_jackpot_wins.jsonl",
        check_time="21:00",
    ),
]


def _ddmmyyyy(iso_yyyy_mm_dd: str) -> str:
    d = datetime.strptime(iso_yyyy_mm_dd, "%Y-%m-%d").date()
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _unwrap(rpc_result: dict) -> dict:
    content = rpc_result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                return json.loads(first["text"])
            except Exception:
                return {"raw": first["text"]}
    return rpc_result if isinstance(rpc_result, dict) else {}


def _load_existing_dates(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
            d = obj.get("date")
            if d:
                out.add(d)
        except Exception:
            continue
    return out


def _filter_last_years(rows: list[dict[str, str]], years: int) -> list[dict[str, str]]:
    today = datetime.now(UTC).date()
    cutoff = date(today.year - years, today.month, today.day)
    out: list[dict[str, str]] = []
    for r in rows:
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        if d >= cutoff:
            out.append(r)
    return out


def enrich_game(
    game: Game,
    *,
    last_years: int = 3,
    check_location_name: str = "Vienna, Austria",
    check_latitude: float = 48.2082,
    check_longitude: float = 16.3738,
    check_timezone: str = "+01:00",
) -> Path:
    if not game.wins_csv.exists():
        raise SystemExit(f"Missing {game.wins_csv}. Run: python scripts/analyze_pots_and_wins.py")

    with game.wins_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    rows = _filter_last_years(rows, years=last_years)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    done_dates = _load_existing_dates(game.out_jsonl)

    with VedAstroClient(timeout=90.0) as v, game.out_jsonl.open("a", encoding="utf-8") as out:
        for r in rows:
            iso = r["date"]
            if iso in done_dates:
                continue

            check_date = _ddmmyyyy(iso)
            ctx_sky = _unwrap(v.call("get_context_based_astrology_data", {
                "query": (
                    "Return all planet signs (longitudes-based) and notable factors "
                    f"for {check_date} {game.check_time}."
                ),
                "check_date": check_date,
                "check_time": game.check_time,
                "check_latitude": str(check_latitude),
                "check_longitude": str(check_longitude),
                "check_timezone": check_timezone,
                "check_location_name": check_location_name,
            }))

            obj: dict[str, Any] = {
                "game": game.name,
                "date": iso,
                "check": {
                    "date": check_date,
                    "time": game.check_time,
                    "location_name": check_location_name,
                    "latitude": check_latitude,
                    "longitude": check_longitude,
                    "timezone": check_timezone,
                },
                "win": r,
                "sky": ctx_sky,
            }
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
            out.flush()

    return game.out_jsonl


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Enrich jackpot win-days with VedAstro sky data (cached JSONL).")
    ap.add_argument("--years", type=int, default=1, help="How many recent years of win-days to enrich (default: 1).")
    ap.add_argument(
        "--game",
        choices=["austria_lotto_6aus45", "euromillions", "all"],
        default="all",
        help="Which game to enrich (default: all).",
    )
    args = ap.parse_args()

    games = GAMES if args.game == "all" else [g for g in GAMES if g.name == args.game]
    for g in games:
        p = enrich_game(g, last_years=max(1, int(args.years)))
        print(f"✓ {g.name}: {p}")

