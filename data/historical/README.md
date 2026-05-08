# Historical lottery results (cached)

This folder contains cached draw histories so you can run experiments offline.

## Sources

- **EuroMillions**: `daowa89/lottery-archive` (mirrors win2day.at)
- **Austrian Lotto 6 aus 45**: `daowa89/lottery-archive` (mirrors win2day.at)

## Files

- `euromillions_results.csv`: full history (since 2004)
- `austria_lotto_6aus45_results.csv`: full history (since 1986)
- `euromillions/last_10_years.csv`: convenience subset
- `austria_lotto_6aus45/last_10_years.csv`: convenience subset

## Pots (jackpots)

Pot history (jackpot amount + whether the jackpot was won) is fetched from win2day exports:

- `pots/austria_lotto_6aus45_pots.csv`
- `pots/euromillions_pots.csv`

These are joined to the draw results by `date` in `analysis/*`.

## Analysis outputs

- `analysis/*_pots_joined.csv`: draw + pot + delta vs previous draw + numbers
- `analysis/*_jackpot_wins.csv`: only jackpot-win days (date + pot + numbers)

## Planet adjustments (VedAstro)

The `scripts/enrich_lottery_history_with_vedastro.py` script enriches recent draws with:

- **Dasa at time** for you + your son (historical, date-specific)
- A **current-sky context query** for the draw date/time (VedAstro semantic router)

Output is written as JSONL to:

- `planet_adjustments/euromillions_last_50_draws.jsonl`
- `planet_adjustments/austria_lotto_6aus45_last_50_draws.jsonl`

## Planet adjustments (VedAstro) — jackpot win days

Jackpot win days can be enriched separately (and cached incrementally):

- `planet_adjustments/win_days/austria_lotto_6aus45_jackpot_wins.jsonl`
- `planet_adjustments/win_days/euromillions_jackpot_wins.jsonl`


