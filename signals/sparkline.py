"""Sparkline decoder — reconstruct absolute prices from a relative sparkline.

poe.ninja ships a fixed-length `sparkline.data` per line (7 points for PoE2): the
cumulative % change of each bucket's price vs a single window-start baseline B.

Verified live 2026-06-18 on HC Runes of Aldur — `data[-1] == sparkline.totalChange`
for all 43 currency lines. totalChange is the change over the whole window, so the
LAST bucket equals the total move and lines up with the current `primaryValue`.
That gives the only self-consistent anchor available without external calibration:

    B        = primary_value / (1 + data[-1] / 100)
    price[i] = B * (1 + data[i] / 100)

This is exactly what momentum.py deliberately declined to do (it z-scores the raw
% series and never leaves relative space). Use this when you want an absolute price
trace out of a single snapshot instead of waiting for accumulated movers history.

Caveats:
- Bucket cadence (seconds between points) is NOT confirmed by the API. Daily is the
  natural read for a multi-week league and is the default; treat reconstructed
  timestamps as approximate.
- If the window's total move is <= -100% the baseline is non-positive and the
  series cannot be anchored — decode returns [].
- Null buckets (poe.ninja emits them when a day has no trades) decode to None and
  keep their slot, so index alignment with `data` is preserved.
"""
from __future__ import annotations
import json
from typing import Optional, Sequence

BUCKET_SEC = 86400  # assumed 1 bucket == 1 day (not API-confirmed)


def _anchor_pct(data: Sequence) -> Optional[float]:
    """The cumulative %% the current price corresponds to: last non-null bucket."""
    for x in reversed(data):
        if isinstance(x, (int, float)):
            return float(x)
    return None


def decode_prices(data: Sequence, primary_value: Optional[float]) -> list[Optional[float]]:
    """Absolute price per sparkline bucket, anchored so the last bucket == primary_value.

    Returns one entry per element of `data` (None for null buckets). Returns [] when
    the series cannot be anchored (no value, empty data, or total move <= -100%).
    """
    if primary_value is None or not data:
        return []
    anchor = _anchor_pct(data)
    if anchor is None:
        return []
    denom = 1.0 + anchor / 100.0
    if denom <= 0:
        return []
    baseline = primary_value / denom
    return [baseline * (1.0 + x / 100.0) if isinstance(x, (int, float)) else None
            for x in data]


def decode_series(data: Sequence, primary_value: Optional[float], ref_ts: int,
                  interval_sec: int = BUCKET_SEC) -> list[dict]:
    """Decode to dated points. `ref_ts` is the snapshot time = the last bucket's time.

    Each point: {buckets_ago, ts (approx), pct (raw sparkline value), price}.
    """
    prices = decode_prices(data, primary_value)
    n = len(prices)
    out: list[dict] = []
    for i, price in enumerate(prices):
        ago = n - 1 - i
        out.append({
            "buckets_ago": ago,
            "ts": ref_ts - ago * interval_sec,
            "pct": data[i],
            "price": price,
        })
    return out


def decode_row(row, interval_sec: int = BUCKET_SEC) -> list[dict]:
    """Decode a snapshot DB row (sqlite Row or dict) with sparkline_json/primary_value/ts."""
    raw = row["sparkline_json"]
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return decode_series(data, row["primary_value"], row["ts"], interval_sec)


def trace_stats(row, interval_sec: int = BUCKET_SEC) -> Optional[dict]:
    """Decode one snapshot row into an absolute price trace plus range stats.

    The whole point: from a *single* snapshot you get a ~7-bucket absolute price
    window, so you can see where the current price sits in its own recent range —
    near the low (potential buy) or near the high (running hot) — before our own
    accumulated movers history is deep enough to say anything.

    Returns None when the series can't be anchored or has <2 real points.
    Keys: prices (with None for null buckets), low, high, current, range_pos
    (0 at low -> 1 at high), pct_from_low, pct_from_high, total_change_pct.
    """
    series = decode_row(row, interval_sec)
    prices_all = [pt["price"] for pt in series]
    prices = [p for p in prices_all if p is not None]
    if len(prices) < 2:
        return None
    cur = prices[-1]
    lo, hi = min(prices), max(prices)
    rng = hi - lo
    return {
        "prices": prices_all,
        "low": lo,
        "high": hi,
        "current": cur,
        "range_pos": (cur - lo) / rng if rng else None,
        "pct_from_low": (cur - lo) / lo * 100.0 if lo else None,
        "pct_from_high": (cur - hi) / hi * 100.0 if hi else None,
        "total_change_pct": series[-1]["pct"],
    }
