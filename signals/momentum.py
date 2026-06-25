"""Hot momentum — z-score of the latest point within a line's own 7-day sparkline.

Live from run #1: the sparkline ships in every overview, so this needs none of our
accumulated history. Sparkline is RELATIVE (% movement) — used only for momentum,
never reconstructed into absolute prices.
"""
from __future__ import annotations
import json
import statistics
from typing import Optional

import config
from store import db


def sparkline_zscore(data: list[float]) -> Optional[float]:
    """z of the most recent sparkline point vs the series' own mean/std.

    poe.ninja sparklines can contain nulls (no data for that bucket); drop them.
    """
    clean = [x for x in (data or []) if isinstance(x, (int, float))]
    if len(clean) < 3:
        return None
    sd = statistics.pstdev(clean)
    if sd == 0:
        return None
    return (clean[-1] - statistics.fmean(clean)) / sd


def currency_momentum(con, league: str = config.LEAGUE, z_threshold: float = 2.0,
                      min_volume: float = 0.0, category: str | None = None) -> list[dict]:
    """Flag exchange items whose latest move is >z_threshold std vs their own range.

    Confidence gate: drop lines below `min_volume` (thin volume = likely price-fixer).
    `category=None` pools all Bucket A categories; pass a key to scope to one.
    """
    out: list[dict] = []
    for r in db.latest_currency(con, league, category):
        vol = r["volume"] or 0.0
        if vol < min_volume:
            continue
        try:
            data = json.loads(r["sparkline_json"] or "[]")
        except (TypeError, ValueError):
            continue
        z = sparkline_zscore(data)
        if z is None or abs(z) < z_threshold:
            continue
        out.append({
            "category": r["category"],
            "currency_id": r["currency_id"],
            "name": r["name"],
            "z": round(z, 2),
            "total_change_pct": r["spark_total_change"],
            "primary_value": r["primary_value"],
            "volume": vol,
        })
    out.sort(key=lambda x: abs(x["z"]), reverse=True)
    return out
