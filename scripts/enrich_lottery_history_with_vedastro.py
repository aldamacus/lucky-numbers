from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from lucky_numbers.loader import ROOT, load_people
from lucky_numbers.vedastro_client import VedAstroClient


HIST_DIR = ROOT / "data" / "historical"
ENRICH_DIR = HIST_DIR / "planet_adjustments"
POTS_DIR = HIST_DIR / "pots"


def _load_pots(game: str) -> dict[str, dict[str, Any]]:
    """
    Load pot/jackpot metadata keyed by ISO date.
    Produced by scripts/fetch_pot_history_win2day.py
    """
    path = POTS_DIR / f"{game}_pots.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = r.get("date")
        if not d:
            continue
        out[d] = {
            "jackpot_eur": int(r["jackpot_eur"]) if r.get("jackpot_eur") else None,
            "jackpot_won": r.get("jackpot_won") == "1",
            "jackpot_winners": int(r["jackpot_winners"]) if r.get("jackpot_winners") else None,
            "source": r.get("source"),
        }
    return out


def _ddmmyyyy(iso_yyyy_mm_dd: str) -> str:
    d = datetime.strptime(iso_yyyy_mm_dd, "%Y-%m-%d").date()
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _unwrap(rpc_result: dict) -> dict:
    # Same envelope style as in lucky_numbers.cli.refresh helpers
    content = rpc_result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                return json.loads(first["text"])
            except Exception:
                return {"raw": first["text"]}
    return rpc_result if isinstance(rpc_result, dict) else {}


def _read_last_n_rows(csv_path: Path, n: int) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-n:] if n > 0 else rows


def _birth_to_jsonable(birth) -> dict[str, Any]:
    d = asdict(birth)
    # dataclass Birth includes a datetime.date which isn't JSON serializable
    if "date" in d and hasattr(d["date"], "isoformat"):
        d["date"] = d["date"].isoformat()
    return d


def enrich(
    game: str,
    source_csv: Path,
    *,
    last_n: int = 50,
    check_time: str = "21:00",
    check_location_name: str = "Vienna, Austria",
    check_latitude: float = 48.2082,
    check_longitude: float = 16.3738,
    check_timezone: str = "+01:00",
) -> Path:
    """
    Enrich draw dates with VedAstro "planet adjustments".

    We store:
    - dasa at time for self + son (deterministic for that date)
    - a context-based current-sky query (positions/retrograde/yogas etc) at the draw date/time
    """
    self_, son = load_people()
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ENRICH_DIR / f"{game}_last_{last_n}_draws.jsonl"

    rows = _read_last_n_rows(source_csv, last_n)
    pots_by_date = _load_pots(game)

    # Context-based tool calls can be slower; use a longer timeout.
    with VedAstroClient(timeout=90.0) as v, out_path.open("w", encoding="utf-8") as out:
        for idx, r in enumerate(rows, start=1):
            iso_date = r["date"]
            check_date = _ddmmyyyy(iso_date)

            dasa_self: dict[str, Any] = {}
            dasa_son: dict[str, Any] = {}
            dasa_err: str | None = None
            try:
                dasa_self = _unwrap(v.call("get_dasa_at_time", {
                    "birth_date": _ddmmyyyy(self_.birth.date.isoformat()),
                    "birth_time": self_.birth.time,
                    "latitude": str(self_.birth.latitude),
                    "longitude": str(self_.birth.longitude),
                    "timezone": self_.birth.timezone,
                    "query_text": f"dasa at {check_date} {check_time}",
                    "check_date": check_date,
                    "check_time": check_time,
                    "levels": 3,
                }))

                dasa_son = _unwrap(v.call("get_dasa_at_time", {
                    "birth_date": _ddmmyyyy(son.birth.date.isoformat()),
                    "birth_time": son.birth.time,
                    "latitude": str(son.birth.latitude),
                    "longitude": str(son.birth.longitude),
                    "timezone": son.birth.timezone,
                    "query_text": f"dasa at {check_date} {check_time}",
                    "check_date": check_date,
                    "check_time": check_time,
                    "levels": 3,
                }))
            except Exception as e:
                dasa_err = f"{type(e).__name__}: {e}"

            # Generic, birth-agnostic "current sky" query at the draw date
            ctx_sky: dict[str, Any] = {}
            ctx_err: str | None = None
            for _attempt in range(3):
                try:
                    ctx_sky = _unwrap(v.call("get_context_based_astrology_data", {
                        "query": (
                            "Planetary positions and notable transit factors at "
                            f"{check_date} {check_time} for lottery draw analysis."
                        ),
                        "check_date": check_date,
                        "check_time": check_time,
                        "check_latitude": str(check_latitude),
                        "check_longitude": str(check_longitude),
                        "check_timezone": check_timezone,
                        "check_location_name": check_location_name,
                    }))
                    ctx_err = None
                    break
                except Exception as e:
                    ctx_err = f"{type(e).__name__}: {e}"

            record: dict[str, Any] = {
                "game": game,
                "date": iso_date,
                "row_index": idx,
                "draw": r,
                "pot": pots_by_date.get(iso_date),
                "check": {
                    "date": check_date,
                    "time": check_time,
                    "location_name": check_location_name,
                    "latitude": check_latitude,
                    "longitude": check_longitude,
                    "timezone": check_timezone,
                },
                "self": {"name": self_.name, "birth": _birth_to_jsonable(self_.birth), "dasa_at_time": dasa_self},
                "son": {"name": son.name, "birth": _birth_to_jsonable(son.birth), "dasa_at_time": dasa_son},
                "dasa_error": dasa_err,
                "sky": ctx_sky,
                "sky_error": ctx_err,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

    return out_path


if __name__ == "__main__":
    # Default: enrich latest 50 draws for both.
    eu_csv = HIST_DIR / "euromillions_results.csv"
    at_csv = HIST_DIR / "austria_lotto_6aus45_results.csv"
    if not eu_csv.exists() or not at_csv.exists():
        raise SystemExit("Missing historical CSVs. Run: python scripts/fetch_lottery_history.py")

    p1 = enrich("euromillions", eu_csv, last_n=50)
    print(f"✓ wrote {p1}")
    p2 = enrich("austria_lotto_6aus45", at_csv, last_n=50)
    print(f"✓ wrote {p2}")

