from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

import httpx


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "historical" / "pots"


@dataclass(frozen=True)
class Game:
    name: str
    out_csv: str
    # URL pattern that needs {year} substitution
    url_pattern: str
    encoding: str = "cp1252"
    delimiter: str = ";"


GAMES: list[Game] = [
    Game(
        name="austria_lotto_6aus45",
        out_csv="austria_lotto_6aus45_pots.csv",
        url_pattern="https://statics.win2day.at/media/NN_W2D_STAT_Lotto_{year}.csv",
    ),
    Game(
        name="euromillions",
        out_csv="euromillions_pots.csv",
        url_pattern="https://statics.win2day.at/media/NN_W2D_STAT_EUML_{year}.csv",
    ),
]


_DECIMAL_COMMA = re.compile(r"[.\s]")


def _parse_eur_amount(s: str) -> int | None:
    """
    Parse German-formatted currency strings like '  40.104.043,00' into cents-less EUR int.
    Returns whole EUR (rounded down).
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # remove thousand separators and spaces
    s = _DECIMAL_COMMA.sub("", s)
    # now '40104043,00'
    if "," in s:
        euros, _cents = s.split(",", 1)
    else:
        euros = s
    try:
        return int(euros)
    except ValueError:
        return None


def _is_int(s: str) -> bool:
    try:
        int(str(s).strip())
        return True
    except Exception:
        return False


def _iter_years(last_years: int) -> Iterable[int]:
    today = datetime.now(UTC).date()
    start = today.year - last_years + 1
    for y in range(start, today.year + 1):
        yield y


def _normalize_lotto_6aus45_rows(rows: list[dict[str, str]], year: int) -> list[dict[str, str]]:
    """
    win2day Lotto yearly CSV has multiple prize tiers per draw.
    We keep the 6er line (jackpot) and extract:
      - date (YYYY-MM-DD)
      - jackpot_eur (Quote_1_5)
      - jackpot_winners_at (Anzahl_1_5 if numeric)
      - jackpot_won (true/false)
    """
    out: list[dict[str, str]] = []
    for r in rows:
        rang = (r.get("Rang_1_5") or "").strip()
        if rang != "6er":
            continue

        # Datum is '03.01.' (no year)
        datum = (r.get("Datum") or "").strip()
        m = re.match(r"(\d{2})\.(\d{2})\.", datum)
        if not m:
            continue
        dd, mm = int(m.group(1)), int(m.group(2))
        d = date(year, mm, dd).isoformat()

        anzahl = (r.get("Anzahl_1_5") or "").strip()
        winners = int(anzahl) if _is_int(anzahl) else None
        won = winners is not None and winners > 0

        jackpot = _parse_eur_amount((r.get("Quote_1_5") or "").strip())

        out.append({
            "date": d,
            "jackpot_eur": "" if jackpot is None else str(jackpot),
            "jackpot_won": "1" if won else "0",
            "jackpot_winners": "" if winners is None else str(winners),
            "source": f"win2day:NN_W2D_STAT_Lotto_{year}.csv",
        })
    return out


def _normalize_euromillions_rows(rows: list[dict[str, str]], year: int) -> list[dict[str, str]]:
    """
    win2day EuroMillionen yearly CSV:
    - Ziehungstag: 'Di. 02.01.2024'
    - Europa: 'JP' or a number (winner count in Europe)
    - Quoten: jackpot amount
    """
    out: list[dict[str, str]] = []
    for r in rows:
        # only rank 1
        if str(r.get("Rang", "")).strip() != "1":
            continue

        z = (r.get("Ziehungstag") or "").strip()
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", z)
        if not m:
            continue
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = date(yyyy, mm, dd).isoformat()

        europa = (r.get("Europa") or "").strip()
        winners = int(europa) if _is_int(europa) else None
        won = winners is not None and winners > 0

        jackpot = _parse_eur_amount((r.get("Quoten") or "").strip())

        out.append({
            "date": d,
            "jackpot_eur": "" if jackpot is None else str(jackpot),
            "jackpot_won": "1" if won else "0",
            "jackpot_winners": "" if winners is None else str(winners),
            "source": f"win2day:NN_W2D_STAT_EUML_{year}.csv",
        })
    return out


def fetch(last_years: int = 10) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60) as client:
        for game in GAMES:
            merged: list[dict[str, str]] = []
            for y in _iter_years(last_years):
                url = game.url_pattern.format(year=y)
                resp = client.get(url)
                resp.raise_for_status()
                text = resp.content.decode(game.encoding, errors="replace")
                reader = csv.DictReader(text.splitlines(), delimiter=game.delimiter)
                rows = list(reader)

                if game.name == "austria_lotto_6aus45":
                    merged.extend(_normalize_lotto_6aus45_rows(rows, year=y))
                elif game.name == "euromillions":
                    merged.extend(_normalize_euromillions_rows(rows, year=y))
                else:
                    raise RuntimeError(f"Unknown game {game.name}")

            # sort + de-dup by date (keep last)
            by_date: dict[str, dict[str, str]] = {}
            for r in merged:
                by_date[r["date"]] = r
            final = [by_date[d] for d in sorted(by_date.keys())]

            out_path = OUT_DIR / game.out_csv
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["date", "jackpot_eur", "jackpot_won", "jackpot_winners", "source"])
                w.writeheader()
                w.writerows(final)

            print(f"✓ {game.name}: {len(final)} rows → {out_path}")


if __name__ == "__main__":
    fetch()

