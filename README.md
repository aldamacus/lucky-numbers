# lucky-numbers

Deterministic, auditable lottery-number generator driven by Vedic astrology
and Chaldean numerology. Built around two people (father + son) and live
planetary transits via the [VedAstro](https://vedastro.org) MCP.

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

## Web UI (branch `my_lucky_numbers`)

A **Streamlit** dashboard lets you view the latest 10 jackpot-win draws and
run every pipeline command from the browser — no terminal needed.

```bash
# Make sure you are on the right branch and dependencies are installed
git checkout my_lucky_numbers
pip install -e .

# Start the dashboard
streamlit run ui/streamlit_app.py
```

Open the URL Streamlit prints — usually **http://localhost:8501**.

The dashboard has four command panels:

| Panel | What it does |
|---|---|
| **Full pipeline (play)** | Refresh sky → update draws/pots → rebuild rules → generate → show win score |
| **Generate (offline)** | Generate numbers instantly from the last cached snapshot |
| **VedAstro refresh** | Pull fresh transits + dasa (or full numerology) from VedAstro |
| **Data & rules** | Download draw history, enrich win-days with VedAstro, rebuild bias rules |

> The win-draw tables require files under `data/historical/analysis/`.
> On first run click **Update draws + pots + analysis** or run
> `python -m lucky_numbers.cli play loto6 --skip-history` once.

## API Key (VedAstro)

The `lucky refresh` command calls the VedAstro public MCP and needs your
developer API key.

```bash
copy .env.example .env
# then edit .env and set VEDASTRO_API_KEY=your-real-key
```

Resolution order: explicit arg → `VEDASTRO_API_KEY` env var → `.env` file.
The `.env` file is gitignored.

## Usage

```bash
# Generate using cached snapshot (offline, fast, reproducible)
python -m lucky_numbers.cli show

python -m lucky_numbers.cli generate loto6
python -m lucky_numbers.cli generate euromillions
python -m lucky_numbers.cli generate eurojackpot

# Refresh live transit data from VedAstro
python -m lucky_numbers.cli refresh                            # transits + dasa
python -m lucky_numbers.cli refresh --numerology               # also recompute name numerology
python -m lucky_numbers.cli refresh --no-dasa --transits       # transits only

# Show full audit trail
python -m lucky_numbers.cli generate loto6 --explain
```

## Project layout

```
lucky-numbers/
├── configs/systems.yaml        # game definitions
├── data/
│   ├── people.yaml             # birth records (gitignored after first edit)
│   └── snapshot.yaml           # cached chart + transit facts
├── rules/
│   ├── base_seeds.yaml         # static seed numbers
│   ├── transit_modifiers.yaml  # live-sky modifiers
│   ├── dasa_modifiers.yaml     # active period modifiers
│   └── combined.yaml           # father+son chart blend
│   ├── win_day_bias.yaml               # win-day numbers bias (higher importance)
│   ├── win_day_astro_bias_loto6.yaml   # win-day astrology bias (loto6)
│   └── win_day_astro_bias_euromillions.yaml # win-day astrology bias (euromillions)
├── src/lucky_numbers/
│   ├── models.py
│   ├── loader.py
│   ├── seeds.py
│   ├── rules.py
│   ├── engine.py
│   ├── vedastro_client.py
│   └── cli.py
└── scripts/
    ├── fetch_lottery_history.py
    ├── fetch_pot_history_win2day.py
    ├── analyze_pots_and_wins.py
    ├── enrich_lottery_history_with_vedastro.py
    ├── enrich_jackpot_wins_with_vedastro.py
    ├── build_win_day_bias_rules.py
    └── build_win_day_astro_rules.py
└── tests/
```

## Pipeline

```
people.yaml + snapshot.yaml ──► seeds (deterministic)
                                  │
rules/*.yaml  ──► rule engine ────┤
                                  ▼
                          normalized pool
                                  │
                          system constraints
                                  ▼
                       final numbers + audit
```

## Win-day analysis + astrology bias (higher importance)

This repo can ingest historical draw data and **upweight jackpot win-days** so they influence the pool more than ordinary draws.

- **Pots (jackpots)** are fetched from win2day exports and joined to draw results by date.
- **Jackpot win-days** (where the pot was won) are extracted as a separate dataset.
- Win-days are enriched with **VedAstro sky data** for that draw date/time.
- From that, the project generates **system-specific rules** that strongly boost win-day numbers,
  and boost them even more when today’s transits match common win-day planet-sign patterns.

Typical workflow:

```bash
# One-command run (refresh today + catch up draws/pots + rebuild win-day rules + generate + score)
python -m lucky_numbers.cli play loto6 --win-years 1
python -m lucky_numbers.cli play euromillions --win-years 1

# 1) Fetch draw history (numbers)
python scripts/fetch_lottery_history.py

# 2) Fetch pot/jackpot history (amount + "won?")
python scripts/fetch_pot_history_win2day.py

# 3) Join pots+results and extract jackpot win-days
python scripts/analyze_pots_and_wins.py

# 4) Enrich win-days with VedAstro (per game)
python scripts/enrich_jackpot_wins_with_vedastro.py

# 5) Build rules from win-day numbers + win-day astrology signatures
python scripts/build_win_day_bias_rules.py
python scripts/build_win_day_astro_rules.py

# 6) Generate with audit trail
python -m lucky_numbers.cli generate loto6 --explain
python -m lucky_numbers.cli generate euromillions --explain
```

## Adding a rule

Edit any file in `rules/`. Each rule:

```yaml
- id: jupiter_10th_boost
  when: "transit.jupiter.house == 10"
  action: add
  value: 3
  reason: "Jupiter in 10th — career/expansion blessing"
```

Available actions: `add`, `add_many`, `remove_range`, `weight_planet`, `weight_planet_strongest`.

### System-specific rules

The rule context includes a `system` value. You can branch rules like:

```yaml
- id: only_for_loto6
  when: "system == 'loto6'"
  action: add
  value: 23
  weight: 2
  reason: "Only apply to loto6"
```

## Disclaimer
For entertainment & symbolic exploration. No system can predict random draws.

## VedAstro docs
- [VedAstro API Guide](./VedAstro-API-Guide.md)