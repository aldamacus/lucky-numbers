"""Backtest the lucky-numbers algorithm against the last N EuroMillions draws.

Searches for the rule-weight configuration that maximises overlap between
generated picks and historical winning numbers for both persons:
  - Person 1 (self):  Alexandru Damacus  born 1981-09-12 09:00 Sibiu, Romania
  - Person 2 (other): David Damacus      born 2017-12-18 06:00 Vienna, Austria

No VedAstro API calls are made during the backtest:
  - Planet positions: taken from existing data/snapshot.yaml (current sky
    serves as a proxy for recent draws; slow planets change little).
  - Moon phase: computed locally per draw date.

Scoring (per draw):
  strict_score  = main_hits/5  + star_hits/2          (max 1.5)
  top10_score   = main10_hits/5 + star4_hits/2         (max 1.5, looser)
  Overall = mean(strict_score) over all draws

Usage:
    python scripts/backtest_euromillions.py
    python scripts/backtest_euromillions.py --draws 100 --iterations 1000
    python scripts/backtest_euromillions.py --draws 100 --iterations 2000 --apply
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import re
import sys
import time
from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lucky_numbers.engine import _stable_pick
from lucky_numbers.loader import load_rule_files, load_snapshot
from lucky_numbers.moon_phase import moon_phase_at_date, PHASE_EMOJI
from lucky_numbers.seeds import build_pool

import yaml

# ── constants ─────────────────────────────────────────────────────────────────

SYSTEM        = "euromillions"
DRAWS_CSV     = ROOT / "data" / "historical" / "euromillions_results.csv"
OUT_YAML      = ROOT / "data" / "best_weights_euromillions.yaml"

# EuroMillions draw parameters
MAIN_COUNT, MAIN_LO, MAIN_HI = 5, 1, 50
STAR_COUNT, STAR_LO, STAR_HI = 2, 1, 12
DRAW_TIME     = "21:30"   # local CET
UTC_OFFSET    = 1.0       # CET = UTC+1 (approximate, good enough for phase bucket)

# Expected random hit rate (hypergeometric baseline)
RANDOM_BASELINE = (MAIN_COUNT / MAIN_HI) + (STAR_COUNT / STAR_HI)  # ~0.267

# ── Rule categorisation ───────────────────────────────────────────────────────
# Each pattern is matched against rule['id']. Order matters (first match wins).

RULE_CATS: list[tuple[str, str]] = [
    # Layer 1 — birth seeds
    (r"^(self|other)_", "birth"),
    (r"^(royal_star|jupiter_compound|self_other_axis)", "birth"),
    # Layer 2 — transit modifiers
    (r"^(jupiter_10th|venus_9th)", "transit_benefic"),
    (r"^high_bindu", "transit_strongest"),
    (r"^(jupiter_house|moon_transit)", "transit_house"),
    (r"^mars_saturn", "transit_remove"),        # remove_range — keep original weight
    # Layer 3 — dasa
    (r"^mahadasa_lord_emphasis", "dasa_maha_p1"),
    (r"^bhukti_lord_emphasis", "dasa_bhukti_p1"),
    (r"^antara_lord_emphasis", "dasa_antara_p1"),
    (r"^other_mahadasa", "dasa_maha_p2"),
    (r"^other_bhukti", "dasa_bhukti_p2"),
    (r"^saturn_dasa", "dasa_remove"),           # remove_range — keep original weight
    # Layer 4 — combined
    (r"^(shared_lagna|jupiter_other_house|birthday_sum)", "combined"),
    # Layer 5 — win-day
    (r"^win_day_number_bias_top", "winday_global"),
    (r"^win_day_numbers_baseline", "winday_system"),
    (r"^win_day_sign_match.*_other_", "winday_sign_p2"),  # must come before p1
    (r"^win_day_sign_match", "winday_sign_p1"),
    # Layer 6 — moon phase (categorised by current weight: 8=strong,6=mod,4=weak)
    (r"^moon_phase", "moon"),
]

MOON_STRONG_WEIGHT   = 8
MOON_MODERATE_WEIGHT = 6
MOON_WEAK_WEIGHT     = 4


def _categorise(rule: dict) -> str:
    rid = rule.get("id", "")
    for pattern, cat in RULE_CATS:
        if re.search(pattern, rid):
            return cat
    return "other"


# ── Weight configuration ───────────────────────────────────────────────────────

@dataclass
class WeightConfig:
    """One candidate weight configuration.

    Values are *absolute* weights written into matching rules.
    Birth seeds use a multiplier on their original weight so relative
    importance within Layer 1 is preserved.
    """
    birth_mult:      float = 1.0   # ×original_weight for all birth seed rules
    transit_benefic: int   = 4     # jupiter_10th, venus_9th
    transit_strongest: int = 3     # high_bindu_planet_boost
    transit_house:   int   = 2     # jupiter_house_number, moon_transit_house
    dasa_maha_p1:    int   = 3
    dasa_bhukti_p1:  int   = 2
    dasa_antara_p1:  int   = 1
    dasa_maha_p2:    int   = 2
    dasa_bhukti_p2:  int   = 1
    combined:        int   = 2
    winday_global:   int   = 6
    winday_system:   int   = 5
    winday_sign_p1:  int   = 9
    winday_sign_p2:  int   = 4
    moon_strong:     int   = 8
    moon_moderate:   int   = 6
    moon_weak:       int   = 4

    def label(self) -> str:
        return (
            f"birth×{self.birth_mult:.1f} trB={self.transit_benefic}"
            f" trS={self.transit_strongest} trH={self.transit_house}"
            f" md1={self.dasa_maha_p1} bh1={self.dasa_bhukti_p1} an1={self.dasa_antara_p1}"
            f" md2={self.dasa_maha_p2} bh2={self.dasa_bhukti_p2}"
            f" comb={self.combined}"
            f" wdG={self.winday_global} wdS={self.winday_system}"
            f" wdP1={self.winday_sign_p1} wdP2={self.winday_sign_p2}"
            f" 🌙{self.moon_strong}/{self.moon_moderate}/{self.moon_weak}"
        )


# Search space per parameter
SEARCH_SPACE: dict[str, list] = {
    "birth_mult":      [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
    "transit_benefic": [1, 2, 3, 4, 5, 6, 7, 8],
    "transit_strongest": [1, 2, 3, 4, 5, 6],
    "transit_house":   [0, 1, 2, 3, 4],
    "dasa_maha_p1":    [1, 2, 3, 4, 5, 6],
    "dasa_bhukti_p1":  [0, 1, 2, 3, 4],
    "dasa_antara_p1":  [0, 1, 2, 3],
    "dasa_maha_p2":    [0, 1, 2, 3, 4],
    "dasa_bhukti_p2":  [0, 1, 2, 3],
    "combined":        [0, 1, 2, 3, 4],
    "winday_global":   [2, 3, 4, 5, 6, 7, 8, 10],
    "winday_system":   [2, 3, 4, 5, 6, 7, 8, 10],
    "winday_sign_p1":  [5, 6, 7, 8, 9, 10, 11, 12, 14],
    "winday_sign_p2":  [1, 2, 3, 4, 5, 6, 7],
    "moon_strong":     [4, 5, 6, 7, 8, 9, 10, 12],
    "moon_moderate":   [2, 3, 4, 5, 6, 7, 8],
    "moon_weak":       [0, 1, 2, 3, 4, 5, 6],
}

DEFAULT_CONFIG = WeightConfig()


def _random_config(rng: random.Random) -> WeightConfig:
    vals = {f.name: rng.choice(SEARCH_SPACE[f.name]) for f in fields(WeightConfig)}
    return WeightConfig(**vals)


def _neighbour(cfg: WeightConfig, rng: random.Random) -> WeightConfig:
    """Produce a config one step away from cfg (hill climbing)."""
    d = asdict(cfg)
    key = rng.choice(list(SEARCH_SPACE.keys()))
    options = SEARCH_SPACE[key]
    idx = options.index(d[key]) if d[key] in options else 0
    # Move +1 or -1 in the option list
    delta = rng.choice([-1, 1])
    new_idx = max(0, min(len(options) - 1, idx + delta))
    d[key] = options[new_idx]
    return WeightConfig(**d)


# ── Rule weight application ────────────────────────────────────────────────────

def _apply_config(base_rules: list[dict], cfg: WeightConfig,
                  orig_weights: dict[str, int]) -> list[dict]:
    """Return a copy of base_rules with weights replaced per cfg."""
    cat_weight: dict[str, Any] = {
        "transit_benefic":  cfg.transit_benefic,
        "transit_strongest": cfg.transit_strongest,
        "transit_house":    cfg.transit_house,
        "dasa_maha_p1":     cfg.dasa_maha_p1,
        "dasa_bhukti_p1":   cfg.dasa_bhukti_p1,
        "dasa_antara_p1":   cfg.dasa_antara_p1,
        "dasa_maha_p2":     cfg.dasa_maha_p2,
        "dasa_bhukti_p2":   cfg.dasa_bhukti_p2,
        "combined":         cfg.combined,
        "winday_global":    cfg.winday_global,
        "winday_system":    cfg.winday_system,
        "winday_sign_p1":   cfg.winday_sign_p1,
        "winday_sign_p2":   cfg.winday_sign_p2,
    }

    patched: list[dict] = []
    for rule in base_rules:
        r = dict(rule)
        cat = _categorise(r)

        if cat == "birth":
            orig = orig_weights.get(r.get("id", ""), r.get("weight", 1))
            r["weight"] = max(1, round(orig * cfg.birth_mult))
        elif cat == "moon":
            orig_w = orig_weights.get(r.get("id", ""), r.get("weight", 4))
            if orig_w >= MOON_STRONG_WEIGHT:
                r["weight"] = cfg.moon_strong
            elif orig_w >= MOON_MODERATE_WEIGHT:
                r["weight"] = cfg.moon_moderate
            else:
                r["weight"] = cfg.moon_weak
        elif cat in cat_weight:
            r["weight"] = cat_weight[cat]
        # "other", "transit_remove", "dasa_remove" → keep original

        patched.append(r)
    return patched


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_draws(n: int) -> list[dict]:
    """Return the most recent n EuroMillions draws as dicts with keys:
    date (str), main (list[int]), stars (list[int]).
    """
    rows = []
    with DRAWS_CSV.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    rows.sort(key=lambda r: r["date"], reverse=True)
    rows = rows[:n]
    out = []
    for r in rows:
        main  = [int(r[f"n{i}"]) for i in range(1, 6)]
        stars = [int(r[f"s{i}"]) for i in range(1, 3)]
        out.append({"date": r["date"], "main": main, "stars": stars})
    return out


def _build_base_context() -> dict:
    """Build a rule context from the existing snapshot. Planet positions
    are taken as-is (current sky proxy).  Moon phase is overridden per draw.
    """
    snap = load_snapshot()
    ctx = snap.as_context()
    ctx["system"] = SYSTEM
    return ctx


# ── Scoring ────────────────────────────────────────────────────────────────────

@dataclass
class DrawScore:
    date: str
    actual_main: list[int]
    actual_stars: list[int]
    gen_main: list[int]
    gen_stars: list[int]
    main_hits: int    # in top-5 pick
    star_hits: int    # in top-2 pick
    main10_hits: int  # actual main numbers in top-10 candidates
    star4_hits: int   # actual stars in top-4 candidates
    moon_phase: str


def _score_draw(
    draw: dict,
    rules: list[dict],
    ctx: dict,
    seed: str,
) -> DrawScore:
    """Run the engine for one draw and return the detailed score."""
    # Override moon phase for this draw date
    ctx = dict(ctx)
    mp = moon_phase_at_date(draw["date"], DRAW_TIME, UTC_OFFSET)
    ctx["moon_phase"] = {
        "phase": mp.phase,
        "illumination": mp.illumination,
        "age_days": mp.age_days,
    }

    pool, _ = build_pool(rules, ctx)

    # Strict top-5 main + top-2 stars
    gen_main  = _stable_pick(pool, MAIN_COUNT, MAIN_LO, MAIN_HI, seed + "|main")
    gen_stars = _stable_pick(pool, STAR_COUNT, STAR_LO, STAR_HI, seed + "|magic")

    # Wider look: top-10 main + top-4 stars
    gen_main10  = _stable_pick(pool, 10, MAIN_LO, MAIN_HI, seed + "|main")
    gen_stars4  = _stable_pick(pool, 4,  STAR_LO, STAR_HI, seed + "|magic")

    actual_main  = set(draw["main"])
    actual_stars = set(draw["stars"])

    return DrawScore(
        date        = draw["date"],
        actual_main = draw["main"],
        actual_stars= draw["stars"],
        gen_main    = gen_main,
        gen_stars   = gen_stars,
        main_hits   = len(set(gen_main)  & actual_main),
        star_hits   = len(set(gen_stars) & actual_stars),
        main10_hits = len(set(gen_main10) & actual_main),
        star4_hits  = len(set(gen_stars4) & actual_stars),
        moon_phase  = mp.phase,
    )


def score_config(
    cfg: WeightConfig,
    draws: list[dict],
    base_rules: list[dict],
    orig_weights: dict[str, int],
    base_ctx: dict,
    seed: str,
) -> tuple[float, float]:
    """Return (strict_score, top10_score) averaged over all draws. 0-1 each."""
    rules = _apply_config(base_rules, cfg, orig_weights)
    strict_total = 0.0
    top10_total  = 0.0
    for draw in draws:
        ds = _score_draw(draw, rules, base_ctx, seed)
        strict_total += ds.main_hits / MAIN_COUNT + ds.star_hits / STAR_COUNT
        top10_total  += ds.main10_hits / MAIN_COUNT + ds.star4_hits / STAR_COUNT
    n = len(draws)
    return strict_total / n, top10_total / n


# ── Search algorithms ──────────────────────────────────────────────────────────

def random_search(
    n_iter: int,
    draws: list[dict],
    base_rules: list[dict],
    orig_weights: dict[str, int],
    base_ctx: dict,
    seed: str,
    rng: random.Random,
    verbose: bool = True,
) -> list[tuple[float, float, WeightConfig]]:
    """Return sorted list of (strict, top10, config) from random sampling."""
    results: list[tuple[float, float, WeightConfig]] = []
    t0 = time.time()
    for i in range(n_iter):
        cfg = _random_config(rng)
        s, t = score_config(cfg, draws, base_rules, orig_weights, base_ctx, seed)
        results.append((s, t, cfg))
        if verbose and (i + 1) % 100 == 0:
            best_s = max(r[0] for r in results)
            elapsed = time.time() - t0
            print(f"  [{i+1:>4}/{n_iter}] best strict={best_s:.4f}  elapsed={elapsed:.1f}s")
    results.sort(key=lambda x: (-x[0], -x[1]))
    return results


def hill_climb(
    start: WeightConfig,
    draws: list[dict],
    base_rules: list[dict],
    orig_weights: dict[str, int],
    base_ctx: dict,
    seed: str,
    rng: random.Random,
    max_steps: int = 200,
) -> tuple[float, float, WeightConfig]:
    """Local hill-climbing from start config."""
    best_s, best_t = score_config(start, draws, base_rules, orig_weights, base_ctx, seed)
    best_cfg = start
    no_improve = 0
    for _ in range(max_steps):
        nb = _neighbour(best_cfg, rng)
        s, t = score_config(nb, draws, base_rules, orig_weights, base_ctx, seed)
        if s > best_s or (s == best_s and t > best_t):
            best_s, best_t, best_cfg = s, t, nb
            no_improve = 0
        else:
            no_improve += 1
        if no_improve >= 30:
            break
    return best_s, best_t, best_cfg


# ── Detailed report ───────────────────────────────────────────────────────────

def detailed_report(
    cfg: WeightConfig,
    draws: list[dict],
    base_rules: list[dict],
    orig_weights: dict[str, int],
    base_ctx: dict,
    seed: str,
    top_n: int = 20,
) -> None:
    rules = _apply_config(base_rules, cfg, orig_weights)
    draw_scores = [_score_draw(d, rules, base_ctx, seed) for d in draws]

    print(f"\n{'─'*80}")
    print(f"  DETAILED REPORT — last {len(draws)} draws with best weight config")
    print(f"{'─'*80}")
    print(f"  {'Date':<12} {'Actual main':<20} {'Actual stars':<10} "
          f"{'Gen main':<20} {'Gen ⭐':<8} {'Hits':>5} {'Moon':>15}")
    print(f"  {'-'*12} {'-'*20} {'-'*10} {'-'*20} {'-'*8} {'-'*5} {'-'*15}")

    total_main = total_star = total_main10 = total_star4 = 0
    for ds in draw_scores[:top_n]:
        em = PHASE_EMOJI.get(ds.moon_phase, "🌙")
        hits_str = f"M:{ds.main_hits} S:{ds.star_hits}"
        print(f"  {ds.date:<12} "
              f"{str(ds.actual_main):<20} "
              f"{str(ds.actual_stars):<10} "
              f"{str(ds.gen_main):<20} "
              f"{str(ds.gen_stars):<8} "
              f"{hits_str:>5}  "
              f"{em}{ds.moon_phase}")
        total_main  += ds.main_hits
        total_star  += ds.star_hits
        total_main10 += ds.main10_hits
        total_star4  += ds.star4_hits

    n = len(draw_scores[:top_n])
    print(f"\n  Averages (top {n} draws):")
    print(f"    Main hits per draw (strict top-5):  {total_main/n:.3f} / {MAIN_COUNT}  "
          f"(random baseline {MAIN_COUNT**2/MAIN_HI:.3f})")
    print(f"    Star hits per draw (strict top-2):  {total_star/n:.3f} / {STAR_COUNT}  "
          f"(random baseline {STAR_COUNT**2/STAR_HI:.3f})")
    print(f"    Main hits (top-10 pool):            {total_main10/n:.3f} / {MAIN_COUNT}")
    print(f"    Star hits (top-4 pool):             {total_star4/n:.3f} / {STAR_COUNT}")

    # Moon phase breakdown
    phase_hits: dict[str, list[int]] = {}
    for ds in draw_scores:
        phase_hits.setdefault(ds.moon_phase, []).append(ds.main_hits)
    print(f"\n  Main-number hits by moon phase:")
    for phase, hits in sorted(phase_hits.items(), key=lambda x: -sum(x[1])/max(1,len(x[1]))):
        em = PHASE_EMOJI.get(phase, "🌙")
        avg = sum(hits) / len(hits)
        print(f"    {em} {phase:<20}  n={len(hits):>3}  avg_hits={avg:.3f}")


# ── Apply best config to rule files ───────────────────────────────────────────

def _patch_rule_file(path: Path, cfg: WeightConfig,
                     orig_weights: dict[str, int]) -> int:
    """Patch one rule YAML file in-place. Returns count of patched rules."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    changed = 0
    for section in ("modifiers", "seeds"):
        for rule in data.get(section, []):
            cat = _categorise(rule)
            orig_w = orig_weights.get(rule.get("id", ""), rule.get("weight", 1))
            new_w: int | None = None
            if cat == "birth":
                new_w = max(1, round(orig_w * cfg.birth_mult))
            elif cat == "transit_benefic":
                new_w = cfg.transit_benefic
            elif cat == "transit_strongest":
                new_w = cfg.transit_strongest
            elif cat == "transit_house":
                new_w = cfg.transit_house
            elif cat == "dasa_maha_p1":
                new_w = cfg.dasa_maha_p1
            elif cat == "dasa_bhukti_p1":
                new_w = cfg.dasa_bhukti_p1
            elif cat == "dasa_antara_p1":
                new_w = cfg.dasa_antara_p1
            elif cat == "dasa_maha_p2":
                new_w = cfg.dasa_maha_p2
            elif cat == "dasa_bhukti_p2":
                new_w = cfg.dasa_bhukti_p2
            elif cat == "combined":
                new_w = cfg.combined
            elif cat == "winday_global":
                new_w = cfg.winday_global
            elif cat == "winday_system":
                new_w = cfg.winday_system
            elif cat == "winday_sign_p1":
                new_w = cfg.winday_sign_p1
            elif cat == "winday_sign_p2":
                new_w = cfg.winday_sign_p2
            elif cat == "moon":
                if orig_w >= MOON_STRONG_WEIGHT:
                    new_w = cfg.moon_strong
                elif orig_w >= MOON_MODERATE_WEIGHT:
                    new_w = cfg.moon_moderate
                else:
                    new_w = cfg.moon_weak

            if new_w is not None and rule.get("weight") != new_w:
                rule["weight"] = new_w
                changed += 1

    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True,
                               sort_keys=False, width=120), encoding="utf-8")
    return changed


