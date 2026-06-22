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

import config
from .transport import Transport

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


def fetch_currency(transport: Transport, league: str = config.LEAGUE) -> list[dict]:
    data = transport.get_json(config.url_currency(league))
    meta = {i["id"]: i for i in data.get("items", [])}
    ts = config.now_ts()
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
