"""Gather all signals + metadata into one plain dict the renderers consume.

Renderers (markdown, html) stay dumb: they format this dict and nothing else.
All thresholds live here so the brief and the dashboard always agree.
"""
from __future__ import annotations
from datetime import datetime, timezone

import config
from store import db
from signals.momentum import currency_momentum
from signals.movers import currency_movers
from signals.items import unique_momentum, unique_movers
from signals.sparkline import trace_stats


def _snapshot_count(con, league: str) -> int:
    row = con.execute(
        "SELECT COUNT(DISTINCT bucket) FROM currency_snapshot WHERE league = ?",
        (league,),
    ).fetchone()
    return row[0] if row else 0


def _entity_count(con, table: str, league: str) -> int:
    group = "currency_id" if table == "currency_snapshot" else "item_type, details_id, corrupted"
    row = con.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} WHERE league = ? GROUP BY {group})",
        (league,),
    ).fetchone()
    return row[0] if row else 0


def _spread_pct(t: dict) -> float:
    """High/low spread of a trace as a % of its low (0 if undefined)."""
    lo, hi = t["low"], t["high"]
    return (hi - lo) / lo * 100.0 if lo else 0.0


def _currency_traces(con, league: str) -> list[dict]:
    """Decoded 7-bucket price trace + range stats for every currency's latest snapshot."""
    out: list[dict] = []
    for r in db.latest_currency(con, league):
        st = trace_stats(r)
        if st is None:
            continue
        out.append({"currency_id": r["currency_id"], "name": r["name"],
                    "volume": r["volume"], **st})
    return out


def _unique_traces(con, league: str) -> list[dict]:
    """Decoded 7-bucket price trace + range stats for every unique's latest snapshot."""
    out: list[dict] = []
    for r in db.latest_uniques(con, league):
        st = trace_stats(r)
        if st is None:
            continue
        out.append({"item_type": r["item_type"], "name": r["name"],
                    "listing_count": r["listing_count"], **st})
    return out


def _above_value(rows: list[dict], value_key: str, min_value: float) -> list[dict]:
    """Drop rows whose price (in exalted orbs) is below min_value."""
    return [r for r in rows if (r.get(value_key) or 0) >= min_value]


def _by_direction(rows: list[dict], pct_key: str) -> list[dict]:
    """Order for display: biggest risers first, biggest fallers last.

    Signed descending sort. Selection (which rows survive `top`) still happens by
    absolute magnitude upstream, so both ends stay visible — this only reorders.
    """
    return sorted(rows, key=lambda r: (r.get(pct_key) or 0), reverse=True)


def _extremes(traces: list[dict], gate_key: str, gate_min: float,
              min_spread_pct: float, top: int) -> tuple[list[dict], list[dict]]:
    """Split traces into near-7d-low (buy candidates) and near-7d-high (running hot).

    Only entities that pass the confidence gate AND actually moved (>= min_spread_pct
    high/low spread) qualify — a flat line has no meaningful range position.
    """
    elig = [t for t in traces
            if (t.get(gate_key) or 0) >= gate_min
            and t["range_pos"] is not None
            and _spread_pct(t) >= min_spread_pct]
    near_low = sorted(elig, key=lambda t: t["range_pos"])[:top]
    near_high = sorted(elig, key=lambda t: t["range_pos"], reverse=True)[:top]
    return near_low, near_high


def collect(con, league: str = config.LEAGUE, *,
            cur_z: float = 2.0, cur_min_volume: float = 1.0,
            uniq_z: float = 2.0, uniq_min_listings: int = 5,
            window_sec: int = 86400, top: int = 25,
            min_spread_pct: float = 5.0, min_value: float = 5.0) -> dict:
    now = config.now_ts()
    # Price floor (exalted orbs): hide low-value noise from every section. The
    # value field differs per signal — `current` for traces, `primary_value` for
    # momentum, `to` (latest price) for movers — so filter each by its own key.
    cur_traces = _above_value(_currency_traces(con, league), "current", min_value)
    uniq_traces = _above_value(_unique_traces(con, league), "current", min_value)
    cur_low, cur_high = _extremes(cur_traces, "volume", cur_min_volume, min_spread_pct, top)
    uniq_low, uniq_high = _extremes(uniq_traces, "listing_count", uniq_min_listings, min_spread_pct, top)
    cur_momentum = _above_value(currency_momentum(
        con, league, z_threshold=cur_z, min_volume=cur_min_volume), "primary_value", min_value)
    uniq_momentum = _above_value(unique_momentum(
        con, league, z_threshold=uniq_z, min_listings=uniq_min_listings), "primary_value", min_value)
    cur_movers = _above_value(currency_movers(
        con, league, window_sec=window_sec, top=top), "to", min_value)
    uniq_movers = _above_value(unique_movers(
        con, league, window_sec=window_sec, top=top, min_listings=uniq_min_listings), "to", min_value)
    return {
        "league": league,
        "league_day": config.league_day(now),
        "generated_ts": now,
        "generated_iso": datetime.fromtimestamp(now, tz=timezone.utc)
                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_count": _snapshot_count(con, league),
        "currency_entities": _entity_count(con, "currency_snapshot", league),
        "unique_entities": _entity_count(con, "unique_snapshot", league),
        "params": {
            "currency_z": cur_z, "currency_min_volume": cur_min_volume,
            "unique_z": uniq_z, "unique_min_listings": uniq_min_listings,
            "window_sec": window_sec, "top": top,
            "min_spread_pct": min_spread_pct, "min_value": min_value,
        },
        "currency_momentum": _by_direction(cur_momentum[:top], "total_change_pct"),
        "currency_movers": _by_direction(cur_movers, "pct"),
        "unique_momentum": _by_direction(uniq_momentum[:top], "total_change_pct"),
        "unique_movers": _by_direction(uniq_movers, "pct"),
        # Sparkline-decoded absolute price traces — full set for every entity, plus
        # range-position extremes (where today sits in its own 7-bucket window).
        "currency_traces": cur_traces,
        "unique_traces": uniq_traces,
        "currency_near_low": cur_low,
        "currency_near_high": cur_high,
        "unique_near_low": uniq_low,
        "unique_near_high": uniq_high,
    }
