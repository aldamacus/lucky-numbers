# lucky-numbers

Deterministic, auditable lottery-number generator driven by Vedic astrology,
Chaldean numerology, historical jackpot-win analysis and **moon phase patterns**.
Built around two people (father + son) and live planetary transits via the
[VedAstro](https://vedastro.org) MCP.

## Why deterministic?

Same inputs (birth data + current sky snapshot) → same numbers, every time.
Each number carries an audit trail: which rule put it in the pool and why.

## Systems

| Name | Format | Range |
|---|---|---|
| `loto6` | 6 main | 1–46 |
| `euromillions` | 5 main + 2 Lucky Stars | main 1–50, stars 1–12 |
| `eurojackpot` | 5 main + 2 magic | main 1–40, magic 1–10 |

Both are configurable in `configs/systems.yaml`.

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone https://github.com/aldamacus/lucky-numbers.git
cd lucky-numbers

# 2. Create a virtual environment and activate it
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate     # macOS / Linux

# 3. Install the package with all dependencies (including Streamlit)
pip install -e .

# 4. Set your VedAstro API key
copy .env.example .env
#    then open .env and set VEDASTRO_API_KEY=<your-key>
```

---

## ▶ Run locally

### Option A — Web UI (recommended)

```bash
# make sure you are on the UI branch
git checkout my_lucky_numbers
pip install -e .

# start the Streamlit dashboard
streamlit run ui/streamlit_app.py
```

Open **http://localhost:8501** in your browser.

### Option B — CLI only

```bash
# Refresh live planet snapshot from VedAstro
python -m lucky_numbers.cli refresh

# Generate EuroMillions numbers
python -m lucky_numbers.cli generate euromillions

# Generate Austrian Loto 6 numbers
python -m lucky_numbers.cli generate loto6

# Full pipeline: refresh + update history + rebuild rules + generate + score
python -m lucky_numbers.cli play euromillions

# Show what the current snapshot looks like
python -m lucky_numbers.cli show

# Run the weight backtester (finds the best rule weights from last 100 draws)
python scripts/backtest_euromillions.py --draws 100 --iterations 1000
```

---

## Web UI details (branch `my_lucky_numbers`)

| Panel | What it does |
|---|---|
| **Full pipeline (play)** | Refresh sky + moon phase → update draws/pots → rebuild all rules → generate → show win score |
| **Generate (offline)** | Generate numbers instantly from the last cached snapshot |
| **VedAstro refresh** | Pull fresh transits + dasa (or full numerology) from VedAstro |
| **Data & rules** | Download draw history, enrich win-days, rebuild bias rules, analyse moon phases |

The header shows the current moon phase (emoji + illumination %) live at all times.
Clicking any row in the jackpot-win tables shows the Chaldean planet ruler for each
winning number, plus the sky snapshot for that draw day (if enriched).

> The win-draw tables require files under `data/historical/analysis/`.
> On first run click **Update draws + pots + analysis** or run
> `python -m lucky_numbers.cli play loto6 --skip-history` once.

**Live deployment:** https://lucky-numbers-wo9yazltz74sarpugqs87x.streamlit.app/

---

## How the algorithm chooses numbers

The engine builds a `pool: {number → cumulative_weight}` by applying every rule in every
`rules/*.yaml` file in alphabetical order, then picks the highest-weighted numbers
deterministically (weight desc → number asc → SHA-256 fill).

### Weight pyramid

| Layer | Source | Max weight |
|---|---|---|
| **1 — Birth seeds** | Numerology root, birth day/month, lagna index, Jupiter house | 3 |
| **2 — Live transits** | Current planet house/sign from today's VedAstro snapshot | 4 |
| **3 — Dasa lords** | Active Mahadasa / Bhukti / Antara planet harmonics | 3 |
| **4 — Combined chart** | Father + son lagna axis blend, shared birthday sum | 2 |
| **5 — Win-day numbers** | Numbers that appeared most on historical jackpot-win days | 6 |
| **5 — Win-day astrology** | Today's planet-in-sign matches win-day sky signatures | 9 |
| **6 — Moon phase** | Today's lunar phase matches dominant win-day moon phases | **8** |

Numbers accumulate weights across layers — a number matching the win-day baseline
**and** two transit-sign rules **and** the moon phase can reach a combined weight of
5 + 9 + 9 + 8 = **31**, making it nearly certain to be picked.

### Layer 1 — Birth seeds (`rules/base_seeds.yaml`)

Static numbers derived from birth data; never change once set.

| Rule | What it contributes | Weight |
|---|---|---|
| `self_root_number` | Person 1 Chaldean root number | 3 |
| `self_name_number_compound` | Person 1 full-name compound | 2 |
| `self_birth_day` / `self_birth_month` | Person 1 birth day / month | 2 / 1 |
| `self_lagna_index` | Person 1 rising-sign index (1–12) | 2 |
| `other_birth_day` / `other_birth_month` | Person 2 birth day / month | 2 / 1 |
| `other_lagna_index` | Person 2 rising-sign index | 2 |
| `other_jupiter_house` | Person 2 natal Jupiter house | 2 |
| `royal_star_23` | Number 23 — "Royal Star of the Lion" | 3 |

### Layer 2 — Live transit modifiers (`rules/transit_modifiers.yaml`)

Fire based on the VedAstro snapshot refreshed by `lucky refresh`.

| Rule | Condition | Weight |
|---|---|---|
| `jupiter_10th_blessing` | Jupiter transiting house 10 | 4 |
| `venus_9th_luck` | Venus in house 9 + kaksha ≥ 1 | 4 |
| `high_bindu_planet_boost` | always — boost the strongest planet's harmonics | varies |
| `jupiter_house_number` | always — add Jupiter's current house index | 2 |
| `moon_transit_house` | always — add Moon's current house index | 1 |
| `mars_saturn_7th_caution` | Mars + Saturn both in house 7 | **removes** 21–28 |

### Layer 3 — Dasa modifiers (`rules/dasa_modifiers.yaml`)

Vimshottari period lords whose number harmonics (multiples up to 50) are boosted.

| Rule | Planet | Weight |
|---|---|---|
| `mahadasa_lord_emphasis` | Person 1 Mahadasa | 3 |
| `bhukti_lord_emphasis` | Person 1 Bhukti | 2 |
| `antara_lord_emphasis` | Person 1 Antara | 1 |
| `other_mahadasa_emphasis` | Person 2 Mahadasa | 2 |
| `other_bhukti_emphasis` | Person 2 Bhukti | 1 |

### Layer 4 — Combined chart (`rules/combined.yaml`)

Both persons' natal data used jointly.

| Rule | Weight |
|---|---|
| `shared_lagna_axis` — sum of both rising signs | 2 |
| `jupiter_other_house_blend` — combined Jupiter houses mod 50 | 1 |
| `birthday_sum` — sum of both birth days mod 50 | 2 |

### Layer 5 — Win-day bias (`rules/win_day_bias.yaml` + `win_day_astro_bias_*.yaml`)

Built automatically from historical jackpot-win data.

| Rule group | Weight |
|---|---|
| `win_day_number_bias_top` — always-on global baseline | 6 |
| `win_day_numbers_baseline_loto6` / `_euromillions` — system baseline | 5 |
| `win_day_sign_match_*` — planet-in-sign match (Person 1) | 9 |
| `win_day_sign_match_other_*` — planet-in-sign match (Person 2) | 4 |

### Layer 6 — Moon phase bias (`rules/moon_phase_bias_*.yaml`) ← NEW

The lunar cycle (~29.5 days) is independent of the weekly draw schedule, so some phases
appear more often among historical jackpot wins than chance predicts.
The algorithm measures this from all available draw data, then boosts win-day numbers
when today's phase matches the historically dominant ones.

**Findings from real data:**

| Game | Top phases (observed vs 12.5% expected) |
|---|---|
| AT Lotto 6/45 — 357 wins | Waxing Crescent **13.7%** (+1.2%), Waxing Gibbous **13.4%** (+0.9%), New Moon & First Quarter **13.2%** (+0.7%) |
| EuroMillions — 163 wins | **Last Quarter 16.6%** (+4.1%), First Quarter **15.3%** (+2.8%), Full Moon **14.7%** (+2.2%) |

Weight bands applied automatically:

| Excess above expected | Weight |
|---|---|
| > 3.0 % | **8** (strong signal) |
| > 1.5 % | **6** (moderate) |
| > 0.0 % | **4** (weak) |

The moon phase is computed locally (no API call) using the known new-moon epoch
(2000-01-06 18:14 UTC) and the mean synodic period (29.530588 days).
It is written into `data/snapshot.yaml` on every `lucky refresh` and is visible
in the UI header and after every generate/play run.

---

## API Key (VedAstro)

```bash
copy .env.example .env
# then edit .env and set VEDASTRO_API_KEY=your-real-key
```

Resolution order: explicit arg → `VEDASTRO_API_KEY` env var → `.env` file.

---

## Usage

```bash
# Generate using cached snapshot (offline, fast, reproducible)
python -m lucky_numbers.cli generate loto6
python -m lucky_numbers.cli generate euromillions

# Show full audit trail (which rule added which number at what weight)
python -m lucky_numbers.cli generate loto6 --explain

# Refresh live transit + dasa + moon phase from VedAstro
python -m lucky_numbers.cli refresh
python -m lucky_numbers.cli refresh --numerology   # also recompute name numerology

# Full pipeline in one command
python -m lucky_numbers.cli play loto6 --win-years 1
python -m lucky_numbers.cli play euromillions --win-years 1

# Show snapshot summary
python -m lucky_numbers.cli show
```

---

## Data pipeline (step by step)

```bash
# 1. Fetch draw history (winning numbers)
python scripts/fetch_lottery_history.py

# 2. Fetch pot/jackpot history (amount + "won?")
python scripts/fetch_pot_history_win2day.py

# 3. Join pots + results, extract jackpot win-days
python scripts/analyze_pots_and_wins.py

# 4. Enrich win-days with VedAstro sky data (planet signs on each win date)
python scripts/enrich_jackpot_wins_with_vedastro.py

# 5. Build win-day number + astrology bias rules
python scripts/build_win_day_bias_rules.py
python scripts/build_win_day_astro_rules.py

# 6. Analyse moon phases on win-days → build moon-phase rules  ← NEW
python scripts/analyze_moon_phases_on_wins.py
python scripts/build_moon_phase_rules.py

# 7. Generate with audit trail
python -m lucky_numbers.cli generate loto6 --explain
python -m lucky_numbers.cli generate euromillions --explain
```

`lucky play` runs all of the above automatically.

---

## Project layout

```
lucky-numbers/
├── configs/systems.yaml            # game definitions
├── data/
│   ├── people.yaml                 # birth records (gitignored after first edit)
│   ├── snapshot.yaml               # cached VedAstro chart + transit + moon-phase facts
│   └── historical/
│       ├── analysis/
│       │   ├── *_jackpot_wins.csv          # jackpot-win rows per game
│       │   ├── *_pots_joined.csv           # all draws with pot info
│       │   └── moon_phase_win_stats.json   # moon phase frequency on win days
│       ├── pots/                           # raw pot history CSVs
│       └── planet_adjustments/win_days/    # enriched sky JSONL per win day
├── rules/
│   ├── base_seeds.yaml                     # static birth-derived seeds
│   ├── transit_modifiers.yaml              # live-sky transit rules
│   ├── dasa_modifiers.yaml                 # Vimshottari period rules
│   ├── combined.yaml                       # father+son combined rules
│   ├── win_day_bias.yaml                   # win-day number baseline
│   ├── win_day_astro_bias_loto6.yaml       # planet-sign bias (loto6)
│   ├── win_day_astro_bias_euromillions.yaml
│   ├── moon_phase_bias_loto6.yaml          # moon phase bias (loto6)  ← NEW
│   └── moon_phase_bias_euromillions.yaml   # moon phase bias (euromillions)  ← NEW
├── src/lucky_numbers/
│   ├── models.py
│   ├── loader.py
│   ├── seeds.py
│   ├── rules.py
│   ├── engine.py
│   ├── moon_phase.py               # pure-Python synodic calculator  ← NEW
│   ├── vedastro_client.py
│   └── cli.py
├── scripts/
│   ├── fetch_lottery_history.py
│   ├── fetch_pot_history_win2day.py
│   ├── analyze_pots_and_wins.py
│   ├── enrich_lottery_history_with_vedastro.py
│   ├── enrich_jackpot_wins_with_vedastro.py
│   ├── build_win_day_bias_rules.py
│   ├── build_win_day_astro_rules.py
│   ├── analyze_moon_phases_on_wins.py      # ← NEW
│   └── build_moon_phase_rules.py           # ← NEW
├── ui/
│   └── streamlit_app.py            # Streamlit dashboard
└── tests/
```

---

## Adding a rule

Edit any file in `rules/`. Each rule:

```yaml
- id: jupiter_10th_boost
  when: "transits.self.jupiter.house == 10"
  action: add
  value: 3
  weight: 4
  reason: "Jupiter in 10th — career/expansion blessing"
```

Available actions: `add`, `add_many`, `remove_range`, `weight_planet`, `weight_planet_strongest`.

### System-specific rules

```yaml
- id: only_for_loto6
  when: "system == 'loto6'"
  action: add
  value: 23
  weight: 2
  reason: "Only apply to loto6"
```

### Moon-phase rules

```yaml
- id: moon_phase_full_euromillions
  when: "system == 'euromillions' and moon_phase.phase == 'Full Moon'"
  action: add_many
  values: [7, 3, 8, 4, 12, 5, 11, 9, 6, 17, 2, 10, 1, 42, 44, 33, 25, 27]
  weight: 6
  reason: "Full Moon appeared on 14.7% of EuroMillions jackpot-win days (vs 12.5% expected)"
```

The `moon_phase` context object exposes `moon_phase.phase` (string), `moon_phase.illumination`
(0.0–1.0), and `moon_phase.age_days` (float).

---

## Top-down data flow

```
UI form / people.yaml
     ↓
VedAstro fetch (transits + dasa per person) + local moon-phase calculation
     ↓
Snapshot { self_, other, transits, dasa, natal, numerology, moon_phase }
     ↓
Rule engine (build_pool)  ── reads rules/*.yaml → weighted pool {number: weight}
     ↓
_stable_pick(pool, count, lo, hi, seed)   — sort: weight desc → number asc → SHA-256 fill
     ↓
main + magic numbers   (with full audit trail)
```

---

## Disclaimer

For entertainment and symbolic exploration. No system can predict random draws.

## Documentation

- [Technical documentation](./TECHNICAL.md) — full algorithm, rule engine, weight pyramid, determinism contract, extension points
- [VedAstro API Guide](./VedAstro-API-Guide.md)
