"""Acceptance tests for the live Exalt:Divine rate + 5-Exalt value floor.

Runs under pytest, or standalone: `python tests/test_rate_floor.py`.
Proves the task's acceptance criteria:
  - rate derived live from the Divine Orb line, guarded, falls back to last-known;
  - at 331:1, an item worth 4 Exalt is filtered, 6 Exalt is kept;
  - a bad/empty fetch with a last-known-good still applies the floor;
  - with no last-known-good the floor is skipped (kept everything), not garbage-cut.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetchers.currency import derive_exalt_per_divine
from report.collect import _above_value, EXALT_FLOOR


def _divine_line(mvr, pivot="exalted"):
    return {"name": "Divine Orb", "max_volume_currency": pivot, "max_volume_rate": mvr}


def test_rate_from_divine_line():
    # mvr is Divine-per-Exalt; exalt-per-divine is the reciprocal.
    assert round(derive_exalt_per_divine([_divine_line(0.011)]), 1) == 90.9
    assert round(derive_exalt_per_divine([_divine_line(1 / 331)]), 0) == 331


def test_rate_guards_fall_back():
    last = 331.0
    assert derive_exalt_per_divine([], last) == last                       # no line
    assert derive_exalt_per_divine([_divine_line(0.011, "divine")], last) == last  # wrong pivot
    assert derive_exalt_per_divine([_divine_line(0)], last) == last        # mvr 0
    assert derive_exalt_per_divine([_divine_line(0.0005)], last) == last   # 2000 ex/div: out of band
    assert derive_exalt_per_divine([_divine_line(0.05)], last) == last     # 20 ex/div: out of band
    # no last-known either -> None (caller must skip the floor, not filter)
    assert derive_exalt_per_divine([], None) is None


def test_floor_filters_at_live_rate():
    rate = 331.0
    min_value_divine = EXALT_FLOOR / rate                 # 5 Exalt expressed in Divine
    rows = [
        {"name": "four_ex", "current": 4 / rate},         # 4 Exalt -> below floor
        {"name": "six_ex", "current": 6 / rate},          # 6 Exalt -> above floor
    ]
    kept = {r["name"] for r in _above_value(rows, "current", min_value_divine)}
    assert kept == {"six_ex"}


def test_floor_skipped_when_no_rate():
    rows = [{"name": "cheap", "current": 0.0001}, {"name": "rich", "current": 9.0}]
    # min_value None => floor disabled => everything kept (warn surfaced by caller)
    assert len(_above_value(rows, "current", None)) == 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
