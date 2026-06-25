"""Intra-league movers — absolute % change of primary_value over a window.

Sourced from our own snapshot DB (not the sparkline). Empty until we have >1
snapshot spanning the window — that is correct; momentum covers the cold-start.
"""
from __future__ import annotations

import config
from store import db


def currency_movers(con, league: str = config.LEAGUE, window_sec: int = 86400,
                    top: int = 15, category: str | None = None) -> list[dict]:
    """Absolute %-change of primary_value over a window, from snapshot history.

    `category=None` pools all Bucket A categories; pass a key to scope to one.
    """
    now = config.now_ts()
    target = now - window_sec
    max_baseline_age = 2 * window_sec  # reject stale baselines reported as fresh
    out: list[dict] = []
    for _key, series in db.currency_series(con, league, category).items():
        latest = series[-1]
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
            "category": latest["category"],
            "currency_id": latest["currency_id"],
            "name": latest["name"],
            "pct": round(pct, 2),
            "from": b,
            "to": l,
            "baseline_ts": baseline["ts"],
            "latest_ts": latest["ts"],
        })
    out.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return out[:top]
