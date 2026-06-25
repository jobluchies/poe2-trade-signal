"""Gather all signals + metadata into one plain dict the renderers consume.

Renderers (markdown, html) stay dumb: they format this dict and nothing else.
All thresholds live here so the brief and the dashboard always agree.

Bucket A is per-category: the same signal set (momentum, movers, near-7d-low,
near-7d-high) is computed for every fungible exchange category and returned under
`fungible`, so the renderers can iterate categories generically — no copy-paste.
"""
from __future__ import annotations
from datetime import datetime, timezone

import config
from store import db
from fetchers.currency import derive_exalt_per_divine
from signals.momentum import currency_momentum
from signals.movers import currency_movers
from signals.items import unique_momentum, unique_movers
from signals.sparkline import trace_stats

# Value floor authored in EXALT, converted to a Divine threshold at compare time
# via the live Exalt:Divine rate — never compared against Divine values directly.
# Governs buy-candidate / position-in-range / momentum surfacing.
EXALT_FLOOR = 5.0

# Independent, higher floor authored in EXALT, applied ONLY to risers / movers-up.
# A mover worth flagging should clear a meaningfully higher bar than a buy
# candidate; also converted to Divine at filter time. No hardcoded Divine values.
RISER_FLOOR = 10.0

# Confidence gate for uniques. poe.ninja has no River API for PoE2, so unique
# prices are estimates — there is no lowConfidenceSparkline flag in the payload,
# so listing-count is the only available proxy. Suppress thin-listing items
# (price-fixer traps). Named + tunable.
UNIQUE_MIN_LISTINGS = 5


def _snapshot_count(con, league: str) -> int:
    row = con.execute(
        "SELECT COUNT(DISTINCT bucket) FROM currency_snapshot WHERE league = ?",
        (league,),
    ).fetchone()
    return row[0] if row else 0


def _entity_count(con, table: str, league: str) -> int:
    group = ("category, currency_id" if table == "currency_snapshot"
             else "item_type, details_id, corrupted")
    row = con.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} WHERE league = ? GROUP BY {group})",
        (league,),
    ).fetchone()
    return row[0] if row else 0


def _spread_pct(t: dict) -> float:
    """High/low spread of a trace as a % of its low (0 if undefined)."""
    lo, hi = t["low"], t["high"]
    return (hi - lo) / lo * 100.0 if lo else 0.0


def _currency_traces(rows) -> list[dict]:
    """Decoded 7-bucket price trace + range stats for every line's latest snapshot."""
    out: list[dict] = []
    for r in rows:
        st = trace_stats(r)
        if st is None:
            continue
        out.append({"category": r["category"], "currency_id": r["currency_id"],
                    "name": r["name"], "volume": r["volume"], **st})
    return out


def _above_value(rows: list[dict], value_key: str, min_value: float | None) -> list[dict]:
    """Drop rows whose price (Divine) is below min_value (a Divine threshold).

    `min_value is None` disables the floor entirely — used when no Exalt:Divine rate
    is available, so we keep everything and warn rather than filter on a garbage cut.
    """
    if min_value is None:
        return rows
    return [r for r in rows if (r.get(value_key) or 0) >= min_value]


