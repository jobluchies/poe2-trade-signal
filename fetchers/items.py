"""Layer C — unique item fetcher. Normalizes stash item overviews into rows.

One overview call per item type (config.UNIQUE_TYPES); fail-soft per type so a
single bad/empty type never aborts the run. Canonical unit is DIVINE — store raw
primary_value; any Exalt conversion is re-derived live at the boundary (never here).
Items ship `sparkLine` (capital L); currency uses `sparkline` — handle both.
listingCount feeds the confidence gate (thin listings = suppress).
"""
from __future__ import annotations
import json
import logging

import config
from .transport import Transport

log = logging.getLogger("poe2.items")


def fetch_uniques(transport: Transport, league: str = config.LEAGUE,
                  types: tuple[str, ...] = config.UNIQUE_TYPES) -> list[dict]:
    ts = config.now_ts()
    rows: list[dict] = []
    for typ in types:
        try:
            data = transport.get_json(config.url_item_overview(typ, league))
        except Exception as e:  # fail soft: one type must not sink the run
            log.warning("unique type %r fetch failed: %s: %s", typ, type(e).__name__, e)
            continue
        lines = data.get("lines", []) if isinstance(data, dict) else []
        if not lines:
            log.warning("unique type %r returned 0 lines (league=%r)", typ, league)
            continue
        for ln in lines:
            did = ln.get("detailsId")
            if not did:
                continue
            spark = ln.get("sparkLine") or ln.get("sparkline") or {}
            rows.append({
                "ts": ts,
                "league": league,
                "league_day": config.league_day(ts),
                "item_type": typ,
                "details_id": did,
                "corrupted": bool(ln.get("corrupted")),
                "name": ln.get("name") or ln.get("itemId") or did,
                "base_type": ln.get("baseType"),
                "category": ln.get("category"),
                "primary_value": ln.get("primaryValue"),
                "listing_count": ln.get("listingCount"),
                "spark_total_change": spark.get("totalChange"),
                "sparkline_json": json.dumps(spark.get("data") or []),
            })
    return rows
