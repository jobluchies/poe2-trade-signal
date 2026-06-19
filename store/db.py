"""SQLite store. Append-only snapshots, idempotent per (league, entity, hour)."""
from __future__ import annotations
import sqlite3
from collections import defaultdict

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS league_meta (
  league   TEXT PRIMARY KEY,
  start_ts INTEGER NOT NULL,
  status   TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS currency_snapshot (
  league              TEXT NOT NULL,
  currency_id         TEXT NOT NULL,
  bucket              INTEGER NOT NULL,   -- ts floored to the hour: idempotency key
  ts                  INTEGER NOT NULL,   -- actual poll time (UTC unix seconds)
  league_day          INTEGER,
  name                TEXT,
  primary_value       REAL,               -- raw; base currency is Exalted
  volume              REAL,
  max_volume_currency TEXT,
  max_volume_rate     REAL,
  spark_total_change  REAL,
  sparkline_json      TEXT,
  PRIMARY KEY (league, currency_id, bucket)
);
CREATE INDEX IF NOT EXISTS idx_curr_league_ts
  ON currency_snapshot(league, currency_id, ts);

CREATE TABLE IF NOT EXISTS unique_snapshot (
  league             TEXT NOT NULL,
  item_type          TEXT NOT NULL,    -- UniqueWeapons, UniqueArmours, ...
  details_id         TEXT NOT NULL,    -- stable slug, entity key
  corrupted          INTEGER NOT NULL DEFAULT 0,  -- variant split (0/1)
  bucket             INTEGER NOT NULL, -- ts floored to the hour: idempotency key
  ts                 INTEGER NOT NULL, -- actual poll time (UTC unix seconds)
  league_day         INTEGER,
  name               TEXT,
  base_type          TEXT,
  category           TEXT,
  primary_value      REAL,             -- raw; base currency is Exalted
  listing_count      INTEGER,          -- confidence gate (thin = suppress)
  spark_total_change REAL,
  sparkline_json     TEXT,
  PRIMARY KEY (league, item_type, details_id, corrupted, bucket)
);
CREATE INDEX IF NOT EXISTS idx_uniq_league_ts
  ON unique_snapshot(league, item_type, details_id, corrupted, ts);
"""


def connect(path=config.DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


def set_league_meta(con, league: str, start_ts: int, status: str = "active") -> None:
    con.execute(
        "INSERT OR REPLACE INTO league_meta(league, start_ts, status) VALUES (?,?,?)",
        (league, start_ts, status),
    )
    con.commit()


def upsert_currency(con, rows: list[dict]) -> int:
    for r in rows:
        bucket = r["ts"] - (r["ts"] % 3600)
        con.execute(
            """INSERT OR REPLACE INTO currency_snapshot
               (league, currency_id, bucket, ts, league_day, name, primary_value,
                volume, max_volume_currency, max_volume_rate, spark_total_change,
                sparkline_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["league"], r["currency_id"], bucket, r["ts"], r["league_day"],
             r["name"], r["primary_value"], r["volume"], r["max_volume_currency"],
             r["max_volume_rate"], r.get("spark_total_change"), r["sparkline_json"]),
        )
    con.commit()
    return len(rows)


def latest_currency(con, league: str = config.LEAGUE) -> list[sqlite3.Row]:
    """Most recent snapshot row per currency."""
    return con.execute(
        """SELECT * FROM currency_snapshot
           WHERE league = ? AND ts = (
             SELECT MAX(ts) FROM currency_snapshot c2
             WHERE c2.league = currency_snapshot.league
               AND c2.currency_id = currency_snapshot.currency_id)
           ORDER BY currency_id""",
        (league,),
    ).fetchall()


def currency_series(con, league: str = config.LEAGUE) -> dict[str, list[sqlite3.Row]]:
    """All snapshots per currency_id, oldest-first."""
    rows = con.execute(
        "SELECT * FROM currency_snapshot WHERE league = ? ORDER BY currency_id, ts",
        (league,),
    ).fetchall()
    series: dict[str, list] = defaultdict(list)
    for r in rows:
        series[r["currency_id"]].append(r)
    return series


# Layer C — unique items -----------------------------------------------------

def _uniq_key(r) -> str:
    """Stable entity key for a unique row across snapshots."""
    return f"{r['item_type']}:{r['details_id']}:{int(r['corrupted'] or 0)}"


def upsert_uniques(con, rows: list[dict]) -> int:
    for r in rows:
        bucket = r["ts"] - (r["ts"] % 3600)
        con.execute(
            """INSERT OR REPLACE INTO unique_snapshot
               (league, item_type, details_id, corrupted, bucket, ts, league_day,
                name, base_type, category, primary_value, listing_count,
                spark_total_change, sparkline_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["league"], r["item_type"], r["details_id"], int(r.get("corrupted") or 0),
             bucket, r["ts"], r["league_day"], r["name"], r.get("base_type"),
             r.get("category"), r.get("primary_value"), r.get("listing_count"),
             r.get("spark_total_change"), r["sparkline_json"]),
        )
    con.commit()
    return len(rows)


def latest_uniques(con, league: str = config.LEAGUE) -> list[sqlite3.Row]:
    """Most recent snapshot row per unique entity."""
    return con.execute(
        """SELECT * FROM unique_snapshot u
           WHERE league = ? AND ts = (
             SELECT MAX(ts) FROM unique_snapshot u2
             WHERE u2.league = u.league AND u2.item_type = u.item_type
               AND u2.details_id = u.details_id AND u2.corrupted = u.corrupted)
           ORDER BY item_type, details_id""",
        (league,),
    ).fetchall()


def unique_series(con, league: str = config.LEAGUE) -> dict[str, list[sqlite3.Row]]:
    """All snapshots per unique entity, oldest-first."""
    rows = con.execute(
        "SELECT * FROM unique_snapshot WHERE league = ? ORDER BY item_type, details_id, ts",
        (league,),
    ).fetchall()
    series: dict[str, list] = defaultdict(list)
    for r in rows:
        series[_uniq_key(r)].append(r)
    return series
