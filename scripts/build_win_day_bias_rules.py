from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WINS_CSV = ROOT / "data" / "historical" / "analysis" / "austria_lotto_6aus45_jackpot_wins.csv"
OUT_RULES = ROOT / "rules" / "win_day_bias.yaml"


def _parse_numbers(s: str) -> list[int]:
    # numbers field is like: "4 15 24 27 39 41 33" (last is Zusatzzahl)
    out: list[int] = []
    for part in (s or "").strip().split():
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def main(top_n: int = 18) -> None:
    if not WINS_CSV.exists():
        raise SystemExit(f"Missing {WINS_CSV}. Run: python scripts/analyze_pots_and_wins.py")

    rows: list[dict[str, str]] = []
    with WINS_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    freq: Counter[int] = Counter()
    for r in rows:
        nums = _parse_numbers(r.get("numbers", ""))
        # weight main numbers more than Zusatz; treat last token as zusatzzahl
        main = nums[:6]
        zz = nums[6:7]
        for n in main:
            freq[n] += 3
        for n in zz:
            freq[n] += 1

    # Keep only numbers valid for Loto6 (1..46)
    freq = Counter({n: c for n, c in freq.items() if 1 <= n <= 46})
    top = [n for n, _ in freq.most_common(top_n)]

    rules = {
        "modifiers": [
            {
                "id": "win_day_number_bias_top",
                "when": "true",
                "action": "add_many",
                "values": top,
                "weight": 6,
                "reason": (
                    "Boost numbers frequently appearing on historical jackpot-win days "
                    "(AT Lotto 6 aus 45), giving win-days higher importance."
                ),
            }
        ]
    }

    OUT_RULES.write_text(yaml.safe_dump(rules, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"✓ wrote {OUT_RULES} (top_n={top_n})")


if __name__ == "__main__":
    main()

