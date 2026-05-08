from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "historical"
OUT_DIR = DATA / "analysis"


@dataclass(frozen=True)
class GameCfg:
    name: str
    results_csv: Path
    pots_csv: Path
    number_fields: list[str]


GAMES: list[GameCfg] = [
    GameCfg(
        name="euromillions",
        results_csv=DATA / "euromillions_results.csv",
        pots_csv=DATA / "pots" / "euromillions_pots.csv",
        number_fields=["n1", "n2", "n3", "n4", "n5", "s1", "s2"],
    ),
    GameCfg(
        name="austria_lotto_6aus45",
        results_csv=DATA / "austria_lotto_6aus45_results.csv",
        pots_csv=DATA / "pots" / "austria_lotto_6aus45_pots.csv",
        number_fields=["n1", "n2", "n3", "n4", "n5", "n6", "zusatzzahl"],
    ),
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_int(s: str | None) -> int | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _format_numbers(row: dict[str, str], fields: list[str]) -> str:
    vals = []
    for f in fields:
        v = row.get(f)
        if v is None:
            continue
        vals.append(str(v))
    return " ".join(vals)


def analyze_game(cfg: GameCfg) -> tuple[Path, Path]:
    results = _read_csv(cfg.results_csv)
    pots = _read_csv(cfg.pots_csv)

    res_by_date = {r["date"]: r for r in results if r.get("date")}
    pots_sorted = sorted((p for p in pots if p.get("date")), key=lambda x: x["date"])

    rows_out: list[dict[str, Any]] = []
    wins_out: list[dict[str, Any]] = []

    prev_jp: int | None = None
    for p in pots_sorted:
        d = p["date"]
        jp = _to_int(p.get("jackpot_eur"))
        won = str(p.get("jackpot_won", "")).strip() == "1"
        winners = _to_int(p.get("jackpot_winners"))

        delta = None
        if jp is not None and prev_jp is not None:
            delta = jp - prev_jp
        prev_jp = jp if jp is not None else prev_jp

        draw = res_by_date.get(d)
        nums = _format_numbers(draw or {}, cfg.number_fields) if draw else ""

        rec = {
            "date": d,
            "jackpot_eur": jp,
            "delta_from_prev_eur": delta,
            "jackpot_won": won,
            "jackpot_winners": winners,
            "numbers": nums,
        }
        rows_out.append(rec)

        # Determine “someone won the pot”:
        # - if winners is known, winners > 0
        # - otherwise fall back to jackpot_won flag (some feeds omit counts)
        is_win = (winners is not None and winners > 0) or (winners is None and won)
        if is_win:
            wins_out.append(rec)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_all = OUT_DIR / f"{cfg.name}_pots_joined.csv"
    out_wins = OUT_DIR / f"{cfg.name}_jackpot_wins.csv"

    def _write(path: Path, rs: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "date",
                    "jackpot_eur",
                    "delta_from_prev_eur",
                    "jackpot_won",
                    "jackpot_winners",
                    "numbers",
                ],
            )
            w.writeheader()
            for r in rs:
                w.writerow(r)

    _write(out_all, rows_out)
    _write(out_wins, wins_out)
    return out_all, out_wins


def main() -> None:
    for cfg in GAMES:
        out_all, out_wins = analyze_game(cfg)
        print(f"✓ {cfg.name}: {out_all}")
        print(f"  ↳ jackpot wins: {out_wins}")


if __name__ == "__main__":
    main()

