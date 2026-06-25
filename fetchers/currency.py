"""Layer A — currency fetcher. Normalizes the exchange overview into snapshot rows.

Canonical internal unit is DIVINE: poe.ninja quotes nearly every line against
`divine` (maxVolumeCurrency), and the Divine Orb line itself is primaryValue 1.0.
We store raw primary_value + the currency each line is most traded against, so the
Exalt:Divine rate can be re-derived live per run (see derive_exalt_per_divine) —
never a hardcoded constant. The old "base is Exalted, ~90.9 ex/div" assumption
(Phase-0, 2026-06-17) is stale; the rate moves continuously.
"""
from __future__ import annotations
import json
import logging

import config
from .transport import Transport

log = logging.getLogger("poe2.exchange")

# Sanity band for a plausible Exalt-per-Divine rate. Anything outside this is
# treated as a bad read and rejected in favour of last-known-good.
RATE_MIN, RATE_MAX = 50.0, 1000.0


def derive_exalt_per_divine(currency_rows, last_known: float | None = None) -> float | None:
    """Live Exalt:Divine rate (Exalt per 1 Divine) from the Divine Orb line.

    The Divine Orb line is the one still quoted against Exalted
    (`max_volume_currency == 'exalted'`); its `max_volume_rate` is Divine-per-Exalt,
    so Exalt-per-Divine is the reciprocal. Guarded by a sanity band. On any failure
    (line missing, wrong pivot, non-positive or out-of-band rate) returns
    `last_known` — never a hardcoded constant.

    `currency_rows`: iterable of row-like mappings (sqlite Row or dict) carrying
    `name`, `max_volume_currency`, `max_volume_rate`.
    """
    line = None
    for r in currency_rows or []:
        if str(r["name"] or "").strip().lower() == "divine orb":
            line = r
            break
    if line is None or str(line["max_volume_currency"] or "").lower() != "exalted":
        return last_known
    mvr = line["max_volume_rate"]
    if not mvr or mvr <= 0:
        return last_known
    rate = 1.0 / mvr
    if not (RATE_MIN <= rate <= RATE_MAX):
        return last_known
    return rate


def _parse_exchange(data: dict, category: str, league: str, ts: int) -> list[dict]:
    """Normalize one exchange overview payload into category-tagged snapshot rows.

    Every line carries a unique `id` slug; the `items` array supplies the display
    name. Keying downstream on (category, id) keeps same-name variants distinct
    (e.g. Uncut Skill Gem Level 17 vs 19 arrive as separate ids), so nothing is
    silently deduped.
    """
    meta = {i["id"]: i for i in data.get("items", [])}
    rows: list[dict] = []
    for ln in data.get("lines", []):
        cid = ln.get("id")
        if cid is None:
            continue
        m = meta.get(cid, {})
        spark = ln.get("sparkline") or {}
        rows.append({
            "ts": ts,
            "league": league,
            "league_day": config.league_day(ts),
            "category": category,
            "currency_id": cid,
            "name": m.get("name") or cid,
            "primary_value": ln.get("primaryValue"),
            "volume": ln.get("volumePrimaryValue"),
            "max_volume_currency": ln.get("maxVolumeCurrency"),
            "max_volume_rate": ln.get("maxVolumeRate"),
            "spark_total_change": spark.get("totalChange"),
            "sparkline_json": json.dumps(spark.get("data") or []),
        })
    return rows


def fetch_exchange(transport: Transport, league: str = config.LEAGUE,
                   categories=config.EXCHANGE_CATEGORIES) -> list[dict]:
    """Generic Bucket A loader: one overview call per category, rows tagged by
    category. Fail-soft per category so one bad/empty category never sinks the run
    (mirrors fetch_uniques). The Divine Orb line lands under category='currency',
    where derive_exalt_per_divine still finds it.
    """
    ts = config.now_ts()
    rows: list[dict] = []
    for key, exch_type, _label in categories:
        try:
            data = transport.get_json(config.url_exchange(exch_type, league))
        except Exception as e:  # fail soft: one category must not sink the run
            log.warning("exchange category %r (type=%r) fetch failed: %s: %s",
                        key, exch_type, type(e).__name__, e)
            continue
        if not isinstance(data, dict) or "lines" not in data:
            log.warning("exchange category %r (type=%r) returned no lines payload",
                        key, exch_type)
            continue
        cat_rows = _parse_exchange(data, key, league, ts)
        if not cat_rows:
            log.info("exchange category %r (type=%r) returned 0 lines (league=%r)",
                     key, exch_type, league)
        rows.extend(cat_rows)
    return rows


def fetch_currency(transport: Transport, league: str = config.LEAGUE) -> list[dict]:
    """Back-compat name — now fetches ALL Bucket A exchange categories, not just
    Currency. Kept so existing callers (cli) keep working."""
    return fetch_exchange(transport, league)
