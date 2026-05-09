"""Seed-pool construction from rule definitions and snapshot context."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import AuditEntry, PLANET_NUMBER
from .rules import RuleEvaluator, WhenEvaluationError


def _coerce_to_ints(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(v) for v in value if v is not None]
    return [int(value)]


def _strongest_planet(transits_self: dict[str, dict[str, Any]]) -> str | None:
    if not transits_self:
        return None
    return max(
        transits_self.items(),
        key=lambda kv: (kv[1].get("kaksha", 0), kv[1].get("ashtaka", 0)),
    )[0].capitalize()


def build_pool(
    rules: list[dict[str, Any]],
    context: dict[str, Any],
) -> tuple[dict[int, int], list[AuditEntry]]:
    """Apply rules; return weighted pool {n: weight} + audit trail."""
    ev = RuleEvaluator(context)
    pool: dict[int, int] = defaultdict(int)
    audit: list[AuditEntry] = []
    blocked: set[int] = set()

    def _add(num: int, weight: int):
        if num in blocked:
            return
        pool[num] += weight

    for rule in rules:
        kind = rule.get("kind", "modifiers")
        rid = rule.get("id", "<unnamed>")
        reason = rule.get("reason", "")
        weight = int(rule.get("weight", 1))

        # Evaluate `when` clause. If it raises (missing context key, attr
        # error), record an audit entry so silently-broken rules become
        # visible in --explain output and the Streamlit audit panel.
        try:
            matched = ev.truthy_when(rule.get("when", True))
        except WhenEvaluationError as e:
            audit.append(AuditEntry(
                rule_id=rid, action="when-skipped", numbers=[],
                weight=weight,
                reason=f"SKIPPED — `when` could not be evaluated ({e}). "
                       f"Likely missing snapshot field. Original reason: {reason}",
            ))
            continue
        except Exception as e:
            audit.append(AuditEntry(
                rule_id=rid, action="when-error", numbers=[],
                weight=weight, reason=f"ERROR in when-guard: {e}",
            ))
            continue
        if not matched:
            continue

        action = rule.get("action") or ("seed" if kind == "seeds" else None)
        produced: list[int] = []

        try:
            if kind == "seeds":
                produced = _coerce_to_ints(ev.eval_expr(rule.get("expr")))
                for n in produced:
                    _add(n, weight)

            elif action == "add":
                val = ev.eval_expr(rule.get("value"))
                produced = _coerce_to_ints(val)
                for n in produced:
                    _add(n, weight)

            elif action == "add_many":
                for v in rule.get("values", []):
                    produced += _coerce_to_ints(ev.eval_expr(v))
                for n in produced:
                    _add(n, weight)

            elif action == "remove_range":
                lo = int(ev.eval_expr(rule.get("low")))
                hi = int(ev.eval_expr(rule.get("high")))
                for n in range(lo, hi + 1):
                    blocked.add(n)
                    pool.pop(n, None)
                produced = list(range(lo, hi + 1))

            elif action == "weight_planet":
                planet_raw = ev.eval_expr(rule.get("planet"))
                planet = str(planet_raw or "").capitalize()
                pn = PLANET_NUMBER.get(planet)
                if pn:
                    # boost all harmonics of the planet number up to 50
                    for n in range(pn, 51, pn):
                        _add(n, weight)
                        produced.append(n)

            elif action == "weight_planet_strongest":
                planet = _strongest_planet(context.get("transits", {}).get("self", {}))
                pn = PLANET_NUMBER.get(planet) if planet else None
                if pn:
                    for n in range(pn, 51, pn):
                        _add(n, weight)
                        produced.append(n)
                    reason = f"{reason} → {planet}"

            else:
                # Unknown action: skip silently but record
                pass

        except Exception as e:
            audit.append(AuditEntry(
                rule_id=rid, action=str(action), numbers=[],
                weight=weight, reason=f"ERROR: {e}",
            ))
            continue

        if produced or action == "remove_range":
            audit.append(AuditEntry(
                rule_id=rid, action=str(action),
                numbers=produced, weight=weight, reason=reason,
            ))

    # remove zero/negative entries that may have leaked
    for n in list(pool):
        if n <= 0:
            pool.pop(n)

    return dict(pool), audit

