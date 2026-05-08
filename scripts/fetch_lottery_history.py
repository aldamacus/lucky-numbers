from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

import httpx


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "historical"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    out_csv: str


SOURCES: list[Source] = [
    Source(
        name="EU EuroMillions",
        url="https://raw.githubusercontent.com/daowa89/lottery-archive/main/eu/euromillions/results.csv",
        out_csv="euromillions_results.csv",
    ),
    Source(
        name="AT Lotto 6 aus 45",
        url="https://raw.githubusercontent.com/daowa89/lottery-archive/main/at/lotto_6aus45/results.csv",
        out_csv="austria_lotto_6aus45_results.csv",
    ),
]


def _parse_iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _filter_last_years(rows: Iterable[dict[str, str]], years: int) -> list[dict[str, str]]:
    today = datetime.now(UTC).date()
    cutoff = date(today.year - years, today.month, today.day)
    out: list[dict[str, str]] = []
    for r in rows:
        d = _parse_iso_date(r["date"])
        if d >= cutoff:
            out.append(r)
    return out


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def fetch_all(years: int = 10) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60) as client:
        for src in SOURCES:
            r = client.get(src.url)
            r.raise_for_status()
            raw_path = OUT_DIR / src.out_csv
            raw_path.write_bytes(r.content)

            # also produce a smaller "last N years" file for quick iteration
            text = r.text
            reader = csv.DictReader(text.splitlines())
            rows = list(reader)
            if not rows:
                raise RuntimeError(f"No rows parsed for {src.name}")

            fieldnames = list(rows[0].keys())
            subset = _filter_last_years(rows, years=years)
            subset_path = OUT_DIR / raw_path.stem.replace("_results", "") / f"last_{years}_years.csv"
            _write_csv(subset_path, subset, fieldnames=fieldnames)

            print(f"✓ {src.name}: {len(rows)} rows → {raw_path}")
            print(f"  ↳ last {years} years: {len(subset)} rows → {subset_path}")


if __name__ == "__main__":
    fetch_all()

