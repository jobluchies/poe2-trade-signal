"""Layer A — currency fetcher. Normalizes the exchange overview into snapshot rows.

Economy base is EXALTED (not chaos). We store raw primary_value + the currency it
is most traded against, so any conversion can be re-derived later.
"""
from __future__ import annotations
import json

import config
from .transport import Transport


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
