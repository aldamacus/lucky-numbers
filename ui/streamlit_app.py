"""
Lucky Numbers — Streamlit dashboard.

Shows the latest 10 jackpot-win draws for AT Lotto 6/45 and EuroMillions,
with per-row planet-alignment detail and a rich visual breakdown after every
play/generate run.

Run from the repo root (after `pip install -e .`):
    streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, date as _date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Inject Streamlit secrets into env so vedastro_client + the access gate
# pick them up (works on Streamlit Community Cloud where secrets are set in
# the dashboard, and locally when keys are exported in the shell or .env).
try:
    if hasattr(st, "secrets"):
        for _k in ("VEDASTRO_API_KEY", "LUCKY_NUMBERS_ACCESS_KEYS"):
            if _k in st.secrets:
                os.environ.setdefault(_k, str(st.secrets[_k]))
except Exception:
    pass

# Lazy imports from lucky_numbers with forced reload so edits to src/lucky_numbers/*
# are picked up without restarting the Streamlit server. Reload cost is negligible
# (tiny modules) and only happens when these helpers are called.
import importlib  # noqa: E402

def _fresh_import(module_name: str):
    import sys as _sys  # noqa: PLC0415
    mod = importlib.import_module(module_name)
    # Reload the module AND its sibling deps so any cross-module change applies
    for dep in ("lucky_numbers.models", "lucky_numbers.rules",
                "lucky_numbers.seeds", "lucky_numbers.loader",
                "lucky_numbers.engine", "lucky_numbers.vedastro_client",
                "lucky_numbers.numerology"):
        if dep in _sys.modules:
            importlib.reload(_sys.modules[dep])
    return importlib.import_module(module_name)

def _import_engine():
    return _fresh_import("lucky_numbers.engine")

def _import_loader():
    return _fresh_import("lucky_numbers.loader")

def _import_models():
    return _fresh_import("lucky_numbers.models")

def _import_vedastro_client():
    mod = _fresh_import("lucky_numbers.vedastro_client")
    return mod.VedAstroClient


def _import_numerology():
    return _fresh_import("lucky_numbers.numerology")

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


def _mask_paths(text: str) -> str:
    """Replace absolute filesystem paths with friendly placeholders.

    Avoids leaking the user's repo location (e.g. F:\\Proiecte\\lucky-numbers)
    or home directory into the browser. Handles:
      - both backslash and forward-slash separators
      - double-escaped backslashes (e.g. inside JSON strings)
      - case-insensitive Windows drive letters (subprocess output may
        capitalise the drive even if Path.resolve() lowercases it)
    """
    if not text:
        return text

    def _variants(p: str) -> list[str]:
        if not p:
            return []
        bs = p
        fs = p.replace("\\", "/")
        out = {bs, fs, bs.replace("\\", "\\\\")}
        # Case variants of the drive letter (Windows)
        if len(p) >= 2 and p[1] == ":":
            for v in list(out):
                out.add(v[0].upper() + v[1:])
                out.add(v[0].lower() + v[1:])
        # Drop empties / duplicates while preserving order (longest first wins)
        return sorted(out, key=len, reverse=True)

    # Substitute repo paths first (longer / more specific) then home paths
    for orig in _variants(str(ROOT)):
        text = text.replace(orig, "<repo>")
    for orig in _variants(str(Path.home())):
        text = text.replace(orig, "<home>")
    return text


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
    return _mask_paths(combined or "(no output)")


def _run_script(rel: str, extra: list[str] | None = None) -> str:
    path = (ROOT / rel).resolve()
    if not path.exists():
        return _mask_paths(f"Script not found: {path}")
    cmd = [sys.executable, str(path)] + (extra or [])
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                           text=True, timeout=600, env=env)
    except Exception as exc:
        return _mask_paths(str(exc))
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    combined = out + ("\n" + err if err else "")
    if r.returncode != 0:
        combined += f"\n\n[exit {r.returncode}]"
    return _mask_paths(combined or "(no output)")


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


# ── Audit trail (browser-friendly, grouped) ──────────────────────────────────

def _classify_audit(entry) -> tuple[str, str, str]:
    """Return (group_key, group_label, icon) for an audit entry.

    Groups (in display order):
      win_match  — today's sky matched a historical jackpot-win signature
      baseline   — always-on win-day numbers
      person1    — Person 1 (self) seeds, transits, dasa
      person2    — Person 2 (other) seeds, transits, dasa
      combined   — joint Person 1+2 rules
      block      — numbers removed from the pool
      skipped    — rules that could not be evaluated
    """
    rid = (entry.rule_id or "").lower()
    action = (entry.action or "").lower()

    if action.startswith("when-"):
        return ("skipped", "Skipped (data missing)", "⚠️")
    if action == "remove_range":
        return ("block", "Numbers excluded", "🚫")
    if "win_day_sign_match" in rid:
        return ("win_match", "Win-day sky match", "🌟")
    if "win_day_number" in rid or "win_day_numbers_baseline" in rid:
        return ("baseline", "Historical win-day baseline", "🎯")
    # Person 2 (other) — new canonical names + legacy `son_*` for old caches
    if rid.startswith("other_") or rid.startswith("son_"):
        return ("person2", "Person 2 (secondary)", "👤")
    if rid in {"shared_lagna_axis", "jupiter_other_house_blend",
               "jupiter_son_house_blend", "birthday_sum",
               "self_other_axis", "father_son_axis"}:
        return ("combined", "Joint Person 1 + 2", "🤝")
    if rid.startswith("self_") or rid in {"royal_star_23", "jupiter_compound_3"}:
        return ("person1", "Person 1 (protagonist)", "👑")
    if rid in {"mahadasa_lord_emphasis", "bhukti_lord_emphasis",
               "antara_lord_emphasis"}:
        return ("person1", "Person 1 (protagonist)", "👑")
    if rid.startswith("jupiter_") or rid.startswith("venus_") or rid.startswith("mars_") \
       or rid.startswith("moon_") or rid.startswith("high_bindu") \
       or rid.startswith("saturn_"):
        return ("person1", "Person 1 (protagonist)", "👑")
    return ("person1", "Person 1 (protagonist)", "👑")


_GROUP_ORDER = [
    ("win_match", "🌟 Win-day sky match", "Today's planet positions match a historical jackpot-winning signature — strongest signal."),
    ("baseline",  "🎯 Historical win-day baseline", "Numbers most frequently appearing on past jackpot-win days."),
    ("person1",   "👑 Person 1 (protagonist)", "Birth, numerology, lagna, current transits and active dasa of Person 1."),
    ("person2",   "👤 Person 2 (secondary)", "Birth, lagna and dasa of Person 2 — about half the weight of Person 1."),
    ("combined",  "🤝 Joint Person 1 + 2", "Combined axes (lagna sum, jupiter blend, birthday sum)."),
    ("block",     "🚫 Numbers excluded", "Numbers removed from the candidate pool."),
    ("skipped",   "⚠️ Skipped rules", "Rules whose `when` clause referenced data not in the snapshot — they did not contribute. Useful for diagnosing missing inputs."),
]

# Pleasant per-group accent colours (background tints for the cards)
_GROUP_COLOR = {
    "win_match": "#1f3b1f",
    "baseline":  "#1f2f3b",
    "person1":   "#2a1f3b",
    "person2":   "#3b2a1f",
    "combined":  "#1f3b3b",
    "block":     "#3b1f1f",
    "skipped":   "#3b3b1f",
}


def _format_numbers_brief(nums: list[int], limit: int = 12) -> str:
    if not nums:
        return "—"
    if len(nums) <= limit:
        return ", ".join(str(n) for n in nums)
    head = ", ".join(str(n) for n in nums[:limit])
    return f"{head} … (+{len(nums) - limit} more)"


def _render_audit_trail(audit: list, *, default_open: bool = False) -> None:
    """Pretty grouped audit display with a collapsible raw view.

    Replaces the flat list-of-captions that used to make the audit hard to
    scan. Each group has an explanation header, then a card per rule showing
    icon · friendly label · weight badge · numbers · plain reason.
    """
    if not audit:
        return

    # Bucket entries by group
    buckets: dict[str, list] = {key: [] for key, _, _ in _GROUP_ORDER}
    for e in audit:
        gk, _, _ = _classify_audit(e)
        buckets.setdefault(gk, []).append(e)

    nonempty = [(k, label, blurb) for (k, label, blurb) in _GROUP_ORDER if buckets.get(k)]
    if not nonempty:
        return

    with st.expander("🧾 Audit trail — why these numbers?", expanded=default_open):
        st.caption(
            "Each rule that fired is grouped by its source. Higher-weight rules "
            "have a bigger effect on the final pick. Skipped rules show where "
            "your snapshot is missing data — fix those to get richer output."
        )

        # Compact summary line: rules per group + total weight
        summary_bits = []
        for k, label, _ in nonempty:
            n = len(buckets[k])
            w = sum(int(e.weight or 0) for e in buckets[k])
            summary_bits.append(f"**{label.split(' ', 1)[1] if ' ' in label else label}**: {n} rule{'s' if n != 1 else ''} (Σw={w})")
        st.markdown(" · ".join(summary_bits))

        for gk, label, blurb in nonempty:
            entries = buckets[gk]
            bg = _GROUP_COLOR.get(gk, "#222")
            st.markdown(f"#### {label}  <span style='color:#888;font-size:0.8rem'>· {len(entries)} rule(s)</span>", unsafe_allow_html=True)
            st.caption(blurb)

            for e in entries:
                w = int(e.weight or 0)
                # Weight badge colour scales with influence
                badge_bg = (
                    "#22c55e" if w >= 6 else
                    "#eab308" if w >= 3 else
                    "#64748b"
                )
                nums_text = _format_numbers_brief(list(e.numbers or []))
                # Friendly action label
                action_label = {
                    "seed":        "adds seed",
                    "add":         "adds",
                    "add_many":    "adds many",
                    "remove_range": "blocks range",
                    "weight_planet": "boosts planet harmonics",
                    "weight_planet_strongest": "boosts strongest planet",
                    "when-skipped": "skipped — missing data",
                    "when-error":   "skipped — eval error",
                }.get((e.action or "").lower(), e.action or "")

                rid_safe = (e.rule_id or "?").replace("<", "&lt;").replace(">", "&gt;")
                reason_safe = (e.reason or "").replace("<", "&lt;").replace(">", "&gt;")

                st.markdown(
                    f"<div style='background:{bg};border-radius:10px;"
                    f"padding:10px 14px;margin:6px 0;border-left:4px solid {badge_bg}'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                    f"<div style='font-weight:600;color:#e2e8f0'>{rid_safe}</div>"
                    f"<div style='background:{badge_bg};color:white;padding:2px 10px;"
                    f"border-radius:999px;font-size:0.75rem;font-weight:600'>weight {w}</div>"
                    f"</div>"
                    f"<div style='color:#cbd5e1;font-size:0.85rem;margin-top:4px'>"
                    f"<span style='color:#94a3b8'>{action_label}</span> → "
                    f"<code style='background:#0f172a;color:#7dd3fc;padding:1px 6px;"
                    f"border-radius:4px'>{nums_text}</code></div>"
                    f"<div style='color:#94a3b8;font-size:0.8rem;margin-top:4px;"
                    f"font-style:italic'>{reason_safe}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # Raw table for power users
        with st.expander("Raw audit (table)", expanded=False):
            try:
                df = pd.DataFrame([
                    {
                        "rule": e.rule_id,
                        "action": e.action,
                        "weight": e.weight,
                        "numbers": ", ".join(str(n) for n in (e.numbers or [])[:20]),
                        "reason": e.reason,
                    }
                    for e in audit
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.caption(f"Could not render raw table: {exc}")


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


# ── person setup helpers ──────────────────────────────────────────────────────

_RELATION_TYPES = [
    "Father-Son",
    "Father-Daughter",
    "Mother-Son",
    "Mother-Daughter",
    "Married",
    "Partner",
    "Relationship",
]

# Only these relation types get an enabled event date
_DATE_ENABLED_RELATIONS = {"Married", "Relationship"}

_ROLES = ["self", "father", "mother", "son", "daughter", "partner", "married", "other"]

# Persistent cache directory — writable on both local dev and Streamlit Cloud
_CACHE_DIR = Path.home() / ".lucky-numbers"
_FORM_STATE_FILE = _CACHE_DIR / "form_state.json"
_VEDASTRO_CACHE_FILE = _CACHE_DIR / "vedastro_cache.json"

# Vedic planet friendship table (used for astral compatibility)
_PLANET_FRIENDS: dict[str, dict[str, list[str]]] = {
    "Sun":     {"friends": ["Moon", "Mars", "Jupiter"],    "enemies": ["Saturn", "Venus", "Rahu"]},
    "Moon":    {"friends": ["Sun", "Mercury"],             "enemies": ["Saturn", "Rahu", "Ketu"]},
    "Mars":    {"friends": ["Sun", "Moon", "Jupiter"],     "enemies": ["Mercury", "Rahu"]},
    "Mercury": {"friends": ["Sun", "Venus"],               "enemies": ["Moon"]},
    "Jupiter": {"friends": ["Sun", "Moon", "Mars"],        "enemies": ["Mercury", "Venus", "Rahu"]},
    "Venus":   {"friends": ["Mercury", "Saturn"],          "enemies": ["Sun", "Moon", "Rahu"]},
    "Saturn":  {"friends": ["Mercury", "Venus", "Rahu"],   "enemies": ["Sun", "Moon", "Mars"]},
    "Rahu":    {"friends": ["Saturn", "Venus", "Mercury"], "enemies": ["Sun", "Moon", "Mars"]},
    "Ketu":    {"friends": ["Mars", "Venus", "Saturn"],    "enemies": ["Sun", "Moon", "Mercury"]},
}


def _planet_compatibility(p1: str, p2: str) -> tuple[str, str]:
    """Return (label, description) for two ruling planets."""
    if p1 == p2:
        return "Same planet", f"Both ruled by {PLANET_EMOJI.get(p1,'')} {p1} — deep mutual understanding, shared drives."
    fr1 = _PLANET_FRIENDS.get(p1, {})
    fr2 = _PLANET_FRIENDS.get(p2, {})
    p1_view = "friend" if p2 in fr1.get("friends", []) else ("enemy" if p2 in fr1.get("enemies", []) else "neutral")
    p2_view = "friend" if p1 in fr2.get("friends", []) else ("enemy" if p1 in fr2.get("enemies", []) else "neutral")
    if p1_view == "friend" and p2_view == "friend":
        return "Strong harmony", f"{PLANET_EMOJI.get(p1,'')} {p1} and {PLANET_EMOJI.get(p2,'')} {p2} are mutual friends — natural attraction, easy cooperation, shared luck."
    elif p1_view == "enemy" and p2_view == "enemy":
        return "Magnetic tension", f"{PLANET_EMOJI.get(p1,'')} {p1} and {PLANET_EMOJI.get(p2,'')} {p2} are mutual enemies — powerful attraction through contrast; growth through friction."
    elif p1_view == "friend" or p2_view == "friend":
        return "Complementary bond", f"One-sided friendship — nurturing dynamic where one supports the other's growth."
    else:
        return "Neutral balance", f"{PLANET_EMOJI.get(p1,'')} {p1} and {PLANET_EMOJI.get(p2,'')} {p2} hold neutral ground — steady, practical partnership."


# ── Persistent form state (file-based "cookie" equivalent) ───────────────────

def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_form_state() -> dict:
    try:
        if _FORM_STATE_FILE.exists():
            return json.loads(_FORM_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_form_state() -> None:
    """Persist current sidebar form values to disk so they survive page reloads."""
    ss = st.session_state
    state: dict = {}
    for prefix in ("p1", "p2"):
        for field in ("name", "time", "loc", "lat_geo", "lon_geo", "tz_name"):
            key = f"{prefix}_{field}"
            val = ss.get(key)
            if val is not None:
                state[key] = val
        dob_key = f"{prefix}_dob"
        val = ss.get(dob_key)
        if val is not None and hasattr(val, "strftime"):
            state[dob_key] = val.strftime("%Y-%m-%d")
    for key in ("num_people", "rel_type"):
        val = ss.get(key)
        if val is not None:
            state[key] = val
    rel_date = ss.get("rel_date")
    if rel_date is not None and hasattr(rel_date, "strftime"):
        state["rel_date"] = rel_date.strftime("%Y-%m-%d")
    # Access-gate persistence: free-trial counter + auth fingerprint
    # (fingerprint only, never the raw key).
    for key in ("_free_uses_count", "_auth_fp"):
        val = ss.get(key)
        if val is not None:
            state[key] = val
    _ensure_cache_dir()
    _FORM_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _preload_form_state() -> None:
    """On first render, seed session_state from the saved form file (cross-session persistence)."""
    if st.session_state.get("_form_loaded"):
        return
    saved = _load_form_state()
    for key, val in saved.items():
        if key not in st.session_state:
            if key in ("p1_dob", "p2_dob", "rel_date") and isinstance(val, str):
                try:
                    val = _date.fromisoformat(val)
                except Exception:
                    continue
            if key == "num_people" and isinstance(val, str):
                try:
                    val = int(val)
                except Exception:
                    val = 1
            if key == "_free_uses_count":
                try:
                    val = int(val)
                except Exception:
                    val = 0
            st.session_state[key] = val
    st.session_state["_form_loaded"] = True


# ── Access gate (free trial + key-based unlock) ──────────────────────────────
#
# Free-trial model:
#   - Anyone can run up to FREE_USES_LIMIT generations (Generate * + Play *)
#     per browser-cookie session. The counter is persisted in form_state.json
#     so it survives page reloads.
#   - After the trial is exhausted, the user must enter a valid access key
#     to keep generating. Keys are configured by the operator in the
#     LUCKY_NUMBERS_ACCESS_KEYS env var (or Streamlit secret) as a comma-
#     separated list. They are NEVER stored on disk in plaintext — only a
#     SHA-256 fingerprint of the validated key is persisted, so a subsequent
#     reload knows the user already authenticated this browser.
#   - If LUCKY_NUMBERS_ACCESS_KEYS is unset/empty the gate is disabled
#     (open-access mode, useful in dev).

FREE_USES_LIMIT = 4
_ACCESS_KEYS_ENV = "LUCKY_NUMBERS_ACCESS_KEYS"


def _get_access_keys() -> set[str]:
    """Parse the operator-configured access keys (comma/whitespace separated)."""
    raw = os.environ.get(_ACCESS_KEYS_ENV, "") or ""
    keys: set[str] = set()
    for chunk in raw.replace("\n", ",").split(","):
        k = chunk.strip()
        if k:
            keys.add(k)
    return keys


def _gate_enabled() -> bool:
    """True when the operator configured any access keys (i.e. real deployment)."""
    return bool(_get_access_keys())


def _key_fingerprint(key: str) -> str:
    return hashlib.sha256(("lucky-numbers-v1|" + key).encode()).hexdigest()


def _valid_key_fingerprints() -> set[str]:
    return {_key_fingerprint(k) for k in _get_access_keys()}


def _is_authenticated() -> bool:
    """Check session-level auth, validated against the current env keys."""
    fp = st.session_state.get("_auth_fp")
    if not fp:
        return False
    return fp in _valid_key_fingerprints()


def _free_uses_used() -> int:
    return int(st.session_state.get("_free_uses_count", 0) or 0)


def _free_uses_remaining() -> int:
    return max(0, FREE_USES_LIMIT - _free_uses_used())


def _can_generate() -> bool:
    if not _gate_enabled():
        return True
    if _is_authenticated():
        return True
    return _free_uses_remaining() > 0


def _consume_free_use() -> None:
    """Increment the free-trial counter (no-op for authenticated users)."""
    if not _gate_enabled() or _is_authenticated():
        return
    st.session_state["_free_uses_count"] = _free_uses_used() + 1
    _save_form_state()


def _try_login(submitted_key: str) -> bool:
    if not _gate_enabled():
        return False
    fp = _key_fingerprint(submitted_key.strip())
    if fp in _valid_key_fingerprints():
        st.session_state["_auth_fp"] = fp
        _save_form_state()
        return True
    return False


def _logout() -> None:
    st.session_state.pop("_auth_fp", None)
    _save_form_state()


def _render_access_panel() -> None:
    """Trial counter + login form / logged-in badge.

    Render once at the top of the Generate section so the user always sees
    where they stand. Buttons themselves are still disabled when the trial
    is exhausted, so this is the only place to unlock.
    """
    if not _gate_enabled():
        st.caption(
            "🟢 **Open-access mode** (operator has not configured "
            f"`{_ACCESS_KEYS_ENV}` — set it to enable the access gate)."
        )
        return

    if _is_authenticated():
        col1, col2 = st.columns([5, 1])
        with col1:
            st.success("✅ **Access key validated** — unlimited generations.")
        with col2:
            if st.button("Log out", use_container_width=True, key="logout_btn"):
                _logout()
                st.rerun()
        return

    remaining = _free_uses_remaining()
    if remaining > 0:
        st.info(
            f"🎁 **Free trial:** {remaining} of {FREE_USES_LIMIT} generation(s) remaining. "
            "After that you'll need an access key to continue."
        )
    else:
        st.warning(
            "🔒 **Free trial used up.** Enter your access key below to keep "
            "generating numbers."
        )

    with st.expander("🔑 Enter access key", expanded=remaining == 0):
        with st.form("access_key_form", clear_on_submit=True):
            key_input = st.text_input(
                "Access key", type="password",
                placeholder="paste the key your operator gave you",
                help="Operator configures valid keys via the "
                     f"`{_ACCESS_KEYS_ENV}` environment variable.",
            )
            ok = st.form_submit_button("Unlock", type="primary",
                                       use_container_width=True)
            if ok:
                if not key_input.strip():
                    st.error("Please paste a key.")
                elif _try_login(key_input):
                    st.success("Validated — reloading…")
                    st.rerun()
                else:
                    st.error("Invalid access key.")


# ── VedAstro result cache (keyed by person-data hash) ────────────────────────

def _person_cache_key(p1_data: dict, p2_data: dict | None) -> str:
    """Stable MD5 hash of the inputs that determine VedAstro output."""
    parts = [
        p1_data.get("name", ""),
        p1_data.get("birth", {}).get("date", ""),
        p1_data.get("birth", {}).get("location", ""),
    ]
    if p2_data:
        parts += [
            p2_data.get("name", ""),
            p2_data.get("birth", {}).get("date", ""),
            p2_data.get("birth", {}).get("location", ""),
        ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _load_vedastro_cache(cache_key: str) -> dict | None:
    try:
        if _VEDASTRO_CACHE_FILE.exists():
            data = json.loads(_VEDASTRO_CACHE_FILE.read_text(encoding="utf-8"))
            return data.get(cache_key)
    except Exception:
        pass
    return None


def _save_vedastro_cache(cache_key: str, payload: dict) -> None:
    _ensure_cache_dir()
    try:
        existing: dict = {}
        if _VEDASTRO_CACHE_FILE.exists():
            existing = json.loads(_VEDASTRO_CACHE_FILE.read_text(encoding="utf-8"))
        existing[cache_key] = payload
        # Keep only the 10 most-recent entries
        if len(existing) > 10:
            for old_key in list(existing.keys())[:-10]:
                del existing[old_key]
        _VEDASTRO_CACHE_FILE.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ── Geocoding + Timezone ──────────────────────────────────────────────────────

def _geocode_location(location: str) -> tuple[float, float] | None:
    """Return (lat, lon) via Nominatim/OpenStreetMap. Uses httpx (already a dep)."""
    import httpx  # noqa: PLC0415
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "lucky-numbers-app/1.0"},
            timeout=10.0,
        )
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None


def _get_timezone_name(lat: float, lon: float) -> str:
    """Return IANA timezone name for coordinates via timeapi.io (free, no key)."""
    import httpx  # noqa: PLC0415
    try:
        r = httpx.get(
            "https://timeapi.io/api/timezone/coordinate",
            params={"latitude": str(lat), "longitude": str(lon)},
            timeout=10.0,
        )
        return r.json().get("timeZone", "UTC")
    except Exception:
        return "UTC"


def _tz_offset_for_date(tz_name: str, year: int, month: int, day: int,
                         hour: int = 12, minute: int = 0) -> str:
    """Return ±HH:MM UTC offset for an IANA timezone at a specific date (DST-aware).

    Uses zoneinfo (Python 3.9+ stdlib) — no extra dependency required.
    """
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        import datetime as _dt         # noqa: PLC0415
        tz = ZoneInfo(tz_name)
        dt = _dt.datetime(year, month, day, hour, minute, tzinfo=tz)
        offset = dt.utcoffset()
        if offset is None:
            return "+00:00"
        total_secs = int(offset.total_seconds())
        sign = "+" if total_secs >= 0 else "-"
        h = abs(total_secs) // 3600
        m = (abs(total_secs) % 3600) // 60
        return f"{sign}{h:02d}:{m:02d}"
    except Exception:
        return "+00:00"


# ── Person form ───────────────────────────────────────────────────────────────

def _person_form(prefix: str, label: str, expanded: bool = True) -> None:
    """Render a person birth-data form (no UTC offset — timezone auto-detected from location)."""
    with st.expander(label, expanded=expanded):
        st.text_input("Full name", key=f"{prefix}_name",
                      placeholder="e.g. John Smith")

        col1, col2 = st.columns(2)
        with col1:
            st.date_input(
                "Date of birth", key=f"{prefix}_dob",
                min_value=_date(1900, 1, 1),
                max_value=_date.today(),
            )
        with col2:
            st.text_input("Birth time (HH:MM)", key=f"{prefix}_time",
                          value=st.session_state.get(f"{prefix}_time", "09:00"),
                          placeholder="09:00")

        st.text_input("Location", key=f"{prefix}_loc",
                      placeholder="Vienna, Austria",
                      help="City and country — timezone resolved automatically from location")

        # Show detected timezone (read-only) if already geocoded
        tz_name = st.session_state.get(f"{prefix}_tz_name")
        if tz_name:
            st.caption(f"Timezone: {tz_name}")


# ── Astral connection panel ───────────────────────────────────────────────────

def _render_astral_connection() -> None:
    """Show planet compatibility between the two persons in the sidebar."""
    snap = st.session_state.get("snapshot_obj")
    if snap is None or snap.other is None:
        return

    p1 = snap.self_
    p2 = snap.other
    rel = snap.relationship

    em1 = PLANET_EMOJI.get(_planet(p1.birth.day), "")
    em2 = PLANET_EMOJI.get(_planet(p2.birth.day), "")
    pl1 = _planet(p1.birth.day)
    pl2 = _planet(p2.birth.day)

    st.markdown("---")
    st.markdown("**Astral connection**")
    st.markdown(
        f"**{p1.name}** — birth day {p1.birth.day} → {em1} {pl1}  \n"
        f"**{p2.name}** — birth day {p2.birth.day} → {em2} {pl2}"
    )
    if rel:
        st.caption(f"Relationship: {rel.relation_type}")
        if rel.transits_on_date:
            event_label = "Marriage" if rel.relation_type == "Married" else "Event"
            dominant = next(iter(rel.transits_on_date), None)
            if dominant:
                st.caption(
                    f"{event_label} date sky — dominant planet: "
                    f"{PLANET_EMOJI.get(dominant.capitalize(),'')} {dominant.capitalize()}"
                )

    label, desc = _planet_compatibility(pl1, pl2)
    st.info(f"**{label}**\n\n{desc}")


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _person_setup_sidebar() -> None:
    """Sidebar: enter 1–2 people with optional relationship. Stores data in session_state."""
    _preload_form_state()

    with st.sidebar:
        st.header("People & Relationship")

        # ── Reset button ──────────────────────────────────────────────────────
        if st.button("Reset cached data", use_container_width=True,
                     help="Clear all saved person data and start fresh"):
            keys_to_clear = [
                k for k in list(st.session_state.keys())
                if k.startswith(("p1_", "p2_", "rel_", "num_people", "snapshot_obj", "_form"))
            ]
            for k in keys_to_clear:
                del st.session_state[k]
            if _FORM_STATE_FILE.exists():
                _FORM_STATE_FILE.unlink(missing_ok=True)
            if _VEDASTRO_CACHE_FILE.exists():
                _VEDASTRO_CACHE_FILE.unlink(missing_ok=True)
            st.rerun()

        st.divider()

        num_people = st.radio(
            "Number of people", [1, 2], horizontal=True,
            key="num_people",
        )

        _person_form("p1", "Person 1", expanded=True)

        if num_people == 2:
            _person_form("p2", "Person 2", expanded=True)

            st.markdown("**Relationship**")
            rel_type = st.selectbox(
                "Relation type", _RELATION_TYPES, key="rel_type",
            )
            date_active = rel_type in _DATE_ENABLED_RELATIONS
            event_label = "Marriage date" if rel_type == "Married" else "Start date"

            col_d, col_t = st.columns(2)
            with col_d:
                st.date_input(
                    event_label, key="rel_date",
                    disabled=not date_active,
                    help="Available for Married and Relationship types only",
                )
            with col_t:
                st.text_input(
                    "Event time (HH:MM)", key="rel_time",
                    value=st.session_state.get("rel_time", "12:00"),
                    disabled=not date_active,
                )

        st.divider()

        if st.button("Fetch VedAstro data", type="primary", use_container_width=True,
                     help="Geocode locations, fetch transits/dasa, cache results"):
            _fetch_vedastro_for_persons()

        # Status + astral connection (shown after successful fetch)
        if "snapshot_obj" in st.session_state:
            st.success("Ready — generate buttons are now enabled")
            from_cache = st.session_state.get("_from_cache", False)
            if from_cache:
                st.caption("Using cached VedAstro data — no API call needed")
            _render_astral_connection()


def _person_dict_from_session(prefix: str, role_fallback: str) -> dict | None:
    """Build a person data dict from session_state keys.

    Geocoded coordinates and timezone are written by _fetch_vedastro_for_persons.
    The UTC offset is computed from the stored IANA timezone name + birth date
    so that DST is handled correctly for historical dates.
    """
    ss = st.session_state
    name = ss.get(f"{prefix}_name", "").strip()
    dob = ss.get(f"{prefix}_dob")
    if not name or dob is None:
        return None
    dob_str = dob.strftime("%Y-%m-%d") if hasattr(dob, "strftime") else str(dob)
    birth_time = ss.get(f"{prefix}_time", "09:00")
    try:
        bh, bm = (int(x) for x in birth_time.split(":"))
    except Exception:
        bh, bm = 9, 0
    tz_name = ss.get(f"{prefix}_tz_name", "UTC")
    try:
        y, mo, d = (int(x) for x in dob_str.split("-"))
    except Exception:
        y, mo, d = 2000, 1, 1
    tz_offset = _tz_offset_for_date(tz_name, y, mo, d, bh, bm)
    return {
        "name": name,
        "role": ss.get(f"{prefix}_role", role_fallback) or role_fallback,
        "birth": {
            "date": dob_str,
            "time": birth_time,
            "timezone": tz_offset,
            "location": ss.get(f"{prefix}_loc", ""),
            "latitude": float(ss.get(f"{prefix}_lat_geo", 0.0)),
            "longitude": float(ss.get(f"{prefix}_lon_geo", 0.0)),
        },
    }


def _vedastro_date(iso: str) -> str:
    """Convert YYYY-MM-DD to DD/MM/YYYY for VedAstro API."""
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def _fetch_vedastro_for_persons() -> None:
    """Geocode locations, check cache, call VedAstro if needed, store Snapshot."""
    ss = st.session_state
    loader = _import_loader()
    models = _import_models()
    VedAstroClient = _import_vedastro_client()
    numerology = _import_numerology()

    # ── 1. Geocode locations + resolve timezone ───────────────────────────────
    with st.sidebar:
        for prefix in (["p1"] + (["p2"] if ss.get("num_people", 1) == 2 else [])):
            loc = ss.get(f"{prefix}_loc", "").strip()
            if loc:
                with st.spinner(f"Geocoding {loc}…"):
                    coords = _geocode_location(loc)
                if coords:
                    ss[f"{prefix}_lat_geo"] = coords[0]
                    ss[f"{prefix}_lon_geo"] = coords[1]
                    with st.spinner(f"Detecting timezone for {loc}…"):
                        tz_name = _get_timezone_name(coords[0], coords[1])
                    ss[f"{prefix}_tz_name"] = tz_name
                    st.caption(f"📍 {loc}: {coords[0]:.4f}, {coords[1]:.4f} · {tz_name}")
                else:
                    st.warning(f"Could not geocode '{loc}' — coordinates and timezone set to defaults")
                    ss[f"{prefix}_lat_geo"] = 0.0
                    ss[f"{prefix}_lon_geo"] = 0.0
                    ss[f"{prefix}_tz_name"] = "UTC"
            else:
                ss[f"{prefix}_lat_geo"] = 0.0
                ss[f"{prefix}_lon_geo"] = 0.0
                ss[f"{prefix}_tz_name"] = "UTC"

    # ── 2. Build person dicts (now that geocoding is done) ────────────────────
    p1_data = _person_dict_from_session("p1", "self")
    if p1_data is None:
        st.sidebar.error("Fill in at least Person 1 name and date of birth.")
        return

    num_people = ss.get("num_people", 1)
    p2_data = _person_dict_from_session("p2", "other") if num_people == 2 else None

    # ── 3. Check disk cache (same person = same hash → skip API calls) ────────
    cache_key = _person_cache_key(p1_data, p2_data)
    cached = _load_vedastro_cache(cache_key)
    if cached:
        # Normalise legacy `son` keys to `other` (cache files predating rename)
        def _migrate_subjects(d: dict) -> dict:
            if not isinstance(d, dict):
                return d or {}
            return {("other" if k == "son" else k): v for k, v in d.items()}

        transits = _migrate_subjects(cached.get("transits", {}))
        dasa = _migrate_subjects(cached.get("dasa", {}))
        natal_blocks = _migrate_subjects(cached.get("natal", {}))
        numerology_blocks = _migrate_subjects(cached.get("numerology", {}))
        rel_raw = cached.get("rel", None)
        rel_obj = None
        if rel_raw and p2_data:
            rel_date_obj = ss.get("rel_date")
            if rel_date_obj is not None:
                rel_obj = models.RelationshipData(
                    relation_type=rel_raw.get("type", ss.get("rel_type", "Relationship")),
                    event_date=rel_date_obj if hasattr(rel_date_obj, "year")
                               else _date.fromisoformat(rel_raw.get("date", str(rel_date_obj))),
                    transits_on_date=rel_raw.get("transits_on_date", {}),
                )
        p1_person = loader.build_person(p1_data)
        # Re-attach numerology + natal blocks so base_seeds/combined rules fire
        p1_person.numerology = numerology_blocks.get("self", {}) or numerology.chaldean_profile(p1_person.name)
        p1_person.natal = natal_blocks.get("self", {})

        other_person = loader.build_person(p2_data) if p2_data else None
        if other_person is not None:
            other_person.numerology = (
                numerology_blocks.get("other", {})
                or numerology.chaldean_profile(other_person.name)
            )
            other_person.natal = natal_blocks.get("other", {})

        ss["snapshot_obj"] = models.Snapshot(
            self_=p1_person, other=other_person,
            transits=transits, dasa=dasa, relationship=rel_obj,
        )
        ss["_from_cache"] = True
        _save_form_state()
        # Sync to data/people.yaml + data/snapshot.yaml so the CLI buttons
        # (Show / Refresh / Play) operate on the freshly-fetched persons.
        _sync_session_to_disk()
        return

    # ── 4. Live VedAstro fetch ────────────────────────────────────────────────
    ss["_from_cache"] = False
    transits: dict = {}
    dasa: dict = {}
    natal_blocks: dict = {}
    numerology_blocks: dict = {
        "self": numerology.chaldean_profile(p1_data["name"]),
    }
    if p2_data:
        numerology_blocks["other"] = numerology.chaldean_profile(p2_data["name"])
    rel_obj = None

    try:
        client = VedAstroClient()
    except RuntimeError as exc:
        st.sidebar.error(f"VedAstro API key missing: {exc}")
        return

    with st.sidebar:
        with st.spinner(f"Fetching VedAstro data for {p1_data['name']}…"):
            b1 = p1_data["birth"]
            try:
                t1 = client.transits(
                    _vedastro_date(b1["date"]), b1["time"],
                    b1["latitude"], b1["longitude"], b1["timezone"],
                )
                d1 = client.current_dasa(
                    _vedastro_date(b1["date"]), b1["time"],
                    b1["latitude"], b1["longitude"], b1["timezone"],
                )
                transits["self"] = _normalise_transits(t1)
                dasa["self"] = _normalise_dasa(d1)
            except Exception as exc:
                st.warning(f"Person 1 VedAstro error: {exc}")

            # Natal chart (best-effort — silently skipped if VedAstro can't parse it)
            try:
                n1 = client.natal_chart(
                    _vedastro_date(b1["date"]), b1["time"],
                    b1["latitude"], b1["longitude"], b1["timezone"],
                )
                natal_blocks["self"] = _natal_from_payload(n1)
            except Exception as exc:
                st.caption(f"Person 1 natal chart unavailable: {exc}")
                natal_blocks["self"] = {}

        if p2_data:
            with st.spinner(f"Fetching VedAstro data for {p2_data['name']}…"):
                b2 = p2_data["birth"]
                try:
                    t2 = client.transits(
                        _vedastro_date(b2["date"]), b2["time"],
                        b2["latitude"], b2["longitude"], b2["timezone"],
                    )
                    d2 = client.current_dasa(
                        _vedastro_date(b2["date"]), b2["time"],
                        b2["latitude"], b2["longitude"], b2["timezone"],
                    )
                    transits["other"] = _normalise_transits(t2)
                    dasa["other"] = _normalise_dasa(d2)
                except Exception as exc:
                    st.warning(f"Person 2 VedAstro error: {exc}")

                try:
                    n2 = client.natal_chart(
                        _vedastro_date(b2["date"]), b2["time"],
                        b2["latitude"], b2["longitude"], b2["timezone"],
                    )
                    natal_blocks["other"] = _natal_from_payload(n2)
                except Exception as exc:
                    st.caption(f"Person 2 natal chart unavailable: {exc}")
                    natal_blocks["other"] = {}

            rel_date_obj = ss.get("rel_date")
            rel_type_val = ss.get("rel_type", "")
            if rel_date_obj is not None and rel_type_val in _DATE_ENABLED_RELATIONS:
                rel_dstr = (rel_date_obj.strftime("%Y-%m-%d")
                            if hasattr(rel_date_obj, "strftime") else str(rel_date_obj))
                rel_date_iso = _vedastro_date(rel_dstr)
                rel_time = ss.get("rel_time", "12:00")
                # Use Person 1's timezone for the event date (best available proxy)
                p1_tz_name = ss.get("p1_tz_name", "UTC")
                try:
                    ry, rm, rd = (int(x) for x in rel_dstr.split("-"))
                    rh = int(rel_time.split(":")[0])
                    rmn = int(rel_time.split(":")[1])
                except Exception:
                    ry, rm, rd, rh, rmn = 2000, 1, 1, 12, 0
                rel_tz = _tz_offset_for_date(p1_tz_name, ry, rm, rd, rh, rmn)
                with st.spinner("Fetching planetary sky on event date…"):
                    try:
                        sky_raw = client.sky_at_date(rel_date_iso, rel_time, rel_tz)
                        sky_transits = _normalise_transits(sky_raw)
                        rel_obj = models.RelationshipData(
                            relation_type=rel_type_val,
                            event_date=rel_date_obj,
                            transits_on_date=sky_transits,
                        )
                    except Exception as exc:
                        st.warning(f"Event sky error: {exc}")

    client.close()

    # ── 5. Build Snapshot + save to cache ────────────────────────────────────
    p1_person = loader.build_person(p1_data)
    p1_person.numerology = numerology_blocks.get("self", {})
    p1_person.natal = natal_blocks.get("self", {})

    other_person = loader.build_person(p2_data) if p2_data else None
    if other_person is not None:
        other_person.numerology = numerology_blocks.get("other", {})
        other_person.natal = natal_blocks.get("other", {})

    snapshot = models.Snapshot(
        self_=p1_person, other=other_person,
        transits=transits, dasa=dasa, relationship=rel_obj,
    )
    ss["snapshot_obj"] = snapshot

    cache_payload: dict = {
        "transits": transits,
        "dasa": dasa,
        "natal": natal_blocks,
        "numerology": numerology_blocks,
    }
    if rel_obj:
        cache_payload["rel"] = {
            "type": rel_obj.relation_type,
            "date": str(rel_obj.event_date),
            "transits_on_date": rel_obj.transits_on_date,
        }
    _save_vedastro_cache(cache_key, cache_payload)
    _save_form_state()
    # Mirror to data/people.yaml + data/snapshot.yaml so subsequent CLI
    # subprocesses (Show / Refresh / Play …) read the same persons.
    _sync_session_to_disk()


_SIGN_TO_INDEX = {
    "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
    "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
    "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12,
}


def _unwrap_mcp(rpc_result: dict) -> dict:
    """Unwrap MCP tools/call result envelope into raw payload dict.

    VedAstro returns the actual JSON inside content[0].text as a string.
    """
    if not isinstance(rpc_result, dict):
        return {}
    content = rpc_result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                parsed = json.loads(first["text"])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {"raw": first["text"]}
    return rpc_result


def _normalise_transits(raw: dict, lagna_index: int = 1) -> dict:
    """Convert VedAstro Gochara payload → engine-friendly dict.

    Output shape per planet:
        {sign, house, kaksha, ashtaka, sarvashtaka}
    Mirrors lucky_numbers.cli._normalize_transits so the rule engine and the
    Streamlit table see identical data regardless of code path.
    """
    payload = _unwrap_mcp(raw)
    # Most common envelope: top-level GocharaKakshas dict keyed by planet name
    gk = payload.get("GocharaKakshas")
    if not isinstance(gk, dict):
        # Fallbacks for alternate shapes
        for alt in ("Planets", "planets", "transits", "Transits", "result", "Result"):
            if isinstance(payload.get(alt), dict):
                gk = payload[alt]
                break
    if not isinstance(gk, dict):
        return {}

    out: dict = {}
    for planet, data in gk.items():
        if not isinstance(data, dict):
            continue
        sign = data.get("Sign") or data.get("sign") or "Aries"
        sign_idx = _SIGN_TO_INDEX.get(sign, 1)
        house = ((sign_idx - lagna_index) % 12) + 1
        out[planet.lower()] = {
            "sign": sign,
            "house": house,
            "kaksha": int(data.get("KakshaScore", data.get("kaksha", 0)) or 0),
            "ashtaka": int(data.get("Ashtaka", data.get("ashtaka", 0)) or 0),
            "sarvashtaka": int(data.get("Sarvashtaka", data.get("sarvashtaka", 0)) or 0),
        }
    return out


def _extract_planet_signs_from_evidence(payload: dict) -> dict[str, str]:
    """Pull {planet_lower: sign} from a get_context_based_astrology_data payload.

    VedAstro returns a list of `evidence` items with a `key_result` JSON string.
    The most useful method here is `AllPlanetSignsBasedOnHouseLongitudes`,
    which yields a planet→sign dict.
    """
    if not isinstance(payload, dict):
        return {}
    for ev in payload.get("evidence", []) or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("method") != "AllPlanetSignsBasedOnHouseLongitudes":
            continue
        kr = ev.get("key_result")
        if not isinstance(kr, str):
            continue
        try:
            obj = json.loads(kr)
        except Exception:
            continue
        if isinstance(obj, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in obj.items()}
    return {}


def _extract_lagna_sign(payload: dict, planet_signs: dict[str, str]) -> str | None:
    """Best-effort lagna/ascendant extraction from a context-based payload.

    Tries (in order):
      1. evidence entries whose key_result mentions a Lagna/Ascendant sign
      2. the planet_signs dict itself (some payloads include "Ascendant"/"Lagna")
      3. a top-level "Lagna" / "Ascendant" key
    """
    if not isinstance(payload, dict):
        return None

    # 1) scan evidence for ascendant-shaped key_results
    for ev in payload.get("evidence", []) or []:
        if not isinstance(ev, dict):
            continue
        method = str(ev.get("method") or "").lower()
        kr = ev.get("key_result")
        text = kr if isinstance(kr, str) else ""
        if "lagna" in method or "ascendant" in method or "rising" in method:
            for sign in _SIGN_TO_INDEX:
                if sign in text:
                    return sign
        if isinstance(kr, dict):
            for key in ("Lagna", "Ascendant", "RisingSign", "lagna", "ascendant"):
                v = kr.get(key)
                if isinstance(v, str) and v in _SIGN_TO_INDEX:
                    return v

    # 2) planet_signs may already contain it
    for key in ("ascendant", "lagna", "risingsign"):
        v = planet_signs.get(key)
        if isinstance(v, str) and v in _SIGN_TO_INDEX:
            return v

    # 3) top-level fallback
    for key in ("Lagna", "Ascendant", "RisingSign"):
        v = payload.get(key)
        if isinstance(v, str) and v in _SIGN_TO_INDEX:
            return v

    return None


def _natal_from_payload(raw: dict) -> dict:
    """Convert a natal_chart() payload into the engine-friendly natal block.

    Output mirrors the existing `data/snapshot.yaml` natal layout:
        {
          lagna_sign, lagna_sign_index, lagna_lord,
          moon_sign, moon_house, sun_house, mars_house, ...
        }

    Returns an empty dict if the payload could not be parsed; the rule engine
    then silently no-ops the natal rules and surfaces them in the audit (rec 4).
    """
    payload = _unwrap_mcp(raw)
    planet_signs = _extract_planet_signs_from_evidence(payload)
    lagna_sign = _extract_lagna_sign(payload, planet_signs)
    if not lagna_sign and not planet_signs:
        return {}

    natal: dict = {}
    if lagna_sign:
        natal["lagna_sign"] = lagna_sign
        natal["lagna_sign_index"] = _SIGN_TO_INDEX.get(lagna_sign, 1)
        # Lord of the lagna (sign → ruling planet)
        sign_lords = {
            "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
            "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
            "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
            "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
        }
        natal["lagna_lord"] = sign_lords.get(lagna_sign, "Unknown")

    lagna_index = natal.get("lagna_sign_index", 1)

    # Per-planet sign + derived house (relative to lagna)
    for planet, sign in planet_signs.items():
        sign_idx = _SIGN_TO_INDEX.get(sign)
        if sign_idx is None:
            continue
        house = ((sign_idx - lagna_index) % 12) + 1
        if planet == "moon":
            natal["moon_sign"] = sign
            natal["moon_house"] = house
        # Generic "<planet>_house" pattern matches base_seeds/combined.yaml usage
        natal[f"{planet}_house"] = house
    return natal


def _normalise_dasa(raw: dict) -> dict:
    """Extract {mahadasa, bhukti, antara} from a VedAstro dasa response."""
    payload = _unwrap_mcp(raw)
    levels = payload.get("levels") or payload.get("Levels") or []
    out: dict = {"mahadasa": None, "bhukti": None, "antara": None}
    label_map = {"Dasa": "mahadasa", "Mahadasha": "mahadasa",
                 "Bhukti": "bhukti", "Antaram": "antara", "Antara": "antara"}
    if isinstance(levels, list):
        for lvl in levels:
            if isinstance(lvl, dict):
                key = label_map.get(lvl.get("level"))
                if key:
                    out[key] = lvl.get("planet")
    # Fallback: top-level keys (used by some response shapes)
    if not any(out.values()):
        out["mahadasa"] = payload.get("mahadasa") or payload.get("Mahadasa") or payload.get("MahaDasa")
        out["bhukti"]   = payload.get("bhukti")   or payload.get("Bhukti")   or payload.get("AntarDasa")
        out["antara"]   = payload.get("antara")   or payload.get("Antara")   or payload.get("PratyantarDasa")
    return out


def _save_people_yaml(notify: bool = True) -> bool:
    """Write current form data to data/people.yaml for the CLI to pick up.

    Returns True on success. When `notify=False` the success/error message is
    not shown — used by the auto-sync-on-fetch path so it stays quiet when
    everything works.
    """
    ss = st.session_state
    p1 = _person_dict_from_session("p1", "self")
    if p1 is None:
        if notify:
            st.sidebar.error("Person 1 incomplete — cannot save.")
        return False
    num_people = ss.get("num_people", 1)
    p2 = _person_dict_from_session("p2", "other") if num_people == 2 else None

    data: dict = {"people": {"self": p1}}
    if p2:
        data["people"]["other"] = p2
    else:
        # Keep a placeholder so loader doesn't crash on CLI (single-person mode)
        data["people"]["other"] = p1

    out_path = ROOT / "data" / "people.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    if notify:
        st.sidebar.success(f"Saved to {out_path}")
    return True


def _save_snapshot_yaml(snapshot) -> bool:
    """Persist the in-memory Snapshot to data/snapshot.yaml.

    Mirrors the on-disk shape used by `lucky_numbers.loader.load_snapshot`,
    so the next CLI subprocess (`lucky show`, `lucky generate`,
    `lucky refresh`, `lucky play`) sees the freshly-fetched data without
    needing another VedAstro round-trip.

    CRITICAL: includes the `relationship` block. Without it the CLI/Play
    pipeline produces different numbers than the UI's Generate button,
    because (a) relationship-planet harmonics worth +3 weight per planet
    are missing from the pool, and (b) the deterministic seed string used
    by the tie-breaker also differs.
    """
    if snapshot is None:
        return False
    try:
        from datetime import datetime, timezone as _tz  # noqa: PLC0415

        other = snapshot.other if snapshot.other is not None else snapshot.self_
        snap_dict: dict = {
            "generated_at": datetime.now(_tz.utc).isoformat(),
            "self": {
                "numerology": snapshot.self_.numerology or {},
                "natal":      snapshot.self_.natal or {},
            },
            "other": {
                "numerology": other.numerology or {},
                "natal":      other.natal or {},
            },
            "transits": snapshot.transits or {},
            "dasa":     snapshot.dasa or {},
        }
        if snapshot.relationship is not None:
            rel = snapshot.relationship
            snap_dict["relationship"] = {
                "type": rel.relation_type,
                "date": str(rel.event_date),
                "transits_on_date": rel.transits_on_date or {},
            }
        out_path = ROOT / "data" / "snapshot.yaml"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            yaml.dump(snap_dict, f, allow_unicode=True,
                      default_flow_style=False, sort_keys=False)
        return True
    except Exception as exc:
        st.sidebar.warning(f"Could not save snapshot.yaml: {exc}")
        return False


def _sync_session_to_disk() -> None:
    """One-shot: dump session form + in-memory snapshot to disk.

    Called automatically at the end of `_fetch_vedastro_for_persons`. Without
    it, CLI-driven buttons (Show snapshot summary, Refresh snapshot, Play
    Loto, Play EuroMillions) keep reading the stale `data/people.yaml` /
    `data/snapshot.yaml` instead of the persons just entered.
    """
    if _save_people_yaml(notify=False):
        snap = st.session_state.get("snapshot_obj")
        if snap is not None:
            _save_snapshot_yaml(snap)


def _build_snapshot_from_session():
    """Return Snapshot object: session data first, file fallback, or None."""
    if "snapshot_obj" in st.session_state:
        return st.session_state["snapshot_obj"]
    loader = _import_loader()
    try:
        return loader.load_snapshot()
    except FileNotFoundError:
        return None


def _generate_direct(system_name: str) -> None:
    """Generate numbers using the Python engine directly (no subprocess)."""
    engine = _import_engine()
    snapshot = _build_snapshot_from_session()
    if snapshot is None:
        st.warning(
            "No person data available. Enter birth data in the sidebar and click "
            "**Fetch VedAstro data**, or save a `people.yaml` locally."
        )
        return

    try:
        result = engine.generate(system_name, snapshot)
    except Exception as exc:
        st.error(f"Generation failed: {exc}")
        return

    snap_dict = snapshot.as_context()
    _render_number_cards(result.main, result.magic, system_name, snap_dict)

    # Relationship summary (if present)
    if snapshot.relationship:
        rel = snapshot.relationship
        st.markdown("---")
        st.markdown(f"**Relationship influence ({rel.relation_type})**")
        event_label = "Marriage date" if rel.relation_type == "Married" else "Event date"
        st.caption(f"{event_label}: {rel.event_date}")
        if rel.transits_on_date:
            st.caption(
                "Planets on event date: "
                + ", ".join(
                    f"{PLANET_EMOJI.get(p.capitalize(), '')} {p.capitalize()}"
                    for p in rel.transits_on_date
                )
            )
        rel_nums: list[int] = []
        for planet_raw in rel.transits_on_date:
            from lucky_numbers.models import PLANET_NUMBER  # noqa: PLC0415
            pn = PLANET_NUMBER.get(str(planet_raw).capitalize())
            if pn:
                rel_nums += [n for n in range(pn, 51, pn)]
        if rel_nums:
            st.caption(
                f"Relationship planet seeds contributed: {sorted(set(rel_nums))[:12]}…"
            )

    st.markdown("### Current planet alignment (VedAstro snapshot)")
    _render_planet_table(snap_dict)

    _render_audit_trail(result.audit, default_open=False)


# ── page ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="Lucky Numbers", page_icon="🍀", layout="wide")

    # Sidebar must be rendered first so session_state keys exist before the rest
    _person_setup_sidebar()

    st.title("🍀 Lucky Numbers — Dashboard")
    st.caption(
    #    f"Repo: `{ROOT}`  |  "
        f"VedAstro snapshot: `{_snapshot_age()}`  |  "
        f"Loaded: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )

    # ── no-data banner ────────────────────────────────────────────────────────
    has_session_data = "snapshot_obj" in st.session_state
    if not has_session_data:
        st.info(
            "**Enter birth data in the sidebar → People & Relationship**, "
            "then click **Fetch VedAstro data**. "
            "Generate buttons will become active once the data is ready."
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
    st.header("Generate lucky numbers")

    # Access gate (free-trial counter + login form) — must be rendered BEFORE
    # the generate buttons so its state is up-to-date when we compute their
    # disabled flag below.
    _render_access_panel()

    # Show who will be used for generation
    if has_session_data:
        snap = st.session_state["snapshot_obj"]
        rel = snap.relationship
        p1_name = snap.self_.name
        rel_info = (
            f" · Relationship: **{rel.relation_type}** on {rel.event_date}"
            if rel else ""
        )
        num_p = 2 if snap.other else 1
        st.success(
            f"Using **{num_p} person(s)**: {p1_name}"
            + (f" & {snap.other.name}" if snap.other else "")
            + rel_info
        )
    else:
        st.caption("Generate buttons are disabled — fetch data in the sidebar first.")

    # Compute a single gate flag + tooltip used by every button below.
    can_use = _can_generate()
    gate_disabled = not has_session_data or not can_use
    if not has_session_data:
        gate_help = "Fetch VedAstro data in the sidebar first."
    elif not can_use:
        gate_help = ("Free trial used up — enter your access key in the panel "
                     "above to keep generating.")
    else:
        gate_help = None

    c1, c2, c3, c4 = st.columns(4)

    # --- generate (fast, direct Python engine) --------------------------------
    with c1:
        st.markdown("**Generate (fast)**")
        if has_session_data:
            st.caption("Data ready — pick a lottery system.")
        else:
            st.caption("Waiting for birth data…")

        if st.button("Generate Loto6", type="primary", use_container_width=True,
                     disabled=gate_disabled, help=gate_help):
            _consume_free_use()
            with st.spinner("Generating…"):
                _generate_direct("loto6")

        if st.button("Generate Euromillions", use_container_width=True,
                     disabled=gate_disabled, help=gate_help):
            _consume_free_use()
            with st.spinner("Generating…"):
                _generate_direct("euromillions")

        if st.button("Generate EuroJackpot", use_container_width=True,
                     disabled=gate_disabled, help=gate_help):
            _consume_free_use()
            with st.spinner("Generating…"):
                _generate_direct("eurojackpot")

    # --- play (full pipeline, CLI subprocess) ---------------------------------
    with c2:
        win_years = st.number_input(
            "Win-day years to enrich",
            min_value=1, max_value=10, value=1,
            help="How many recent years of jackpot-win days to pull from VedAstro.",
            key="win_years_input",
        )
        st.markdown("**Full pipeline (play)**")
        st.caption("Fetches history, enriches win-days, then generates.")

        if st.button("▶ Play Loto6", use_container_width=True,
                     disabled=gate_disabled, help=gate_help):
            _consume_free_use()
            with st.spinner("Running full play for loto6 (may take a few minutes)…"):
                out = _run_cli(["play", "loto6", "--win-years", str(int(win_years))])
            st.success("Done — see analysis below ↓")
            _render_play_result(out, "loto6")

        if st.button("▶ Play EuroMillions", use_container_width=True,
                     disabled=gate_disabled, help=gate_help):
            _consume_free_use()
            with st.spinner("Running full play for euromillions…"):
                out = _run_cli(["play", "euromillions", "--win-years", str(int(win_years))])
            st.success("Done — see analysis below ↓")
            _render_play_result(out, "euromillions")

    # --- VedAstro refresh (file-based snapshot) -------------------------------
    with c3:
        st.markdown("**VedAstro refresh (snapshot file)**")
        st.caption("Updates data/snapshot.yaml via CLI.")
        if st.button("Refresh snapshot", use_container_width=True,
                     disabled=not has_session_data):
            with st.spinner("Calling VedAstro…"):
                out = _run_cli(["refresh"])
            st.code(out)
            st.markdown("**Updated planet alignment:**")
            _render_planet_table(_load_snapshot())

        if st.button("Refresh + numerology", use_container_width=True,
                     disabled=not has_session_data):
            with st.spinner("Calling VedAstro…"):
                out = _run_cli(["refresh", "--numerology"])
            st.code(out)

        if st.button("Show snapshot summary", use_container_width=True,
                     disabled=not has_session_data):
            st.code(_run_cli(["show"]))
            st.markdown("**Current transits:**")
            _render_planet_table(_load_snapshot())

    # --- data pipeline -------------------------------------------------------
    with c4:
        st.markdown("**Data & rules**")
        win_years_data = st.session_state.get("win_years_input", 1)
        if st.button("Update draws + pots + analysis", use_container_width=True,
                     disabled=not has_session_data):
            with st.spinner("Downloading CSVs…"):
                o1 = _run_script("scripts/fetch_lottery_history.py")
                o2 = _run_script("scripts/fetch_pot_history_win2day.py")
                o3 = _run_script("scripts/analyze_pots_and_wins.py")
            st.code(o1 + "\n---\n" + o2 + "\n---\n" + o3)

        if st.button("Enrich win-days (VedAstro)", use_container_width=True,
                     disabled=not has_session_data):
            with st.spinner("Calling VedAstro for win days…"):
                out = _run_script(
                    "scripts/enrich_jackpot_wins_with_vedastro.py",
                    extra=["--years", str(int(win_years_data))],
                )
            st.code(out)

        if st.button("Rebuild win-day bias rules", use_container_width=True,
                     disabled=not has_session_data):
            o1 = _run_script("scripts/build_win_day_bias_rules.py")
            o2 = _run_script("scripts/build_win_day_astro_rules.py")
            st.code(o1 + "\n---\n" + o2)


if __name__ == "__main__":
    main()
