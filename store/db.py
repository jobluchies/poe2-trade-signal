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
  category            TEXT NOT NULL DEFAULT 'currency',  -- Bucket A category key
  currency_id         TEXT NOT NULL,
  bucket              INTEGER NOT NULL,   -- ts floored to the hour: idempotency key
  ts                  INTEGER NOT NULL,   -- actual poll time (UTC unix seconds)
  league_day          INTEGER,
  name                TEXT,
  primary_value       REAL,               -- raw; canonical unit is Divine
  volume              REAL,
  max_volume_currency TEXT,
  max_volume_rate     REAL,
  spark_total_change  REAL,
  sparkline_json      TEXT,
  PRIMARY KEY (league, category, currency_id, bucket)
);
CREATE INDEX IF NOT EXISTS idx_curr_league_ts
  ON currency_snapshot(league, category, currency_id, ts);

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
  primary_value      REAL,             -- raw; canonical unit is Divine
  listing_count      INTEGER,          -- confidence gate (thin = suppress)
  spark_total_change REAL,
  sparkline_json     TEXT,
  PRIMARY KEY (league, item_type, details_id, corrupted, bucket)
);
CREATE INDEX IF NOT EXISTS idx_uniq_league_ts
  ON unique_snapshot(league, item_type, details_id, corrupted, ts);

CREATE TABLE IF NOT EXISTS rate_state (
  league TEXT NOT NULL,
  key    TEXT NOT NULL,        -- e.g. 'exalt_per_divine'
  value  REAL NOT NULL,        -- last-known-good value
  ts     INTEGER NOT NULL,     -- when it was derived (UTC unix seconds)
  PRIMARY KEY (league, key)
);
"""


def connect(path=config.DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _migrate_currency_category(con: sqlite3.Connection) -> None:
    """Add the `category` column to a pre-Bucket-A currency_snapshot in place.

    Old DBs have PK (league, currency_id, bucket) and no category column. SQLite
    can't ALTER a primary key, so rebuild the table: rename → recreate (new PK) →
    copy old rows tagged category='currency' → drop. Idempotent and a no-op once
    the column exists (or the table doesn't yet).
    """
    cols = [r["name"] for r in con.execute("PRAGMA table_info(currency_snapshot)")]
    if not cols or "category" in cols:
        return  # fresh DB (SCHEMA builds it correctly) or already migrated
    con.executescript(
        """
        ALTER TABLE currency_snapshot RENAME TO currency_snapshot_old;
        CREATE TABLE currency_snapshot (
          league TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'currency',
          currency_id TEXT NOT NULL, bucket INTEGER NOT NULL, ts INTEGER NOT NULL,
          league_day INTEGER, name TEXT, primary_value REAL, volume REAL,
          max_volume_currency TEXT, max_volume_rate REAL, spark_total_change REAL,
          sparkline_json TEXT,
          PRIMARY KEY (league, category, currency_id, bucket)
        );
        INSERT INTO currency_snapshot
          (league, category, currency_id, bucket, ts, league_day, name,
           primary_value, volume, max_volume_currency, max_volume_rate,
           spark_total_change, sparkline_json)
          SELECT league, 'currency', currency_id, bucket, ts, league_day, name,
                 primary_value, volume, max_volume_currency, max_volume_rate,
                 spark_total_change, sparkline_json
          FROM currency_snapshot_old;
        DROP TABLE currency_snapshot_old;
        """
    )
    con.commit()


def init_db(con: sqlite3.Connection) -> None:
    _migrate_currency_category(con)
    con.executescript(SCHEMA)
    con.commit()


def set_league_meta(con, league: str, start_ts: int, status: str = "active") -> None:
    con.execute(
        "INSERT OR REPLACE INTO league_meta(league, start_ts, status) VALUES (?,?,?)",
        (league, start_ts, status),
    )
    con.commit()


def get_last_rate(con, league: str, key: str = "exalt_per_divine") -> float | None:
    """Last-known-good rate for a league, or None if never persisted."""
    row = con.execute(
        "SELECT value FROM rate_state WHERE league = ? AND key = ?", (league, key)
    ).fetchone()
    return row["value"] if row else None


def set_last_rate(con, league: str, value: float, ts: int,
                  key: str = "exalt_per_divine") -> None:
    """Persist a last-known-good rate so a later bad fetch can fall back to it."""
    con.execute(
        "INSERT OR REPLACE INTO rate_state(league, key, value, ts) VALUES (?,?,?,?)",
        (league, key, value, ts),
    )
    con.commit()


def upsert_currency(con, rows: list[dict]) -> int:
    for r in rows:
        bucket = r["ts"] - (r["ts"] % 3600)
        con.execute(
            """INSERT OR REPLACE INTO currency_snapshot
               (league, category, currency_id, bucket, ts, league_day, name,
                primary_value, volume, max_volume_currency, max_volume_rate,
                spark_total_change, sparkline_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["league"], r.get("category") or "currency", r["currency_id"], bucket,
             r["ts"], r["league_day"], r["name"], r["primary_value"], r["volume"],
             r["max_volume_currency"], r["max_volume_rate"],
             r.get("spark_total_change"), r["sparkline_json"]),
        )
    con.commit()
    return len(rows)


def latest_currency(con, league: str = config.LEAGUE,
                    category: str | None = None) -> list[sqlite3.Row]:
    """Most recent snapshot row per (category, currency_id).

    `category=None` returns every category pooled; pass a category key to scope to
    one. Entity identity now spans category so same id across categories never
    collides (though exchange ids are globally unique slugs in practice).
    """
    sql = """SELECT * FROM currency_snapshot
             WHERE league = ?{cat} AND ts = (
               SELECT MAX(ts) FROM currency_snapshot c2
               WHERE c2.league = currency_snapshot.league
                 AND c2.category = currency_snapshot.category
                 AND c2.currency_id = currency_snapshot.currency_id)
             ORDER BY category, currency_id"""
    if category is None:
        return con.execute(sql.format(cat=""), (league,)).fetchall()
    return con.execute(sql.format(cat=" AND category = ?"), (league, category)).fetchall()


def currency_series(con, league: str = config.LEAGUE,
                    category: str | None = None) -> dict[str, list[sqlite3.Row]]:
    """All snapshots per (category, currency_id), oldest-first.

    Keyed on 'category:currency_id' so each category keeps its own accumulated
    history. `category=None` pools all categories; pass a key to scope to one.
    """
    if category is None:
        rows = con.execute(
            "SELECT * FROM currency_snapshot WHERE league = ? "
            "ORDER BY category, currency_id, ts", (league,)).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM currency_snapshot WHERE league = ? AND category = ? "
            "ORDER BY currency_id, ts", (league, category)).fetchall()
    series: dict[str, list] = defaultdict(list)
    for r in rows:
        series[f"{r['category']}:{r['currency_id']}"].append(r)
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
