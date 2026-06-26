"""Gather all signals + metadata into one plain dict the renderers consume.

Renderers (markdown, html) stay dumb: they format this dict and nothing else.
All thresholds live here so the brief and the dashboard always agree.

Bucket A is per-category: the same signal set (movers, momentum) is computed for
every fungible exchange category and returned under `fungible`, so the renderers
can iterate categories generically — no copy-paste. Movers carry a decoded
sparkline trace (latest snapshot) for an at-a-glance price shape.
"""
from __future__ import annotations
import math
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

# Movers embed floor, authored in EXALT, applied to risers / movers-up for BOTH
# Bucket A and uniques. This is now only a JSON-inclusion junk-cutoff: rows below
# it never reach the page, but rows above it are baked in and the *display* floor
# is the client-side slider (min == this value). Converted to Divine at filter
# time via the live rate; no hardcoded Divine values. Replaces the old split
# RISER_FLOOR (10, uniques) / BUCKET_A_RISER_FLOOR (2, Bucket A) — unified at 5.
MOVERS_EMBED_FLOOR = 5.0

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


def _spark_by_id(traces: list[dict], key: str) -> dict:
    """Map entity id -> decoded price trace, for hanging a sparkline on mover rows."""
    return {t[key]: t.get("prices") for t in traces}


def _snap_traces(series_map: dict, keyfn, now: int, window_sec: int) -> dict:
    """Trailing-window primary_value path per entity, from our OWN snapshots.

    Oldest-first list of recorded prices within the last `window_sec`, keyed by
    keyfn(row). This is the snapshot-based companion to the poe.ninja sparkline:
    the actual intra-window path we observed, not the vendor's daily series. Sparse
    until enough hourly snapshots land inside the window — that is expected.
    """
    cutoff = now - window_sec
    out: dict = {}
    for rows in series_map.values():
        recent = [r for r in rows if r["ts"] >= cutoff]
        if not recent:
            continue
        out[keyfn(recent[0])] = [r["primary_value"] for r in recent]
    return out


def _attach_spark(movers: list[dict], spark: dict, keyfn, field: str = "prices") -> list[dict]:
    """Hang a price trace on each mover row under `field` (None when unavailable)."""
    for m in movers:
        m[field] = spark.get(keyfn(m))
    return movers


def _above_value(rows: list[dict], value_key: str, min_value: float | None) -> list[dict]:
    """Drop rows whose price (Divine) is below min_value (a Divine threshold).

    `min_value is None` disables the floor entirely — used when no Exalt:Divine rate
    is available, so we keep everything and warn rather than filter on a garbage cut.
    """
    if min_value is None:
        return rows
    return [r for r in rows if (r.get(value_key) or 0) >= min_value]


