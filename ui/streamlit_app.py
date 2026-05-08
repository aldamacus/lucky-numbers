"""
Lucky Numbers — Streamlit dashboard.

Shows the latest 10 jackpot-win draws for AT Lotto 6/45 and EuroMillions,
with per-row planet-alignment detail and a rich visual breakdown after every
play/generate run.

Run from the repo root (after `pip install -e .`):
    streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ANALYSIS    = ROOT / "data" / "historical" / "analysis"
WIN_DAYS    = ROOT / "data" / "historical" / "planet_adjustments" / "win_days"
AT_WINS     = ANALYSIS / "austria_lotto_6aus45_jackpot_wins.csv"
EU_WINS     = ANALYSIS / "euromillions_jackpot_wins.csv"
AT_SKY_JSONL = WIN_DAYS / "austria_lotto_6aus45_jackpot_wins.jsonl"
EU_SKY_JSONL = WIN_DAYS / "euromillions_jackpot_wins.jsonl"
SNAPSHOT    = ROOT / "data" / "snapshot.yaml"

# ── Chaldean & astrology knowledge tables ─────────────────────────────────────

# Chaldean system: root digit → ruling planet
_CHALDEAN: dict[int, str] = {
    1: "Sun", 2: "Moon", 3: "Jupiter", 4: "Rahu",
    5: "Mercury", 6: "Venus", 7: "Ketu", 8: "Saturn", 9: "Mars",
}

PLANET_EMOJI: dict[str, str] = {
    "Sun": "☀️", "Moon": "🌙", "Jupiter": "♃", "Venus": "♀️",
    "Mercury": "☿", "Saturn": "♄", "Mars": "♂️", "Rahu": "☊", "Ketu": "☋",
}

PLANET_MEANINGS: dict[str, str] = {
    "Sun":     "Vitality, authority, soul purpose — leadership number",
    "Moon":    "Intuition, mind, emotional flow — fortune through feelings",
    "Jupiter": "Luck, expansion, blessings — the most auspicious planet",
    "Venus":   "Wealth, pleasure, material harmony — comfort & luxury",
    "Mercury": "Intellect, communication, speed — analytical edge",
    "Saturn":  "Karma, discipline, long-term reward — perseverance pays",
    "Mars":    "Courage, action, competitive drive — bold initiative",
    "Rahu":    "Ambition, foreign luck, hidden desires — unexpected gains",
    "Ketu":    "Spiritual insight, sudden events — karmic wildcard",
}

SIGN_QUALITY: dict[str, str] = {
    "Aries": "🔥 Fire — energy & new beginnings",
    "Taurus": "🌍 Earth — stability & material gain",
    "Gemini": "💨 Air — duality & quick change",
    "Cancer": "💧 Water — intuition & emotional depth",
    "Leo": "🔥 Fire — courage & leadership luck",
    "Virgo": "🌍 Earth — precision & service",
    "Libra": "💨 Air — balance & partnership",
    "Scorpio": "💧 Water — transformation & hidden power",
    "Sagittarius": "🔥 Fire — expansion & optimism",
    "Capricorn": "🌍 Earth — achievement & karma",
    "Aquarius": "💨 Air — innovation & higher mind",
    "Pisces": "💧 Water — spirituality & sacrifice",
}

# House meanings (condensed for tooltips)
HOUSE_MEANINGS: dict[int, str] = {
    1: "self/body", 2: "wealth", 3: "courage/short travel", 4: "home/mother",
    5: "children/creativity", 6: "enemies/health", 7: "partnerships",
    8: "transformation/longevity", 9: "luck/dharma", 10: "career/status",
    11: "gains/network", 12: "loss/liberation",
}


# ── helper functions ──────────────────────────────────────────────────────────

def _root(n: int) -> int:
    """Chaldean digit-sum until single digit; 0 wraps to 9."""
    while n >= 10:
        n = sum(int(d) for d in str(n))
    return n or 9


def _planet(n: int) -> str:
    return _CHALDEAN.get(_root(n), "Unknown")


def _load_snapshot() -> dict[str, Any]:
    try:
        return yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _snapshot_age() -> str:
    snap = _load_snapshot()
    return str(snap.get("generated_at", "unknown"))


def _load_last_wins(path: Path, n: int = 10) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty or "date" not in df.columns:
        return df
    df = df.copy()
    df["_sort"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("_sort", ascending=False).head(n).drop(columns=["_sort"])
    return df.reset_index(drop=True)


def _load_sky_index(jsonl: Path) -> dict[str, dict]:
    """Return {date_iso: full_record} from an enriched JSONL file."""
    if not jsonl.exists():
        return {}
    out: dict[str, dict] = {}
    for line in jsonl.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(line)
            if d := obj.get("date"):
                out[d] = obj
        except Exception:
            continue
    return out


def _sky_planet_lines(sky_record: dict) -> list[str]:
    """Extract human-readable planet sign lines from a sky record."""
    sky = sky_record.get("sky", {})
    lines: list[str] = []

    # Format 1: flat dict with planet keys
    for p in ("sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn", "rahu", "ketu"):
        entry = sky.get(p) or sky.get(p.capitalize())
        if isinstance(entry, dict):
            sign = entry.get("sign") or entry.get("Sign", "?")
            house = entry.get("house") or entry.get("House", "?")
            emoji = PLANET_EMOJI.get(p.capitalize(), "")
            h_meaning = HOUSE_MEANINGS.get(int(house), "") if str(house).isdigit() else ""
            lines.append(f"{emoji} **{p.capitalize()}** in **{sign}** (house {house} — {h_meaning})")

    # Format 2: nested "Planets" key
    if not lines and isinstance(sky.get("Planets"), dict):
        for name, data in sky["Planets"].items():
            sign = data.get("Sign", "?")
            emoji = PLANET_EMOJI.get(name, "")
            lines.append(f"{emoji} **{name}** in **{sign}**")

    # Fallback: show raw text snippet
    if not lines:
        raw = json.dumps(sky, ensure_ascii=False)[:400]
        if raw and raw != "{}":
            lines.append(f"_Raw sky data:_ `{raw}`")

    return lines


def _numbers_from_row(row: pd.Series) -> list[int]:
    """Parse the 'numbers' string '3 7 12 24 39 40' → [3, 7, 12, 24, 39, 40]."""
    raw = str(row.get("numbers", ""))
    return [int(x) for x in re.findall(r"\d+", raw)]


def _run_cli(args: list[str], timeout: int = 600) -> str:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    cmd = [sys.executable, "-m", "lucky_numbers.cli", *args]
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                           text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return f"Timeout after {timeout}s"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    combined = out + ("\n" + err if err else "")
    if r.returncode != 0:
        combined += f"\n\n[exit {r.returncode}]"
    return combined or "(no output)"


def _run_script(rel: str, extra: list[str] | None = None) -> str:
    path = (ROOT / rel).resolve()
    if not path.exists():
        return f"Script not found: {path}"
    cmd = [sys.executable, str(path)] + (extra or [])
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                           text=True, timeout=600, env=env)
    except Exception as exc:
        return str(exc)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    combined = out + ("\n" + err if err else "")
    if r.returncode != 0:
        combined += f"\n\n[exit {r.returncode}]"
    return combined or "(no output)"


def _parse_numbers(text: str) -> tuple[list[int], list[int]]:
    """Extract main + magic numbers from stripped CLI output."""
    main: list[int] = []
    magic: list[int] = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"main\s*:", s, re.I):
            main = [int(x) for x in re.findall(r"\b\d{1,2}\b", s.split(":", 1)[1])]
        elif re.match(r"magic\s*:", s, re.I) or re.match(r"lucky.?stars?\s*:", s, re.I):
            magic = [int(x) for x in re.findall(r"\b\d{1,2}\b", s.split(":", 1)[1])]
    return main, magic


def _parse_score(text: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    m = re.search(r"Win-day match score:\s*(\d+)/100", text)
    if m:
        score = int(m.group(1))
    in_reasons = False
    for line in text.splitlines():
        s = line.strip()
        if "win-day match score" in s.lower():
            in_reasons = True
            continue
        if in_reasons and s.startswith("- "):
            reasons.append(s[2:])
    return score, reasons


# ── UI components ─────────────────────────────────────────────────────────────

def _render_win_table(game_label: str, df: pd.DataFrame, sky_index: dict) -> None:
    """Render win-draw table with clickable row → planet detail panel."""
    if df.empty:
        st.info("No data. Run **Update draws + pots + analysis** first.")
        return

    st.caption(
        f"Planet data available for {len(sky_index)} dates"
        if sky_index else
        "Run **Enrich win-days (VedAstro)** to unlock planet-alignment detail."
    )

    event = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"tbl_{game_label}",
    )

    selected = event.selection.rows if hasattr(event, "selection") else []
    if not selected:
        st.caption("↑ Click any row to see planet alignment for that draw date.")
        return

    row = df.iloc[selected[0]]
    date_iso = str(row.get("date", ""))
    jackpot = row.get("jackpot_eur", "?")
    numbers = _numbers_from_row(row)

    st.markdown(f"#### {date_iso}  —  jackpot {jackpot:,.0f} €" if isinstance(jackpot, (int, float))
                else f"#### {date_iso}")

    # Number breakdown (Chaldean planet for each winning number)
    st.markdown("**Winning numbers — Chaldean planet ruler:**")
    cols = st.columns(len(numbers)) if numbers else []
    for i, num in enumerate(numbers):
        pl = _planet(num)
        em = PLANET_EMOJI.get(pl, "")
        with cols[i]:
            st.metric(label=f"{em} {pl}", value=num,
                      help=PLANET_MEANINGS.get(pl, ""))

    # Planet positions on that draw day (if enriched data is available)
    sky_rec = sky_index.get(date_iso)
    if sky_rec:
        planet_lines = _sky_planet_lines(sky_rec)
        if planet_lines:
            with st.expander("🌌 Planet positions on draw day", expanded=True):
                for ln in planet_lines:
                    st.markdown(ln)
    else:
        st.info("No sky snapshot for this date. Run **Enrich win-days (VedAstro)** to add it.")


def _render_planet_table(snap: dict) -> None:
    """Render a compact current-transits table from snapshot."""
    transits = snap.get("transits", {}).get("self", {})
    if not transits:
        st.info("Snapshot has no transit data. Run **Refresh snapshot** first.")
        return

    rows = []
    for planet in ("sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn"):
        t = transits.get(planet, {})
        sign = t.get("sign", "—")
        house = t.get("house", "—")
        score = t.get("ashtaka", "—")
        quality = SIGN_QUALITY.get(sign, "")
        h_meaning = HOUSE_MEANINGS.get(house, "") if isinstance(house, int) else ""
        rows.append({
            "Planet": f"{PLANET_EMOJI.get(planet.capitalize(), '')} {planet.capitalize()}",
            "Sign": sign,
            "Sign quality": quality,
            "House": house,
            "House meaning": h_meaning,
            "Ashtaka score": score,
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_number_cards(
    main: list[int],
    magic: list[int],
    system: str,
    snap: dict,
) -> None:
    """Visual breakdown: each generated number with its astrological meaning."""
    if not main:
        return

    transits = snap.get("transits", {}).get("self", {})
    dasa = snap.get("dasa", {}).get("self", {})

    st.markdown("### Generated numbers — astrological reading")

    # ---- main numbers -------------------------------------------------------
    st.markdown(f"**Main numbers** ({len(main)} picks)")
    cols = st.columns(len(main))
    for i, num in enumerate(main):
        pl = _planet(num)
        root = _root(num)
        em = PLANET_EMOJI.get(pl, "")
        t = transits.get(pl.lower(), {})
        sign = t.get("sign", "—")
        house = t.get("house", "—")
        sign_q = SIGN_QUALITY.get(sign, "")
        h_meaning = HOUSE_MEANINGS.get(house, "") if isinstance(house, int) else ""
        with cols[i]:
            st.markdown(
                f"<div style='text-align:center;background:#1a1a2e;border-radius:12px;"
                f"padding:12px 6px;margin:4px;'>"
                f"<div style='font-size:2rem;font-weight:bold;color:#00d4ff'>{num}</div>"
                f"<div style='font-size:0.8rem;color:#aaa'>root {root}</div>"
                f"<div style='font-size:1.1rem'>{em} {pl}</div>"
                f"<div style='font-size:0.75rem;color:#ccc'>in {sign}</div>"
                f"<div style='font-size:0.7rem;color:#888'>{sign_q}</div>"
                f"<div style='font-size:0.7rem;color:#888'>house {house} — {h_meaning}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ---- magic / lucky stars ------------------------------------------------
    if magic:
        label = "Lucky Stars" if "euro" in system.lower() else "Magic numbers"
        st.markdown(f"**{label}** ({len(magic)} picks)")
        cols2 = st.columns(len(magic))
        for i, num in enumerate(magic):
            pl = _planet(num)
            root = _root(num)
            em = PLANET_EMOJI.get(pl, "")
            t = transits.get(pl.lower(), {})
            sign = t.get("sign", "—")
            sign_q = SIGN_QUALITY.get(sign, "")
            with cols2[i]:
                st.markdown(
                    f"<div style='text-align:center;background:#2a0a3e;border-radius:12px;"
                    f"padding:10px 6px;margin:4px;'>"
                    f"<div style='font-size:1.8rem;font-weight:bold;color:#df80ff'>{num}</div>"
                    f"<div style='font-size:0.8rem;color:#aaa'>root {root}</div>"
                    f"<div style='font-size:1.0rem'>{em} {pl}</div>"
                    f"<div style='font-size:0.75rem;color:#ccc'>in {sign}</div>"
                    f"<div style='font-size:0.7rem;color:#888'>{sign_q}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ---- planet-ruler summary -----------------------------------------------
    planet_counts: dict[str, list[int]] = {}
    for num in main + magic:
        planet_counts.setdefault(_planet(num), []).append(num)

    st.markdown("**Planet rulers in this draw:**")
    for pl, nums in sorted(planet_counts.items(), key=lambda x: -len(x[1])):
        em = PLANET_EMOJI.get(pl, "")
        meaning = PLANET_MEANINGS.get(pl, "")
        t = transits.get(pl.lower(), {})
        sign = t.get("sign", "—")
        house = t.get("house", "—")
        st.markdown(
            f"- {em} **{pl}** → numbers {nums} &nbsp;|&nbsp; "
            f"currently in **{sign}** (house {house}) &nbsp;|&nbsp; _{meaning}_"
        )

    # ---- active dasa --------------------------------------------------------
    maha = dasa.get("mahadasa")
    bhukti = dasa.get("bhukti")
    if maha:
        maha_meaning = PLANET_MEANINGS.get(maha, "")
        bhukti_meaning = PLANET_MEANINGS.get(bhukti, "") if bhukti else ""
        st.markdown(
            f"**Active dasa:** {PLANET_EMOJI.get(maha,'')} {maha}"
            + (f" / {PLANET_EMOJI.get(bhukti,'')} {bhukti}" if bhukti else "")
        )
        if maha_meaning:
            st.caption(f"Mahadasa planet theme: {maha_meaning}")
        if bhukti_meaning:
            st.caption(f"Bhukti planet theme: {bhukti_meaning}")


def _render_play_result(out: str, system: str) -> None:
    """Parse CLI play/generate output and display it visually."""
    main, magic = _parse_numbers(out)
    score, reasons = _parse_score(out)
    snap = _load_snapshot()

    # Win-day match score badge
    if score > 0:
        colour = "#22c55e" if score >= 60 else "#f59e0b" if score >= 30 else "#ef4444"
        st.markdown(
            f"<div style='background:{colour};border-radius:12px;padding:10px 18px;"
            f"display:inline-block;font-size:1.3rem;font-weight:bold;color:white'>"
            f"Win-day match score: {score}/100</div>",
            unsafe_allow_html=True,
        )
        for r in reasons:
            st.caption(f"• {r}")
        st.write("")

    if main:
        _render_number_cards(main, magic, system, snap)
    else:
        st.warning("Could not parse numbers from output — see raw output below.")

    # Current planet alignment
    st.markdown("### Current planet alignment (VedAstro snapshot)")
    _render_planet_table(snap)

    # Full CLI output in expander
    with st.expander("Raw CLI output", expanded=not bool(main)):
        st.code(out)


# ── page ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="Lucky Numbers", page_icon="🍀", layout="wide")

    st.title("🍀 Lucky Numbers — Dashboard")
    st.caption(
        f"Repo: `{ROOT}`  |  "
        f"VedAstro snapshot: `{_snapshot_age()}`  |  "
        f"Loaded: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )

    # ── jackpot-win tables with planet detail ─────────────────────────────────
    st.header("Last 10 jackpot-win draws")
    st.markdown(
        "_Click any row to see the winning numbers' planet rulers "
        "and (when enriched) the sky alignment on that draw day._"
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("AT Lotto 6/45")
        _render_win_table("at", _load_last_wins(AT_WINS), _load_sky_index(AT_SKY_JSONL))
    with col_b:
        st.subheader("EuroMillions")
        _render_win_table("eu", _load_last_wins(EU_WINS), _load_sky_index(EU_SKY_JSONL))

    if st.button("Reload tables from disk"):
        st.rerun()

    # ── commands ──────────────────────────────────────────────────────────────
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
            st.success("Done — see analysis below ↓")
            _render_play_result(out, "loto6")

        if st.button("▶ Play EuroMillions", use_container_width=True):
            with st.spinner("Running full play for euromillions…"):
                out = _run_cli(["play", "euromillions", "--win-years", str(int(win_years))])
            st.success("Done — see analysis below ↓")
            _render_play_result(out, "euromillions")

    # --- generate (offline, fast) --------------------------------------------
    with c2:
        st.markdown("**Generate (offline)**")
        if st.button("Generate Loto6", use_container_width=True):
            out = _run_cli(["generate", "loto6"])
            _render_play_result(out, "loto6")

        if st.button("Generate Euromillions", use_container_width=True):
            out = _run_cli(["generate", "euromillions"])
            _render_play_result(out, "euromillions")

        if st.button("Generate + Audit trail (loto6)", use_container_width=True):
            out = _run_cli(["generate", "loto6", "--explain"])
            _render_play_result(out, "loto6")

    # --- VedAstro refresh ----------------------------------------------------
    with c3:
        st.markdown("**VedAstro refresh**")
        if st.button("Refresh snapshot", use_container_width=True):
            with st.spinner("Calling VedAstro…"):
                out = _run_cli(["refresh"])
            st.code(out)
            st.markdown("**Updated planet alignment:**")
            _render_planet_table(_load_snapshot())

        if st.button("Refresh + numerology", use_container_width=True):
            with st.spinner("Calling VedAstro…"):
                out = _run_cli(["refresh", "--numerology"])
            st.code(out)

        if st.button("Show snapshot summary", use_container_width=True):
            st.code(_run_cli(["show"]))
            st.markdown("**Current transits:**")
            _render_planet_table(_load_snapshot())

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