def _risers(rows: list[dict], riser_min_divine: float | None) -> list[dict]:
    """Movers filter: keep only risers (positive %), above the riser floor.

    Decliners are dropped entirely (movers show up-moves only). The floor here is
    RISER_FLOOR-in-Divine, independent of the buy-candidate EXALT_FLOOR. With no
    usable rate (riser_min_divine is None) the floor is skipped but decliners are
    still dropped. Never touches buy-candidate / near-7d-low logic.
    """
    up = [r for r in rows if (r.get("pct") or 0) > 0]
    if riser_min_divine is None:
        return up
    return [r for r in up if (r.get("to") or 0) >= riser_min_divine]


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
            uniq_z: float = 2.0, uniq_min_listings: int = UNIQUE_MIN_LISTINGS,
            window_sec: int = 86400, top: int = 25,
            min_spread_pct: float = 5.0, min_value: float = EXALT_FLOOR,
            riser_floor: float = RISER_FLOOR) -> dict:
    now = config.now_ts()

    # Live Exalt:Divine rate from the Divine Orb line. Fallback chain: live line ->
    # DB last-known-good -> skip the floor (+ warn). Never a hardcoded constant. The
    # Divine Orb line lands under category='currency'; latest_currency(None) pools
    # all categories so it's still found.
    cur_rows = db.latest_currency(con, league)
    last_rate = db.get_last_rate(con, league)
    exalt_per_divine = derive_exalt_per_divine(cur_rows, last_known=last_rate)
    if exalt_per_divine is not None:
        db.set_last_rate(con, league, exalt_per_divine, now)

    # Both floors are authored in EXALT; convert to Divine thresholds. With no usable
    # rate we keep everything (None) and surface a warning rather than filter on a
    # garbage cut. min_value -> momentum/buy-candidate floor; riser_floor -> movers.
    rate_warning = None
    if exalt_per_divine:
        min_value_divine = min_value / exalt_per_divine
        riser_divine = riser_floor / exalt_per_divine
    else:
        min_value_divine = riser_divine = None
        rate_warning = ("No Exalt:Divine rate available (Divine Orb line missing/out "
                        "of band and no last-known-good) — value floors skipped this run.")

    # Per-category fungible groups — same signal set for every Bucket A category.
    # near-low/high use EXALT_FLOOR; movers use RISER_FLOOR and drop decliners.
    fungible: list[dict] = []
    for key, _exch_type, label in config.EXCHANGE_CATEGORIES:
        rows = db.latest_currency(con, league, key)
        traces = _above_value(_currency_traces(rows), "current", min_value_divine)
        near_low, near_high = _extremes(traces, "volume", cur_min_volume, min_spread_pct, top)
        mom = _above_value(currency_momentum(
            con, league, z_threshold=cur_z, min_volume=cur_min_volume, category=key),
            "primary_value", min_value_divine)
        mov = currency_movers(con, league, window_sec=window_sec, top=top, category=key)
        fungible.append({
            "key": key,
            "label": label,
            "momentum": _by_direction(mom[:top], "total_change_pct"),
            "movers": _by_direction(_risers(mov, riser_divine), "pct"),
            "near_low": near_low,
            "near_high": near_high,
        })

    # Uniques — Momentum (z-score) + Movers (risers only). No 7d low/high sections.
    uniq_momentum = _above_value(unique_momentum(
        con, league, z_threshold=uniq_z, min_listings=uniq_min_listings),
        "primary_value", min_value_divine)
    uniq_movers = _risers(unique_movers(
        con, league, window_sec=window_sec, top=top, min_listings=uniq_min_listings),
        riser_divine)

    live = sum(len(g["momentum"]) for g in fungible) + len(uniq_momentum)

    return {
        "league": league,
        "league_day": config.league_day(now),
        "generated_ts": now,
        "generated_iso": datetime.fromtimestamp(now, tz=timezone.utc)
                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_count": _snapshot_count(con, league),
        "currency_entities": _entity_count(con, "currency_snapshot", league),
        "unique_entities": _entity_count(con, "unique_snapshot", league),
        "live_signals": live,
        # Live display/floor context: Exalt per 1 Divine (None if unavailable), the
        # two Exalt-authored floors, and a warning when they had to be skipped.
        "exalt_per_divine": exalt_per_divine,
        "floor_exalt": min_value,
        "riser_floor_exalt": riser_floor,
        "rate_warning": rate_warning,
        "params": {
            "currency_z": cur_z, "currency_min_volume": cur_min_volume,
            "unique_z": uniq_z, "unique_min_listings": uniq_min_listings,
            "window_sec": window_sec, "top": top,
            "min_spread_pct": min_spread_pct,
            "min_value": min_value,       # buy-candidate floor, authored in Exalt
            "riser_floor": riser_floor,   # movers-up floor, authored in Exalt
        },
        # Bucket A: one group per fungible category, each with momentum / movers /
        # near_low / near_high. Renderers iterate this generically.
        "fungible": fungible,
        # Uniques: momentum + movers only (7d low/high deliberately removed).
        "unique_momentum": _by_direction(uniq_momentum[:top], "total_change_pct"),
        "unique_movers": _by_direction(uniq_movers, "pct"),
    }