def _risers(rows: list[dict], riser_min_divine: float | None) -> list[dict]:
    """Movers filter: keep only risers (positive %), above the embed floor.

    Decliners are dropped entirely (movers show up-moves only). The floor here is
    MOVERS_EMBED_FLOOR-in-Divine, independent of the buy-candidate EXALT_FLOOR, and
    is now just a junk-cutoff for the embedded payload — the live display floor is
    the client slider. With no usable rate (riser_min_divine is None) the floor is
    skipped but decliners are still dropped. Never touches buy-candidate logic.
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


def _nice_ceiling(x: float) -> float:
    """Round x up to the next 1/2/5 × 10ⁿ — a clean top end for the value slider."""
    if x <= 0:
        return 10.0
    exp = math.floor(math.log10(x))
    base = 10.0 ** exp
    for m in (1, 2, 5, 10):
        if x <= m * base:
            return m * base
    return 10 * base


def _movers_max_exalt(fungible: list[dict], uniques: list[dict],
                      rate: float | None) -> float | None:
    """Highest embedded mover value in EXALT, rounded up to a clean slider ceiling.

    None when there's no rate (no slider). Movers carry `to` in Divine; convert via
    the live rate. Ceiling is kept strictly above the slider min (5 ex) so the top
    of the range is always reachable even when every mover is cheap.
    """
    if not rate:
        return None
    tos = [m.get("to") for g in fungible for m in g["movers"]]
    tos += [m.get("to") for m in uniques]
    top_div = max((t for t in tos if t is not None), default=0.0)
    return max(_nice_ceiling(top_div * rate), 2 * MOVERS_EMBED_FLOOR)


def collect(con, league: str = config.LEAGUE, *,
            cur_z: float = 2.0, cur_min_volume: float = 1.0,
            uniq_z: float = 2.0, uniq_min_listings: int = UNIQUE_MIN_LISTINGS,
            window_sec: int = 86400, top: int = 25,
            min_value: float = EXALT_FLOOR,
            movers_floor: float = MOVERS_EMBED_FLOOR) -> dict:
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
    # garbage cut. min_value -> momentum/buy-candidate floor; movers_floor -> the
    # single movers embed cut (Bucket A + uniques), then the client slider re-filters.
    rate_warning = None
    if exalt_per_divine:
        min_value_divine = min_value / exalt_per_divine
        movers_divine = movers_floor / exalt_per_divine
    else:
        min_value_divine = movers_divine = None
        rate_warning = ("No Exalt:Divine rate available (Divine Orb line missing/out "
                        "of band and no last-known-good) — value floors skipped this run.")

    # Per-category fungible groups — movers (primary) + momentum for every Bucket A
    # category. Bucket A movers drop decliners and apply the unified MOVERS_EMBED_FLOOR
    # (junk-cutoff only; the slider is the real display floor). Momentum keeps EXALT_FLOOR.
    fungible: list[dict] = []
    for key, _exch_type, label in config.EXCHANGE_CATEGORIES:
        rows = db.latest_currency(con, league, key)
        # Two traces per mover row: poe.ninja's ~7d daily sparkline (vendor `spark`)
        # and our own trailing-window snapshot path (`snap`). No value filter —
        # movers gate themselves on the riser floor.
        spark = _spark_by_id(_currency_traces(rows), "currency_id")
        snap = _snap_traces(db.currency_series(con, league, key),
                            lambda r: r["currency_id"], now, window_sec)
        # Bucket A movers gate on the unified MOVERS_EMBED_FLOOR (same as uniques).
        mom = _above_value(currency_momentum(
            con, league, z_threshold=cur_z, min_volume=cur_min_volume, category=key),
            "primary_value", min_value_divine)
        mov = _risers(
            currency_movers(con, league, window_sec=window_sec, top=top, category=key),
            movers_divine)  # unified movers embed floor
        mov = _attach_spark(mov, spark, lambda m: m["currency_id"], "prices")
        mov = _attach_spark(mov, snap, lambda m: m["currency_id"], "snap_prices")
        fungible.append({
            "key": key,
            "label": label,
            "movers": _by_direction(mov, "pct"),
            "momentum": _by_direction(mom[:top], "total_change_pct"),
        })

    # Uniques — Movers (primary) + Momentum (z-score), risers only. No 7d low/high.
    # Sparkline trace decoded from each unique's latest snapshot, keyed by entity id.
    uniq_spark: dict = {}
    for r in db.latest_uniques(con, league):
        st = trace_stats(r)
        if st is not None:
            uniq_spark[(r["item_type"], r["details_id"])] = st["prices"]
    uniq_snap = _snap_traces(db.unique_series(con, league),
                             lambda r: (r["item_type"], r["details_id"]), now, window_sec)
    uniq_momentum = _above_value(unique_momentum(
        con, league, z_threshold=uniq_z, min_listings=uniq_min_listings),
        "primary_value", min_value_divine)
    uniq_key = lambda m: (m["item_type"], m["details_id"])
    uniq_movers = _risers(unique_movers(
        con, league, window_sec=window_sec, top=top, min_listings=uniq_min_listings),
        movers_divine)  # unified movers embed floor
    uniq_movers = _attach_spark(uniq_movers, uniq_spark, uniq_key, "prices")
    uniq_movers = _attach_spark(uniq_movers, uniq_snap, uniq_key, "snap_prices")

    live = sum(len(g["momentum"]) for g in fungible) + len(uniq_momentum)

    # Top of the client value slider: highest embedded mover (Exalt), rounded up.
    movers_max_exalt = _movers_max_exalt(fungible, uniq_movers, exalt_per_divine)

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
        # momentum floor, the single movers embed floor, the slider's top end, and a
        # warning when the floors had to be skipped.
        "exalt_per_divine": exalt_per_divine,
        "floor_exalt": min_value,
        "movers_floor_exalt": movers_floor,
        "movers_max_exalt": movers_max_exalt,
        "rate_warning": rate_warning,
        "params": {
            "currency_z": cur_z, "currency_min_volume": cur_min_volume,
            "unique_z": uniq_z, "unique_min_listings": uniq_min_listings,
            "window_sec": window_sec, "top": top,
            "min_value": min_value,         # momentum floor, authored in Exalt
            "movers_floor": movers_floor,   # unified movers embed floor, in Exalt
        },
        # Bucket A: one group per fungible category, each with movers (primary) +
        # momentum. Renderers iterate this generically.
        "fungible": fungible,
        # Uniques: movers + momentum only (7d low/high deliberately removed).
        "unique_momentum": _by_direction(uniq_momentum[:top], "total_change_pct"),
        "unique_movers": _by_direction(uniq_movers, "pct"),
    }
