"""Top-level orchestration: snapshot -> rules -> numbers."""
from __future__ import annotations

import hashlib
from typing import Any

from .loader import load_rule_files, load_snapshot, load_systems
from .models import GenerationResult, Snapshot
from .seeds import build_pool


def _stable_pick(
    pool: dict[int, int],
    count: int,
    lo: int,
    hi: int,
    seed: str,
) -> list[int]:
    """Deterministically pick `count` numbers from pool within [lo, hi]."""
    candidates = [(n, w) for n, w in pool.items() if lo <= n <= hi]
    candidates.sort(key=lambda x: (-x[1], x[0]))   # weight desc, then number asc
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

    # Include BOTH people’s live sky + dasa in the deterministic seed so
    # outputs change when either person’s current snapshot changes.
    seed = (
        f"{system_name}"
        f"|dasa_self={snapshot.dasa.get('self')}"
        f"|dasa_son={snapshot.dasa.get('son')}"
        f"|t_self={snapshot.transits.get('self', {})}"
        f"|t_son={snapshot.transits.get('son', {})}"
    )

    main_cfg = sys_cfg["main"]
    main = _stable_pick(pool, main_cfg["count"], main_cfg["min"], main_cfg["max"], seed + "|main")

    magic: list[int] = []
    if "magic" in sys_cfg:
        m = sys_cfg["magic"]
        magic = _stable_pick(pool, m["count"], m["min"], m["max"], seed + "|magic")

    return GenerationResult(system=system_name, main=main, magic=magic, audit=audit)

