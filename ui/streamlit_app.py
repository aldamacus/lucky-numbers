"""
Lucky Numbers — Streamlit dashboard.

Shows the latest 10 jackpot-win draws for AT Lotto 6/45 and EuroMillions,
and lets you run every CLI command (play, refresh, generate, data update)
from the browser.

Run from the repo root (after `pip install -e .`):
    streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "historical" / "analysis"
AT_WINS = ANALYSIS / "austria_lotto_6aus45_jackpot_wins.csv"
EU_WINS = ANALYSIS / "euromillions_jackpot_wins.csv"
SNAPSHOT = ROOT / "data" / "snapshot.yaml"


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_last_wins(path: Path, n: int = 10) -> pd.DataFrame:
    """Return the most-recent n jackpot-win rows, sorted newest first."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty or "date" not in df.columns:
        return df
    df = df.copy()
    df["_sort"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("_sort", ascending=False).head(n).drop(columns=["_sort"])
    return df.reset_index(drop=True)


def _run_cli(args: list[str], timeout: int = 600) -> str:
    """Invoke `python -m lucky_numbers.cli <args>` and return combined output."""
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    cmd = [sys.executable, "-m", "lucky_numbers.cli", *args]
    try:
        r = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Timeout after {timeout}s"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    combined = out + ("\n" + err if err else "")
    if r.returncode != 0:
        combined += f"\n\n[exit {r.returncode}]"
    return combined or "(no output)"


def _run_script(rel: str, extra: list[str] | None = None) -> str:
    """Invoke a repo script directly and return combined output."""
    path = (ROOT / rel).resolve()
    if not path.exists():
        return f"Script not found: {path}"
    cmd = [sys.executable, str(path)] + (extra or [])
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    try:
        r = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True,
            timeout=600, env=env,
        )
    except Exception as exc:
        return str(exc)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    combined = out + ("\n" + err if err else "")
    if r.returncode != 0:
        combined += f"\n\n[exit {r.returncode}]"
    return combined or "(no output)"


def _snapshot_age() -> str:
    try:
        import yaml
        snap = yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8"))
        ts = snap.get("generated_at", "unknown")
        return str(ts)
    except Exception:
        return "unknown"


# ── page layout ───────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="Lucky Numbers", page_icon="🍀", layout="wide")

    st.title("Lucky Numbers — Dashboard")
    st.caption(
        f"Repo: `{ROOT}`   |   "
        f"VedAstro snapshot: `{_snapshot_age()}`   |   "
        f"Loaded: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )

    # ── last 10 jackpot wins ─────────────────────────────────────────────────
    st.header("Last 10 jackpot-win draws")
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("AT Lotto 6/45")
        df_at = _load_last_wins(AT_WINS)
        if df_at.empty:
            st.info("No data. Run **Update draws + pots** first.")
        else:
            st.dataframe(df_at, use_container_width=True, hide_index=True)

    with col_b:
        st.subheader("EuroMillions")
        df_eu = _load_last_wins(EU_WINS)
        if df_eu.empty:
            st.info("No data. Run **Update draws + pots** first.")
        else:
            st.dataframe(df_eu, use_container_width=True, hide_index=True)

    if st.button("Reload tables from disk"):
        st.rerun()

    # ── commands ─────────────────────────────────────────────────────────────
    st.divider()
    st.header("Run commands")

    win_years = st.number_input(
        "Play: years of win-day astrology to enrich",
        min_value=1, max_value=10, value=1,
        help="How many recent years of jackpot-win days to pull from VedAstro.",
    )

    c1, c2, c3, c4 = st.columns(4)

    # --- play (full pipeline) ------------------------------------------------
    with c1:
        st.markdown("**Full pipeline (play)**")
        if st.button("▶ Play Loto6", type="primary", use_container_width=True):
            with st.spinner("Running full play for loto6 (may take a few minutes)…"):
                out = _run_cli(["play", "loto6", "--win-years", str(int(win_years))])
            st.success("Done")
            st.code(out)
        if st.button("▶ Play EuroMillions", use_container_width=True):
            with st.spinner("Running full play for euromillions…"):
                out = _run_cli(["play", "euromillions", "--win-years", str(int(win_years))])
            st.success("Done")
            st.code(out)

    # --- generate (offline, fast) --------------------------------------------
    with c2:
        st.markdown("**Generate (offline)**")
        if st.button("Generate Loto6", use_container_width=True):
            out = _run_cli(["generate", "loto6"])
            st.code(out)
        if st.button("Generate Euromillions", use_container_width=True):
            out = _run_cli(["generate", "euromillions"])
            st.code(out)
        if st.button("Generate + Audit trail (loto6)", use_container_width=True):
            out = _run_cli(["generate", "loto6", "--explain"])
            st.code(out)

    # --- VedAstro refresh ----------------------------------------------------
    with c3:
        st.markdown("**VedAstro refresh**")
        if st.button("Refresh snapshot (transits+dasa)", use_container_width=True):
            with st.spinner("Calling VedAstro…"):
                out = _run_cli(["refresh"])
            st.code(out)
        if st.button("Refresh + numerology", use_container_width=True):
            with st.spinner("Calling VedAstro…"):
                out = _run_cli(["refresh", "--numerology"])
            st.code(out)
        if st.button("Show snapshot summary", use_container_width=True):
            st.code(_run_cli(["show"]))

    # --- data pipeline -------------------------------------------------------
    with c4:
        st.markdown("**Data & rules**")
        if st.button("Update draws + pots + analysis", use_container_width=True):
            with st.spinner("Downloading CSVs…"):
                o1 = _run_script("scripts/fetch_lottery_history.py")
                o2 = _run_script("scripts/fetch_pot_history_win2day.py")
                o3 = _run_script("scripts/analyze_pots_and_wins.py")
            st.code(o1 + "\n---\n" + o2 + "\n---\n" + o3)
        if st.button("Enrich win-days (VedAstro)", use_container_width=True):
            with st.spinner("Calling VedAstro for win days…"):
                out = _run_script(
                    "scripts/enrich_jackpot_wins_with_vedastro.py",
                    extra=["--years", str(int(win_years))],
                )
            st.code(out)
        if st.button("Rebuild win-day bias rules", use_container_width=True):
            o1 = _run_script("scripts/build_win_day_bias_rules.py")
            o2 = _run_script("scripts/build_win_day_astro_rules.py")
            st.code(o1 + "\n---\n" + o2)


if __name__ == "__main__":
    main()