def apply_best_config(cfg: WeightConfig, orig_weights: dict[str, int]) -> None:
    rules_dir = ROOT / "rules"
    total = 0
    for p in sorted(rules_dir.glob("*.yaml")):
        n = _patch_rule_file(p, cfg, orig_weights)
        if n:
            print(f"  patched {p.name}: {n} rule(s) updated")
            total += n
    print(f"  Total rules patched: {total}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest EuroMillions weight optimisation")
    ap.add_argument("--draws",      type=int, default=100,  help="Number of recent draws to score (default 100)")
    ap.add_argument("--iterations", type=int, default=1000, help="Random search iterations (default 1000)")
    ap.add_argument("--top",        type=int, default=10,   help="Top configs to show in leaderboard (default 10)")
    ap.add_argument("--seed",       type=int, default=42,   help="RNG seed for reproducibility")
    ap.add_argument("--apply",      action="store_true",    help="Patch rule files with the best config")
    ap.add_argument("--no-climb",   action="store_true",    help="Skip hill climbing")
    ap.add_argument("--detail-rows",type=int, default=20,   help="Rows in per-draw detail table (default 20)")
    args = ap.parse_args()

    rng = random.Random(args.seed)

    # ── Load data ──────────────────────────────────────────────────────────────
    print(f"\n{'═'*80}")
    print("  EuroMillions Weight Backtester")
    print(f"  Persons: Alexandru Damacus (1981-09-12) + David Damacus (2017-12-18)")
    print(f"{'═'*80}\n")

    if not DRAWS_CSV.exists():
        print(f"ERROR: {DRAWS_CSV} not found. Run: python scripts/fetch_lottery_history.py")
        sys.exit(1)

    draws = _load_draws(args.draws)
    print(f"  Draws loaded:     {len(draws)}  ({draws[-1]['date']} → {draws[0]['date']})")

    base_rules = load_rule_files()
    orig_weights = {r["id"]: r.get("weight", 1) for r in base_rules if "id" in r}
    base_ctx = _build_base_context()

    # Build the seed used by _stable_pick (mirrors engine.py)
    snap = load_snapshot()
    pick_seed = (
        f"{SYSTEM}"
        f"|dasa_self={snap.dasa.get('self')}"
        f"|dasa_other={snap.dasa.get('other')}"
        f"|t_self={snap.transits.get('self', {})}"
        f"|t_other={snap.transits.get('other', {})}"
    )

    # Random baseline
    print(f"  Rules loaded:     {len(base_rules)}")
    print(f"  Random baseline:  {RANDOM_BASELINE:.4f}  (expected hits if fully random)")

    # Default config score
    def_s, def_t = score_config(DEFAULT_CONFIG, draws, base_rules, orig_weights, base_ctx, pick_seed)
    print(f"  Default config:   strict={def_s:.4f}  top10={def_t:.4f}")

    # ── Random search ──────────────────────────────────────────────────────────
    print(f"\n  Random search: {args.iterations} iterations …")
    results = random_search(args.iterations, draws, base_rules, orig_weights,
                            base_ctx, pick_seed, rng, verbose=True)

    # ── Hill climbing on top configs ───────────────────────────────────────────
    if not args.no_climb:
        print(f"\n  Hill climbing on top {min(5, args.top)} configs …")
        climbed: list[tuple[float, float, WeightConfig]] = []
        for s, t, cfg in results[:5]:
            cs, ct, ccfg = hill_climb(cfg, draws, base_rules, orig_weights,
                                      base_ctx, pick_seed, rng)
            climbed.append((cs, ct, ccfg))
            print(f"    {s:.4f} → {cs:.4f}  (top10: {t:.4f} → {ct:.4f})")
        results = climbed + results
        results.sort(key=lambda x: (-x[0], -x[1]))

    best_s, best_t, best_cfg = results[0]

    # ── Leaderboard ────────────────────────────────────────────────────────────
    print(f"\n  {'─'*80}")
    print(f"  TOP {args.top} WEIGHT CONFIGURATIONS")
    print(f"  {'─'*80}")
    print(f"  {'Rank':>4}  {'Strict':>7}  {'Top-10':>7}  Config")
    print(f"  {'─'*4}  {'─'*7}  {'─'*7}  {'─'*55}")
    seen: set[str] = set()
    shown = 0
    for s, t, cfg in results:
        lbl = cfg.label()
        if lbl in seen:
            continue
        seen.add(lbl)
        marker = " ◄ BEST" if shown == 0 else ""
        print(f"  {shown+1:>4}  {s:.4f}   {t:.4f}   {lbl}{marker}")
        shown += 1
        if shown >= args.top:
            break

    print(f"\n  Default config:  strict={def_s:.4f}  top10={def_t:.4f}")
    print(f"  Best found:      strict={best_s:.4f}  top10={best_t:.4f}  "
          f"(+{best_s-def_s:+.4f} vs default)")

    # ── Best config summary ────────────────────────────────────────────────────
    print(f"\n  BEST WEIGHT CONFIG (full breakdown):")
    print(f"  {'─'*55}")
    fc = asdict(best_cfg)
    for field_name, val in fc.items():
        orig_default = getattr(DEFAULT_CONFIG, field_name)
        change = f"  ← was {orig_default}" if val != orig_default else ""
        print(f"    {field_name:<22} = {val}{change}")

    # ── Per-draw detail ────────────────────────────────────────────────────────
    detailed_report(best_cfg, draws, base_rules, orig_weights, base_ctx, pick_seed,
                    top_n=args.detail_rows)

    # ── Save best config ───────────────────────────────────────────────────────
    out = {
        "backtest": {
            "draws": len(draws),
            "date_range": f"{draws[-1]['date']} to {draws[0]['date']}",
            "iterations": args.iterations,
            "strict_score": round(best_s, 6),
            "top10_score":  round(best_t, 6),
            "default_strict": round(def_s, 6),
            "improvement":   round(best_s - def_s, 6),
            "random_baseline": round(RANDOM_BASELINE, 6),
        },
        "best_weights": asdict(best_cfg),
    }
    OUT_YAML.write_text(yaml.dump(out, default_flow_style=False, sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")
    print(f"\n  ✓ Best config saved to {OUT_YAML}")

    # ── Patch rule files ────────────────────────────────────────────────────────
    if args.apply:
        print(f"\n  Applying best weights to rules/ …")
        apply_best_config(best_cfg, orig_weights)
        print("  ✓ Rule files patched. Run 'lucky generate euromillions --explain' to verify.")
    else:
        print(f"\n  Tip: re-run with --apply to patch the live rule files with the best config.")


if __name__ == "__main__":
    main()
