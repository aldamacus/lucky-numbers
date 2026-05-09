"""Top-level orchestration: snapshot -> rules -> numbers."""
from __future__ import annotations

import hashlib
from typing import Any

from .loader import load_rule_files, load_snapshot, load_systems
from .models import GenerationResult, Snapshot, PLANET_NUMBER
from .seeds import build_pool


def _seed_rank(seed: str, n: int) -> int:
    """Stable per-seed pseudo-random rank for tie-breaking.

    Two numbers with identical pool weight previously fell back to "smaller
    number wins", which made the top-N pick collapse to the lowest numbers in
    the historically-frequent winning list regardless of who Person 1 / 2 are.
    Hashing (seed, n) means equal-weight numbers shuffle deterministically per
    snapshot, so changing any person/relationship/dasa input visibly perturbs
    the final pick.
    """
    h = hashlib.sha256(f"{seed}|{n}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def _stable_pick(
    pool: dict[int, int],
    count: int,
    lo: int,
    hi: int,
    seed: str,
) -> list[int]:
    """Deterministically pick `count` numbers from pool within [lo, hi].

    Sort key:
      1. weight desc      (rule-driven importance always wins)
      2. seed-hash asc    (per-snapshot tie-break — person sensitive)
      3. number asc       (final fallback for total determinism)
    """
    candidates = [(n, w) for n, w in pool.items() if lo <= n <= hi]
    candidates.sort(key=lambda x: (-x[1], _seed_rank(seed, x[0]), x[0]))
    chosen: list[int] = []
    seen: set[int] = set()
    for n, _ in candidates:
        if n not in seen:
            chosen.append(n)
            seen.add(n)
        if len(chosen) >= count:
            break

    # Fill gap deterministically using SHA-based hash of (pool + seed)
    if len(chosen) < count:
        h = hashlib.sha256(
            (seed + repr(sorted(pool.items()))).encode()
        ).digest()
        cursor = 0
        while len(chosen) < count and cursor < 256:
            n = lo + (h[cursor % len(h)] + cursor) % (hi - lo + 1)
            cursor += 1
            if n not in seen and lo <= n <= hi:
                chosen.append(n)
                seen.add(n)

    return sorted(chosen)


def generate(
    system_name: str,
    snapshot: Snapshot | None = None,
) -> GenerationResult:
    snapshot = snapshot or load_snapshot()
    systems = load_systems()
    if system_name not in systems:
        raise ValueError(f"Unknown system '{system_name}'. Known: {list(systems)}")
    sys_cfg: dict[str, Any] = systems[system_name]

    rules = load_rule_files()
    ctx = snapshot.as_context()
    # Allow rules to branch per lottery system (e.g. loto6 vs euromillions).
    ctx["system"] = system_name
    pool, audit = build_pool(rules, ctx)

    # Inject relationship-date planet numbers directly into the pool.
    # These derive from the sky on the marriage/hookup date and carry a
    # fixed weight of 3 — influential but not dominant over rule weights.
    if snapshot.relationship and snapshot.relationship.transits_on_date:
        rel_pool_weight = 3
        for planet_raw in snapshot.relationship.transits_on_date:
            planet = str(planet_raw).capitalize()
            pn = PLANET_NUMBER.get(planet)
            if pn:
                for n in range(pn, 51, pn):
                    pool[n] = pool.get(n, 0) + rel_pool_weight

    # Include BOTH people's live sky + dasa AND relationship in the
    # deterministic seed so outputs change when any snapshot changes.
    rel_seed = ""
    if snapshot.relationship:
        rel_seed = (
            f"|rel_type={snapshot.relationship.relation_type}"
            f"|rel_date={snapshot.relationship.event_date}"
            f"|rel_sky={sorted(snapshot.relationship.transits_on_date.keys())}"
        )

    seed = (
        f"{system_name}"
        f"|dasa_self={snapshot.dasa.get('self')}"
        f"|dasa_other={snapshot.dasa.get('other')}"
        f"|t_self={snapshot.transits.get('self', {})}"
        f"|t_other={snapshot.transits.get('other', {})}"
        f"{rel_seed}"
    )

    main_cfg = sys_cfg["main"]
    main = _stable_pick(pool, main_cfg["count"], main_cfg["min"], main_cfg["max"], seed + "|main")

    magic: list[int] = []
    if "magic" in sys_cfg:
        m = sys_cfg["magic"]
        magic = _stable_pick(pool, m["count"], m["min"], m["max"], seed + "|magic")

    return GenerationResult(system=system_name, main=main, magic=magic, audit=audit)
