# Lucky Numbers — Technical Documentation

End-to-end reference for the algorithm: data flow, modules, rule semantics,
weight pyramid, determinism guarantees, and where to extend each layer.

For installation/usage see [README.md](./README.md).
For the upstream astrology API see [VedAstro-API-Guide.md](./VedAstro-API-Guide.md).

---

## 1. Top-down data flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ INPUTS                                                                  │
│   Streamlit form  ─┐                                                    │
│   data/people.yaml ┴──► Person 1 (protagonist)  + Person 2 (optional)   │
│   Relationship form ──► relation_type, event_date, event_time           │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ FETCH (vedastro_client.py + numerology.py)                              │
│   per person: transits, current dasa, natal chart, Chaldean numerology  │
│   per relationship: sky on event date                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SNAPSHOT (models.Snapshot)                                              │
│   self_, son, other, transits.{self,son}, dasa.{self,son},              │
│   relationship{type, date, transits_on_date}                            │
│   each Person carries: birth, numerology, natal                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                 ▼
┌──────────────────────────────────┐   ┌────────────────────────────────┐
│ RULE ENGINE (seeds.build_pool)   │   │ DIRECT INJECTION (engine.py)   │
│   reads rules/*.yaml             │   │   relationship-date planets →  │
│   evaluates `when`               │   │   harmonics added at fixed     │
│   applies action                 │   │   weight 3                     │
│   builds pool {n: weight}        │   │                                │
│   builds audit trail             │   │                                │
└──────────────────────────────────┘   └────────────────────────────────┘
                  │                                 │
                  └────────────────┬────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SELECTION (engine._stable_pick)                                         │
│   sort by (weight desc, seed-hash, number asc)                          │
│   pick top N within [lo, hi]                                            │
│   SHA-256 backfill if pool too small                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ OUTPUT (engine.GenerationResult)                                        │
│   system, main[], magic[], audit[]                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module map

| Module | Responsibility |
|---|---|
| `src/lucky_numbers/models.py` | Typed data: `Birth`, `Person`, `RelationshipData`, `Snapshot`, `AuditEntry`, `GenerationResult`. Constants `PLANET_NUMBER` and `SIGN_INDEX`. |
| `src/lucky_numbers/loader.py` | YAML parsing for `data/people.yaml`, `data/snapshot.yaml`, `configs/systems.yaml`, every `rules/*.yaml`. Builds Snapshots from dicts (UI path) and from disk (CLI path). |
| `src/lucky_numbers/numerology.py` | Local Chaldean letter→digit table, `name_number`, `root_number`, `ruling_planet`, `chaldean_profile(name)`. No API call — used by the UI to populate `numerology` blocks for both persons. |
| `src/lucky_numbers/vedastro_client.py` | JSON-RPC 2.0 client for the public VedAstro MCP. Wrappers: `transits`, `current_dasa`, `numerology`, `sky_at_date`, `natal_chart`. |
| `src/lucky_numbers/rules.py` | `RuleEvaluator` (safe expression eval via `simpleeval`), `WhenEvaluationError` (raised when a `when` clause cannot be evaluated). |
| `src/lucky_numbers/seeds.py` | `build_pool(rules, context)` — dispatch loop over all rule actions, returns weighted pool + audit. Logs evaluation failures as `when-skipped` / `when-error` audit entries. |
| `src/lucky_numbers/engine.py` | `generate(system, snapshot)` — orchestrates pool build, relationship injection, deterministic selection. Contains `_stable_pick` and `_seed_rank`. |
| `src/lucky_numbers/cli.py` | `lucky generate`, `lucky play`, `lucky show`, `lucky refresh`. Calls VedAstro for `data/snapshot.yaml`. |
| `ui/streamlit_app.py` | Web dashboard. Sidebar form for both persons + relationship; "Fetch VedAstro data" populates an in-memory Snapshot (transits, dasa, natal, numerology, relationship sky). |
| `scripts/build_win_day_*` | Re-build `rules/win_day_*.yaml` from historical jackpot-win CSVs + win-day sky JSONL. |
| `scripts/enrich_*` | Hit VedAstro to add planet positions to historical draw / win days. |
| `scripts/fetch_*` | Pull lottery draw + jackpot pot history. |
| `scripts/analyze_pots_and_wins.py` | Join pots + draws, extract jackpot-win days into `data/historical/analysis/`. |

---

## 3. The Snapshot — single source of truth

```python
Snapshot(
    self_   = Person,                   # Person 1 — main protagonist
    other   = Person | None,            # Person 2 (None for solo setups)
    transits = {                        # current sky relative to natal chart
        "self":  {planet_lower: {sign, house, kaksha, ashtaka, sarvashtaka}},
        "other": {planet_lower: {…}},
    },
    dasa = {                            # active Vimshottari periods
        "self":  {mahadasa, bhukti, antara},
        "other": {…},
    },
    relationship = RelationshipData(    # optional
        relation_type   = "Married|Relationship|Father-Son|…",
        event_date      = date,
        transits_on_date = {planet_lower: {sign, house, kaksha, …}},
    ),
)
```

When no second person is supplied, `Snapshot.as_context()` aliases `other`
to `self`, so rules that reference `other.*` evaluate cleanly even in solo
mode (they simply match Person 1).

`Snapshot.as_context()` flattens this into the dict that rule expressions
read by name (`self.birth.day`, `transits.self.jupiter.house`,
`dasa.other.mahadasa`, `relationship.transits_on_date`, `system`, …).

> **Backward compatibility.** The loader (`loader._normalise_subject_keys`,
> `loader.load_people`, `loader.load_snapshot`) and the UI cache reader
> automatically translate the legacy subject key `son` → `other` when
> reading older `data/people.yaml`, `data/snapshot.yaml`, or
> `~/.lucky-numbers/vedastro_cache.json` files. Newly written files always
> use `other`.

Each `Person` also carries:

- `birth.day / month / year / time / timezone / location / latitude / longitude`
- `numerology.{name, name_number, root_number, ruling_planet}` — populated by `numerology.chaldean_profile()` (UI) or the `lucky refresh --numerology` CLI command (writes `data/snapshot.yaml`).
- `natal.{lagna_sign, lagna_sign_index, lagna_lord, moon_sign, moon_house, sun_house, jupiter_house, …}` — populated by `vedastro_client.natal_chart()` in the UI flow, or hand-curated in `data/snapshot.yaml`.

---

## 4. Rule engine

### 4.1 File layout & load order

`loader.load_rule_files()` globs `rules/*.yaml` in **alphabetical filename
order** and concatenates every `seeds:` and `modifiers:` list into a single
ordered list of rule dicts. Each rule is tagged with `kind` (`seeds` or
`modifiers`) and `source_file` for the audit trail.

| File | Kind | What it contributes |
|---|---|---|
| `rules/base_seeds.yaml` | seeds | Person 1 birth/numerology/lagna/moon-house, a few Person 2 (`other_*`) seeds, Royal Star 23, Jupiter 3, self+other lagna axis. |
| `rules/combined.yaml` | modifiers | Joint Person 1 + Person 2 lagna axis, Jupiter blend, birthday sum. |
| `rules/dasa_modifiers.yaml` | modifiers | Person 1 mahadasa/bhukti/antara → planet harmonics. Person 2 (`other`) mahadasa + bhukti at lower weight. Saturn-Saturn drops 13. |
| `rules/transit_modifiers.yaml` | modifiers | Person 1's CURRENT transits vs natal: Jupiter‑10th, Venus‑9th, Mars+Saturn‑7th block, strongest-bindu planet boost, Jupiter house, Moon house. |
| `rules/win_day_bias.yaml` | modifiers | Always-on baseline boost of historical jackpot-win numbers. |
| `rules/win_day_astro_bias_loto6.yaml` | modifiers | Per-system: when today's `transits.self.<planet>.sign` matches a historically frequent jackpot-win sign, big boost. Plus `transits.other.<planet>.sign` variants at lower weight. |
| `rules/win_day_astro_bias_euromillions.yaml` | modifiers | Same shape as loto6, for EuroMillions. |

### 4.2 Rule schema

```yaml
- id: my_rule_id              # unique string, shown in audit
  when: "expression"          # optional; default "true"
  kind: seeds | modifiers     # auto-set from the YAML key
  weight: 1                   # integer, default 1
  reason: "human-readable"    # shown in audit
  action: seed | add | add_many | remove_range | weight_planet | weight_planet_strongest
  # action-specific keys:
  expr:    <int|str>          # for `seed`        — value to add
  value:   <int|str>          # for `add`         — value to add
  values:  [<int|str>, …]     # for `add_many`    — values to add
  low:     <int|str>          # for `remove_range`
  high:    <int|str>
  planet:  "<expr>"           # for `weight_planet` — yields a planet name
```

The `expression` syntax is a safe Python subset (via `simpleeval`) with full
attribute access on the context dict and the helpers `abs`, `min`, `max`,
`len`, `int`. Examples:

```yaml
when: "transits.self.jupiter.house == 10"
when: "system == 'loto6' and transits.other.mars.sign == 'Cancer'"
expr: "(self.natal.lagna_sign_index + other.natal.lagna_sign_index) % 50"
planet: "dasa.self.mahadasa"
```

### 4.3 Action semantics (in `seeds.build_pool`)

| Action | Effect on pool |
|---|---|
| `seed` | Eval `expr`, coerce to ints, `pool[n] += weight`. Skipped if `n` is in the blocked set. |
| `add` | Eval `value`, coerce to ints, same as `seed` (used in modifier files for symmetry). |
| `add_many` | For each item in `values`, eval and add. |
| `remove_range` | Eval `low`/`high`, add the integer range to `blocked` and pop from pool. |
| `weight_planet` | Eval `planet`, look up `PLANET_NUMBER[planet]`, add **all harmonics up to 50** (`p, 2p, 3p, …`) with `weight`. |
| `weight_planet_strongest` | Pick the strongest of `transits.self.*` (sort by `kaksha` then `ashtaka`), then same as `weight_planet`. |

### 4.4 `when` evaluation & visibility (audit)

- `RuleEvaluator.truthy_when` returns `True` / `False` for clean evaluations.
- If the expression refers to missing context (e.g. `transits.self.jupiter.house` when no transits were fetched), it raises `WhenEvaluationError`.
- `seeds.build_pool` catches that error and writes a `when-skipped` audit entry with the rule id, weight, and the reason text. Earlier this was silently swallowed; now `--explain` shows you *exactly* which rules dropped and why.

---

## 5. Direct relationship injection (engine-level, not a rule)

After `build_pool` returns, `engine.generate` performs one extra step before
selection:

```python
if snapshot.relationship and snapshot.relationship.transits_on_date:
    rel_pool_weight = 3
    for planet_raw in snapshot.relationship.transits_on_date:
        pn = PLANET_NUMBER[planet_raw.capitalize()]
        for n in range(pn, 51, pn):     # all harmonics up to 50
            pool[n] = pool.get(n, 0) + rel_pool_weight
```

This is intentionally hard-coded at weight 3 (smaller than the win-day signal
at weight 9, larger than ordinary natal seeds) so the relationship influences
the pool noticeably but cannot dominate.

The same relationship facts are also folded into the deterministic `seed`
string that controls tie-breaking and backfill.

---

## 6. Selection — `_stable_pick` and `_seed_rank`

```python
candidates.sort(key=lambda x: (-x[1], _seed_rank(seed, x[0]), x[0]))
```

Three-level sort key:

1. **`-weight`** — rule-driven importance always wins.
2. **`_seed_rank(seed, n)`** — SHA‑256 of `f"{seed}|{n}"`, gives equal-weight
   numbers a deterministic but **per-snapshot** order. This is the lever that
   makes two different Person 2's perturb the final pick even when both
   trigger the same set of dominant rules.
3. **`n`** — final fallback, guarantees full determinism.

The `seed` string includes:

```
{system}|dasa_self={…}|dasa_other={…}|t_self={…}|t_other={…}|rel_type={…}|rel_date={…}|rel_sky={…}
```

So a change to *any* part of the snapshot reshuffles equal-weight ties.

If after sorting the pool still doesn't supply enough numbers in `[lo, hi]`,
a SHA-256 of `seed + sorted(pool.items())` is used as a deterministic random
source for backfill.

---

## 7. The weight pyramid (effective influence)

This is the actual ranking that decides the pick. Higher rows dominate.

| Tier | Weight | Source | Whose data |
|---|---|---|---|
| 1 | **9** | `win_day_sign_match_<system>_<planet>_<sign>` | `transits.self` |
| 1b | **6** | `win_day_number_bias_top` (always-on baseline) | system-wide |
| 1c | **5** | `win_day_numbers_baseline_<system>` | system-wide |
| 2 | **4** | `jupiter_10th_blessing`, `venus_9th_luck`, `high_bindu_planet_boost`, `win_day_sign_match_<system>_other_<planet>_<sign>` | `transits.self` / `transits.other` |
| 3 | **3** | `mahadasa_lord_emphasis`, `royal_star_23`, `self_root_number`, **relationship-date planet harmonics** | Person 1 / relationship |
| 4 | **2** | `bhukti_lord_emphasis`, `other_mahadasa_emphasis`, `self_birth_day`, `self_lagna_index`, `other_birth_day`, `other_lagna_index`, `other_jupiter_house`, `birthday_sum`, `shared_lagna_axis`, `jupiter_house_number`, `self_other_axis`, `self_name_number_compound` | mixed |
| 5 | **1** | `antara_lord_emphasis`, `other_bhukti_emphasis`, `self_birth_month`, `other_birth_month`, `self_moon_house`, `moon_transit_house`, `jupiter_other_house_blend`, `jupiter_compound_3` | mixed |

**Design intent encoded in this pyramid:**

- The **biggest single signal** is the correlation between today's sky and historical jackpot-winning days.
- **Person 1** is the protagonist — almost every modifier rule reads `self.*`, `transits.self.*`, `dasa.self.*`.
- **Person 2** contributes both as a secondary win-day signature (weight 4) and through smaller seeds (weight 1–2). Combined: enough to perturb the final pick.
- **Relationship** is a fixed weight 3, so it nudges but cannot out-vote the win-day rules.

---

## 8. Determinism contract

| Property | Guarantee |
|---|---|
| Same Snapshot, same system | Identical `main` and `magic` arrays, every time. |
| Two snapshots differing only in Person 2 | Different Person 2 sky may flip a `win_day_sign_match_*_other_*` rule (weight 4) and changes `seed`, reshuffling all ties. Typically 1–3 of the picked numbers change. |
| Two snapshots differing only in relationship | Relationship-planet harmonics (weight 3) and `rel_seed` change. Typically 1–2 picked numbers shift. |
| Two snapshots differing only in current date | All `transits.*` rules re-evaluate; can flip multiple weight-9 win-day signatures. The pick can change a lot. |

---

## 9. Extending the system

### Add a new rule

Drop a YAML file into `rules/`. Example:

```yaml
# rules/my_custom.yaml
modifiers:
  - id: my_loto6_lucky_7
    when: "system == 'loto6' and self.natal.lagna_sign == 'Leo'"
    action: add
    value: 7
    weight: 5
    reason: "Custom: Leo ascendant on Loto6 boosts 7"
```

It is picked up automatically on the next `generate` (no code change).

### Add a new lottery system

Edit `configs/systems.yaml`:

```yaml
systems:
  my_lottery:
    description: "5 main numbers from 1 to 60"
    main:
      count: 5
      min: 1
      max: 60
```

System-specific rules can branch with `when: "system == 'my_lottery'"`.

### Add a new VedAstro fact

1. Add a wrapper to `vedastro_client.py` (or use `client.call("tool_name", {…})`).
2. Add a parser to `ui/streamlit_app.py` (`_normalise_*` helpers) and/or `cli.py` (`_unwrap` + `_normalize_*`).
3. Store it in the appropriate Snapshot field.
4. Reference it from a new rule via `when` / `expr`.

### Re-build win-day rules from fresh data

```bash
python scripts/fetch_lottery_history.py
python scripts/fetch_pot_history_win2day.py
python scripts/analyze_pots_and_wins.py
python scripts/enrich_jackpot_wins_with_vedastro.py --years 2
python scripts/build_win_day_bias_rules.py
python scripts/build_win_day_astro_rules.py
```

The astro rule generator emits both `_<planet>_<sign>` (weight 9, `transits.self`) and `_other_<planet>_<sign>` (weight 4, `transits.other`) variants per planet-sign signature.

---

## 10. Audit trail — reading `--explain` output

Each row in the audit corresponds to one rule firing or being skipped:

| Action column | Meaning |
|---|---|
| `seed` / `add` / `add_many` | Rule contributed numbers to the pool. `Numbers` = what was added; `W` = weight per number. |
| `remove_range` | Numbers were blocked (subtracted) from the pool. |
| `weight_planet` / `weight_planet_strongest` | Planet-harmonic boost applied. `Numbers` = the harmonics added. |
| `when-skipped` | Rule's `when` referenced a missing snapshot field (e.g. natal data not fetched yet). The reason explains which expression failed. |
| `when-error` | Rare runtime error during evaluation. |

If a rule does *not* appear in the audit at all, its `when` cleanly evaluated to `False` (the condition was simply not met). Anything that errored or was skipped due to missing data now shows up explicitly.

---

## 11. Caching

| Cache | Location | Key | Lifetime |
|---|---|---|---|
| Streamlit form state | `~/.lucky-numbers/form_state.json` | none | persistent |
| VedAstro per-person snapshot | `~/.lucky-numbers/vedastro_cache.json` | MD5 of `(p1_name + p1_dob + p1_loc + p2_name + p2_dob + p2_loc)` | last 10 entries |
| File-based snapshot | `data/snapshot.yaml` | none | overwritten by `lucky refresh` |

The per-person cache stores `transits`, `dasa`, `natal`, `numerology`, and `rel`, all keyed by subject (`self` / `other`). Old caches that still use the legacy `son` subject key are migrated transparently on read. Re-entering the same birth data on a later session bypasses every VedAstro call.

---

## 12. Disclaimer

This is symbolic & deterministic — useful for entertainment, audit-driven exploration of astrological seed systems, and a reproducible alternative to ad-hoc number-picking habits. **No system can predict random draws.**
