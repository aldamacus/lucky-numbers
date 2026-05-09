"""Load YAML config files into typed objects."""
from __future__ import annotations

from datetime import date as _date, datetime
from pathlib import Path
from typing import Any

import yaml

from .models import Birth, Person, RelationshipData, Snapshot

ROOT = Path(__file__).resolve().parents[2]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_people(people_yaml: Path | None = None) -> tuple[Person, Person]:
    """Return (self_, other). Falls back to legacy `son:` key for old files."""
    path = people_yaml or ROOT / "data" / "people.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"people.yaml not found at {path}. "
            "Enter your birth data in the UI sidebar and click 'Fetch VedAstro data'."
        )
    data = _read_yaml(path)["people"]
    other_data = data.get("other") or data.get("son")
    if other_data is None:
        # Single-person config: alias other to self
        other_data = data["self"]
    return _person(data["self"]), _person(other_data)


def build_person(d: dict[str, Any]) -> Person:
    """Construct a Person from a plain dict (e.g. from session-state form data)."""
    return _person(d)


def _person(d: dict[str, Any]) -> Person:
    b = d["birth"]
    birth = Birth(
        date=datetime.strptime(b["date"], "%Y-%m-%d").date(),
        time=b["time"],
        timezone=b["timezone"],
        location=b["location"],
        latitude=float(b["latitude"]),
        longitude=float(b["longitude"]),
    )
    return Person(name=d["name"], role=d["role"], birth=birth)


def _normalise_subject_keys(d: dict[str, Any] | None) -> dict[str, Any]:
    """Translate legacy 'son' subject keys to 'other'.

    Existing snapshots, caches and pipeline outputs use either `son` (old
    canonical name) or `other` (new canonical name). Reading code only ever
    looks for `other` after this normalisation step, simplifying the rest of
    the codebase.
    """
    if not isinstance(d, dict):
        return d or {}
    out: dict[str, Any] = {}
    for k, v in d.items():
        out["other" if k == "son" else k] = v
    return out


def _parse_relationship(rel_block: Any) -> RelationshipData | None:
    """Parse a YAML relationship block into a RelationshipData object.

    Critical for parity between the UI 'Generate' button (which uses the
    in-memory snapshot complete with relationship) and the 'Play' / CLI
    pipeline (which round-trips through data/snapshot.yaml). Without this,
    the CLI loses the relationship-planet harmonics (weight 3) and the
    relationship part of the deterministic seed, producing different
    numbers from the UI's Generate button.
    """
    if not isinstance(rel_block, dict):
        return None
    raw_date = rel_block.get("date")
    if isinstance(raw_date, _date):
        event_date = raw_date
    elif isinstance(raw_date, str) and raw_date.strip():
        try:
            event_date = _date.fromisoformat(raw_date)
        except ValueError:
            return None
    else:
        return None
    return RelationshipData(
        relation_type=str(rel_block.get("type", "") or ""),
        event_date=event_date,
        transits_on_date=rel_block.get("transits_on_date") or {},
    )


def load_snapshot(
    snapshot_yaml: Path | None = None,
    people_yaml: Path | None = None,
) -> Snapshot:
    self_, other = load_people(people_yaml)
    snap_path = snapshot_yaml or ROOT / "data" / "snapshot.yaml"
    if not snap_path.exists():
        return Snapshot(self_=self_, transits={}, dasa={}, other=other)
    snap = _read_yaml(snap_path)
    self_.numerology = snap.get("self", {}).get("numerology", {})
    self_.natal      = snap.get("self", {}).get("natal", {})
    other_block = snap.get("other") or snap.get("son") or {}
    other.numerology = other_block.get("numerology", {})
    other.natal      = other_block.get("natal", {})
    return Snapshot(
        self_=self_,
        other=other,
        transits=_normalise_subject_keys(snap.get("transits", {})),
        dasa=_normalise_subject_keys(snap.get("dasa", {})),
        relationship=_parse_relationship(snap.get("relationship")),
    )


def build_snapshot_from_dicts(
    self_data: dict[str, Any],
    other_data: dict[str, Any] | None,
    transits: dict[str, Any] | None = None,
    dasa: dict[str, Any] | None = None,
    relationship: dict[str, Any] | None = None,
) -> Snapshot:
    """Build a Snapshot purely from dicts (no YAML files needed — used by the UI)."""
    self_ = build_person(self_data)
    return Snapshot(
        self_=self_,
        other=build_person(other_data) if other_data else None,
        transits=_normalise_subject_keys(transits),
        dasa=_normalise_subject_keys(dasa),
        relationship=_parse_relationship(relationship),
    )


def load_systems(path: Path | None = None) -> dict[str, Any]:
    return _read_yaml(path or ROOT / "configs" / "systems.yaml")["systems"]


def load_rule_files(rules_dir: Path | None = None) -> list[dict[str, Any]]:
    """Returns a flat list of rule dicts (seeds + modifiers) in load order."""
    rdir = rules_dir or ROOT / "rules"
    out: list[dict[str, Any]] = []
    for p in sorted(rdir.glob("*.yaml")):
        data = _read_yaml(p) or {}
        for key in ("seeds", "modifiers"):
            for r in data.get(key, []) or []:
                r.setdefault("kind", key)
                r.setdefault("source_file", p.name)
                out.append(r)
    return out

