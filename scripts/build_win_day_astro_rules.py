from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "historical"
ANALYSIS = HIST / "analysis"
WIN_SKY = HIST / "planet_adjustments" / "win_days"


@dataclass(frozen=True)
class GameCfg:
    system: str
    wins_csv: Path
    win_sky_jsonl: Path
    out_rules: Path
    # The jackpot-win CSVs have a single "numbers" column (space separated).
    # This defines how many leading numbers are considered "main" and how many
    # trailing numbers are special (stars / etc) for frequency weighting.
    main_count: int
    special_count: int


GAMES: list[GameCfg] = [
    GameCfg(
        system="loto6",
        wins_csv=ANALYSIS / "austria_lotto_6aus45_jackpot_wins.csv",
        win_sky_jsonl=WIN_SKY / "austria_lotto_6aus45_jackpot_wins.jsonl",
        out_rules=ROOT / "rules" / "win_day_astro_bias_loto6.yaml",
        main_count=6,
        special_count=0,  # ignore Zusatz here (it is included in CSV numbers string)
    ),
    GameCfg(
        system="euromillions",
        wins_csv=ANALYSIS / "euromillions_jackpot_wins.csv",
        win_sky_jsonl=WIN_SKY / "euromillions_jackpot_wins.jsonl",
        out_rules=ROOT / "rules" / "win_day_astro_bias_euromillions.yaml",
        main_count=5,
        special_count=2,  # stars
    ),
]


PLANETS = ["sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn"]


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


def _parse_numbers_field(s: str) -> list[int]:
    out: list[int] = []
    for part in (s or "").strip().split():
        n = _to_int(part)
        if n is not None:
            out.append(n)
    return out


def _load_win_sky(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Run: python scripts/enrich_jackpot_wins_with_vedastro.py"
        )
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _extract_signs_from_sky(sky: dict[str, Any]) -> dict[str, str] | None:
    """
    Try to find a JSON dict of planet->sign from VedAstro context-tool evidence.
    We prefer evidence method 'AllPlanetSignsBasedOnHouseLongitudes'.
    """
    for ev in sky.get("evidence", []) or []:
        if ev.get("method") == "AllPlanetSignsBasedOnHouseLongitudes":
            kr = ev.get("key_result")
            if isinstance(kr, str):
                try:
                    obj = json.loads(kr)
                    if isinstance(obj, dict) and obj:
                        # normalize keys to lowercase planet names
                        return {str(k).strip().lower(): str(v).strip() for k, v in obj.items()}
                except Exception:
                    pass
    return None


def build_rules(cfg: GameCfg, *, top_numbers: int = 18, top_signs_per_planet: int = 2) -> Path:
    wins = _read_csv(cfg.wins_csv)
    win_sky = _load_win_sky(cfg.win_sky_jsonl)

    # 1) Numbers that appear on jackpot-win days (high importance baseline)
    freq_nums: Counter[int] = Counter()
    for r in wins:
        nums = _parse_numbers_field(r.get("numbers", ""))
        if not nums:
            continue

        main = nums[: cfg.main_count]
        special = nums[cfg.main_count : cfg.main_count + cfg.special_count] if cfg.special_count else []

        for n in main:
            freq_nums[n] += 3
        for n in special:
            freq_nums[n] += 2

    # constrain to plausible ranges:
    if cfg.system == "loto6":
        freq_nums = Counter({n: c for n, c in freq_nums.items() if 1 <= n <= 46})
    else:
        # euroMillions main 1..50 and stars 1..12 (both share the pool, stable_pick will filter by range)
        freq_nums = Counter({n: c for n, c in freq_nums.items() if 1 <= n <= 50})

    top_nums = [n for n, _ in freq_nums.most_common(top_numbers)]

    # 2) Win-day astrology signatures: most common sign per planet on win days
    sign_counts: dict[str, Counter[str]] = {p: Counter() for p in PLANETS}
    for rec in win_sky:
        sky = rec.get("sky") or {}
        signs = _extract_signs_from_sky(sky) or {}
        for p in PLANETS:
            s = signs.get(p)
            if s:
                sign_counts[p][s] += 1

    # Create rules:
    # - system-specific (uses ctx["system"] added in engine)
    # - when current transits match common win-day signs, boost win-day numbers strongly
    modifiers: list[dict[str, Any]] = []

    # baseline: always-on win-day number boost (already exists via win_day_bias.yaml,
    # but keep this system-specific and higher weight for astrology pipeline)
    modifiers.append({
        "id": f"win_day_numbers_baseline_{cfg.system}",
        "when": f"system == '{cfg.system}'",
        "action": "add_many",
        "values": top_nums,
        "weight": 5,
        "reason": "Win-day numbers baseline boost (system-specific).",
    })

    for planet in PLANETS:
        common = [s for s, _ in sign_counts[planet].most_common(top_signs_per_planet)]
        for sign in common:
            # Person 1 (protagonist) — full strength
            modifiers.append({
                "id": f"win_day_sign_match_{cfg.system}_{planet}_{sign}".lower().replace(" ", "_"),
                "when": f"system == '{cfg.system}' and transits.self.{planet}.sign == '{sign}'",
                "action": "add_many",
                "values": top_nums,
                "weight": 9,
                "reason": (
                    f"Win-day astrology bias (Person 1): many jackpot-win days had "
                    f"{planet.title()} in {sign} at draw time; boost win-day numbers "
                    "when today's transits match."
                ),
            })
            # Person 2 (secondary) — about half the weight so they nudge the
            # pool but cannot out-vote Person 1's signature.
            modifiers.append({
                "id": f"win_day_sign_match_{cfg.system}_other_{planet}_{sign}".lower().replace(" ", "_"),
                "when": f"system == '{cfg.system}' and transits.other.{planet}.sign == '{sign}'",
                "action": "add_many",
                "values": top_nums,
                "weight": 4,
                "reason": (
                    f"Win-day astrology bias (Person 2): {planet.title()} in {sign} "
                    "in Person 2's current sky matches a historical jackpot-win "
                    "signature — secondary boost."
                ),
            })

    out = {"modifiers": modifiers}
    cfg.out_rules.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return cfg.out_rules


if __name__ == "__main__":
    for cfg in GAMES:
        p = build_rules(cfg)
        print(f"✓ wrote {p}")

