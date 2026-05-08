"""Smoke tests — confirm both systems generate the right shape."""
from __future__ import annotations

from lucky_numbers.engine import generate


def test_eurojackpot_shape():
    r = generate("eurojackpot")
    assert r.system == "eurojackpot"
    assert len(r.main) == 5
    assert all(1 <= n <= 40 for n in r.main)
    assert len(set(r.main)) == 5
    assert len(r.magic) == 2
    assert all(1 <= n <= 10 for n in r.magic)
    assert len(set(r.magic)) == 2


def test_loto6_shape():
    r = generate("loto6")
    assert r.system == "loto6"
    assert len(r.main) == 6
    assert all(1 <= n <= 46 for n in r.main)
    assert len(set(r.main)) == 6
    assert r.magic == []


def test_deterministic():
    a = generate("eurojackpot")
    b = generate("eurojackpot")
    assert a.main == b.main
    assert a.magic == b.magic


def test_audit_trail_present():
    r = generate("loto6")
    assert len(r.audit) > 0
    assert any("Lagna" in e.reason or "lagna" in e.reason for e in r.audit)

