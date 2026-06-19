"""Layer C signals — unique item momentum + movers.

Same maths as the currency signals: sparkline z-score for run-#1 hot momentum,
and absolute %-change from our own snapshot history for movers. The confidence
gate here is `listing_count` (poe.ninja's thin-listing flag) rather than volume —
a 6000ex weapon with 2 listings is a price-fixer trap, not a signal.
"""
from __future__ import annotations
import json

import config
from store import db
from .momentum import sparkline_zscore


def unique_momentum(con, league: str = config.LEAGUE, z_threshold: float = 2.0,
                    min_listings: int = 3) -> list[dict]:
    """Flag uniques whose latest move is >z_threshold std vs their own 7d range.

    Confidence gate: drop entities with fewer than `min_listings` active listings.
    """
    out: list[dict] = []
    for r in db.latest_uniques(con, league):
        listings = r["listing_count"] or 0
        if listings < min_listings:
            continue
        try:
            data = json.loads(r["sparkline_json"] or "[]")
        except (TypeError, ValueError):
            continue
        z = sparkline_zscore(data)
        if z is None or abs(z) < z_threshold:
            continue
        out.append({
            "details_id": r["details_id"],
            "item_type": r["item_type"],
            "name": r["name"],
            "z": round(z, 2),
            "total_change_pct": r["spark_total_change"],
            "primary_value": r["primary_value"],
            "listing_count": listings,
        })
    out.sort(key=lambda x: abs(x["z"]), reverse=True)
    return out


def unique_movers(con, league: str = config.LEAGUE, window_sec: int = 86400,
                  top: int = 15, min_listings: int = 3) -> list[dict]:
    """Absolute %-change of primary_value over a window, from snapshot history.

    Empty until >=2 snapshots span the window — momentum covers the cold-start.
    """
    now = config.now_ts()
    target = now - window_sec
    max_baseline_age = 2 * window_sec  # reject stale baselines reported as fresh
    out: list[dict] = []
    for key, series in db.unique_series(con, league).items():
        latest = series[-1]
        if (latest["listing_count"] or 0) < min_listings:
            continue
        baseline = None
        for r in series:
            if r["ts"] <= target:
                baseline = r  # last row at or before the target time
        if baseline is None:
            continue
        if (now - baseline["ts"]) > max_baseline_age:
            continue
        b, l = baseline["primary_value"], latest["primary_value"]
        if not b or not l:
            continue
        pct = (l - b) / b * 100.0
        out.append({
            "details_id": latest["details_id"],
            "item_type": latest["item_type"],
            "name": latest["name"],
            "pct": round(pct, 2),
            "from": b,
            "to": l,
            "listing_count": latest["listing_count"],
            "baseline_ts": baseline["ts"],
            "latest_ts": latest["ts"],
        })
    out.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return out[:top]
