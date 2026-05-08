"""Load YAML config files into typed objects."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import Birth, Person, Snapshot

ROOT = Path(__file__).resolve().parents[2]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_people(people_yaml: Path | None = None) -> tuple[Person, Person]:
    path = people_yaml or ROOT / "data" / "people.yaml"
    data = _read_yaml(path)["people"]
    return _person(data["self"]), _person(data["son"])


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


def load_snapshot(
    snapshot_yaml: Path | None = None,
    people_yaml: Path | None = None,
) -> Snapshot:
    self_, son = load_people(people_yaml)
    snap = _read_yaml(snapshot_yaml or ROOT / "data" / "snapshot.yaml")
    self_.numerology = snap["self"].get("numerology", {})
    self_.natal      = snap["self"].get("natal", {})
    son.numerology   = snap["son"].get("numerology", {})
    son.natal        = snap["son"].get("natal", {})
    return Snapshot(
        self_=self_,
        son=son,
        transits=snap.get("transits", {}),
        dasa=snap.get("dasa", {}),
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

