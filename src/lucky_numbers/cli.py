"""Command-line interface."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .engine import generate
from .loader import ROOT, load_snapshot

app = typer.Typer(add_completion=False, help="Vedic-numerology lottery numbers")
console = Console()


@app.command("generate")
def cmd_generate(
    system: str = typer.Argument(..., help="System name: loto6 | euromillions | eurojackpot"),
    explain: bool = typer.Option(False, "--explain", "-x", help="Show audit trail"),
):
    """Generate numbers for a system."""
    result = generate(system)

    main_str = "  ".join(f"[bold cyan]{n:>2}[/]" for n in result.main)
    console.print(f"\n[bold]System:[/] {system}")
    console.print(f"[bold]Main:[/]  {main_str}")
    if result.magic:
        magic_str = "  ".join(f"[bold magenta]{n:>2}[/]" for n in result.magic)
        console.print(f"[bold]Magic:[/] {magic_str}")

    if explain:
        table = Table(title="Audit trail", show_lines=False)
        table.add_column("Rule", style="cyan", no_wrap=True)
        table.add_column("Action")
        table.add_column("W", justify="right")
        table.add_column("Numbers")
        table.add_column("Reason", style="dim")
        for a in result.audit:
            nums = ", ".join(str(n) for n in a.numbers[:8])
            if len(a.numbers) > 8:
                nums += f", … (+{len(a.numbers)-8})"
            table.add_row(a.rule_id, a.action, str(a.weight), nums, a.reason)
        console.print(table)
    console.print()


def _estimate_win_likelihood(system: str, result) -> tuple[int, list[str]]:
    """
    Heuristic "win likelihood" score.
    It intentionally measures *match strength* between today's sky and historical jackpot-win patterns,
    not true lottery probability.
    """
    # Signals:
    # - astro matches: how many win-day sign-match rules fired today
    # - baseline overlap: how many generated numbers are in the win-day baseline list
    astro_matches = [a for a in result.audit if a.rule_id.startswith(f"win_day_sign_match_{system}_")]
    baseline = next((a for a in result.audit if a.rule_id == f"win_day_numbers_baseline_{system}"), None)
    baseline_nums = set(baseline.numbers) if baseline else set()

    main_overlap = len(set(result.main) & baseline_nums) if baseline_nums else 0
    magic_overlap = len(set(result.magic) & baseline_nums) if baseline_nums and result.magic else 0

    # Score composition (capped to 0..100)
    astro_score = min(60, len(astro_matches) * 20)  # 0,20,40,60+
    overlap_score = 0
    if result.main:
        overlap_score += int(30 * (main_overlap / len(result.main)))
    if result.magic:
        overlap_score += int(10 * (magic_overlap / max(1, len(result.magic))))

    score = max(0, min(100, astro_score + overlap_score))

    reasons: list[str] = []
    if astro_matches:
        reasons.append(f"{len(astro_matches)} win-day sky signature(s) matched today")
    else:
        reasons.append("No win-day sky signatures matched today")
    if baseline_nums:
        reasons.append(f"{main_overlap}/{len(result.main)} main number(s) are frequent on jackpot-win days")
        if result.magic:
            reasons.append(f"{magic_overlap}/{len(result.magic)} star/magic number(s) are frequent on jackpot-win days")
    else:
        reasons.append("Win-day baseline list not available (rules not built yet)")

    return score, reasons


def _run_repo_script(script_rel: str) -> None:
    script_path = (ROOT / script_rel).resolve()
    if not script_path.exists():
        raise RuntimeError(f"Missing script: {script_path}")
    subprocess.run([sys.executable, str(script_path)], check=True)


@app.command("play")
def cmd_play(
    system: str = typer.Argument(..., help="System name: loto6 | euromillions | eurojackpot"),
    explain: bool = typer.Option(False, "--explain", "-x", help="Show audit trail"),
    skip_history: bool = typer.Option(False, "--skip-history", help="Skip updating draw/pot history + rules"),
    win_years: int = typer.Option(1, "--win-years", min=1, help="How many recent years of jackpot win-days to enrich"),
):
    """
    One-command flow:
    1) Refresh today's VedAstro snapshot (transits+dasa)
    2) Update draw history + pot history, extract jackpot win-days, refresh win-day astrology rules
    3) Generate numbers and show a win-day match score (heuristic)
    """
    # 1) Always refresh today's sky (as requested)
    cmd_refresh(transits=True, dasa=True, numerology=False)

    # 2) Catch up missing draw dates + pot/win status + rebuild win-day rules
    if not skip_history:
        console.print("[cyan]→ updating historical draws/pots…[/]")
        _run_repo_script("scripts/fetch_lottery_history.py")
        _run_repo_script("scripts/fetch_pot_history_win2day.py")
        _run_repo_script("scripts/analyze_pots_and_wins.py")

        console.print("[cyan]→ enriching jackpot win-days (VedAstro)…[/]")
        script_path = (ROOT / "scripts" / "enrich_jackpot_wins_with_vedastro.py").resolve()
        subprocess.run([sys.executable, str(script_path), "--years", str(win_years)], check=True)

        console.print("[cyan]→ rebuilding win-day bias rules…[/]")
        _run_repo_script("scripts/build_win_day_bias_rules.py")
        _run_repo_script("scripts/build_win_day_astro_rules.py")

    # 3) Generate + score
    result = generate(system)

    main_str = "  ".join(f"[bold cyan]{n:>2}[/]" for n in result.main)
    console.print(f"\n[bold]System:[/] {system}")
    console.print(f"[bold]Main:[/]  {main_str}")
    if result.magic:
        magic_str = "  ".join(f"[bold magenta]{n:>2}[/]" for n in result.magic)
        console.print(f"[bold]Magic:[/] {magic_str}")

    score, reasons = _estimate_win_likelihood(system, result)
    console.print(f"\n[bold]Win-day match score:[/] {score}/100")
    for r in reasons:
        console.print(f"- {r}")

    if explain:
        table = Table(title="Audit trail", show_lines=False)
        table.add_column("Rule", style="cyan", no_wrap=True)
        table.add_column("Action")
        table.add_column("W", justify="right")
        table.add_column("Numbers")
        table.add_column("Reason", style="dim")
        for a in result.audit:
            nums = ", ".join(str(n) for n in a.numbers[:8])
            if len(a.numbers) > 8:
                nums += f", … (+{len(a.numbers)-8})"
            table.add_row(a.rule_id, a.action, str(a.weight), nums, a.reason)
        console.print(table)
    console.print()


@app.command("show")
def cmd_show():
    """Show the loaded snapshot summary."""
    s = load_snapshot()
    console.print("[bold]Father:[/]", s.self_.name, "—", s.self_.birth.location)
    console.print("[bold]Son:[/]", s.son.name, "—", s.son.birth.location)
    console.print("[bold]Father lagna:[/]", s.self_.natal.get("lagna_sign"))
    console.print("[bold]Son lagna:[/]", s.son.natal.get("lagna_sign"))
    console.print("[bold]Father dasa:[/]", s.dasa.get("self"))
    console.print("[bold]Son dasa:[/]", s.dasa.get("son"))
    console.print("[bold]Father Jupiter house (transit):[/]",
                  s.transits.get("self", {}).get("jupiter", {}).get("house"))


@app.command("refresh")
def cmd_refresh(
    transits: bool = typer.Option(True, "--transits/--no-transits", help="Refresh live transits"),
    dasa: bool = typer.Option(True, "--dasa/--no-dasa", help="Refresh active dasa"),
    numerology: bool = typer.Option(False, "--numerology", help="Refresh name-numerology blocks"),
):
    """Refresh transit/dasa/numerology blocks in data/snapshot.yaml from VedAstro."""
    from datetime import datetime, timezone as _tz
    from pathlib import Path
    import yaml

    from .loader import load_people, ROOT
    from .vedastro_client import VedAstroClient

    self_, son = load_people()
    snap_path: Path = ROOT / "data" / "snapshot.yaml"
    snap = yaml.safe_load(snap_path.read_text(encoding="utf-8"))

    def _ddmmyyyy(d) -> str:
        return f"{d.day:02d}/{d.month:02d}/{d.year}"

    with VedAstroClient() as v:
        for label, person in [("self", self_), ("son", son)]:
            if transits:
                console.print(f"[cyan]→ transits ({label})…[/]")
                res = v.transits(
                    _ddmmyyyy(person.birth.date), person.birth.time,
                    person.birth.latitude, person.birth.longitude, person.birth.timezone,
                )
                # Normalize: vedastro returns {"GocharaKakshas": {...}}
                content = _unwrap(res)
                gk = content.get("GocharaKakshas", content)
                snap.setdefault("transits", {})[label] = _normalize_transits(
                    gk, person.natal.get("lagna_sign_index", 1) if person.natal else 1
                )

            if dasa:
                console.print(f"[cyan]→ dasa ({label})…[/]")
                res = v.current_dasa(
                    _ddmmyyyy(person.birth.date), person.birth.time,
                    person.birth.latitude, person.birth.longitude, person.birth.timezone,
                    query=f"current dasa for {person.name}",
                )
                content = _unwrap(res)
                snap.setdefault("dasa", {})[label] = _extract_dasa(content)

            if numerology:
                console.print(f"[cyan]→ numerology ({person.name})…[/]")
                res = v.numerology(person.name)
                content = _unwrap(res)
                pred = content.get("NameNumberPrediction", content)
                snap.setdefault(label, {}).setdefault("numerology", {}).update({
                    "name": person.name,
                    "name_number": pred.get("Number"),
                    "root_number": pred.get("RootNumber"),
                    "ruling_planet": pred.get("Planet"),
                })

    snap["generated_at"] = datetime.now(_tz.utc).isoformat()
    snap_path.write_text(yaml.safe_dump(snap, sort_keys=False), encoding="utf-8")
    console.print(f"[green]✓ snapshot updated:[/] {snap_path}")


# ---- helpers --------------------------------------------------------------

def _unwrap(rpc_result: dict) -> dict:
    """Unwrap MCP tools/call result envelope into raw payload dict."""
    import json
    content = rpc_result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                return json.loads(first["text"])
            except Exception:
                return {"raw": first["text"]}
    return rpc_result if isinstance(rpc_result, dict) else {}


_SIGN_TO_INDEX = {
    "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
    "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
    "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12,
}


def _normalize_transits(gk: dict, lagna_index: int) -> dict:
    """Convert VedAstro Gochara payload → engine-friendly dict."""
    out = {}
    for planet, data in gk.items():
        sign = data.get("Sign", "Aries")
        sign_idx = _SIGN_TO_INDEX.get(sign, 1)
        house = ((sign_idx - lagna_index) % 12) + 1
        out[planet.lower()] = {
            "sign": sign,
            "house": house,
            "kaksha": int(data.get("KakshaScore", 0)),
            "ashtaka": int(data.get("Ashtaka", 0)),
            "sarvashtaka": int(data.get("Sarvashtaka", 0)),
        }
    return out


def _extract_dasa(payload: dict) -> dict:
    """Best-effort parse of VedAstro current_dasa payload."""
    levels = payload.get("levels") or []
    out = {"mahadasa": None, "bhukti": None, "antara": None}
    label_map = {"Dasa": "mahadasa", "Mahadasha": "mahadasa",
                 "Bhukti": "bhukti", "Antaram": "antara", "Antara": "antara"}
    for lvl in levels:
        key = label_map.get(lvl.get("level"))
        if key:
            out[key] = lvl.get("planet")
    return out


def main():  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

