"""Thin CLI tying the layers together.

    python cli.py init
    python cli.py fetch                 # poll currency, store snapshot
    python cli.py momentum [--z 2.0] [--min-volume 0]
    python cli.py movers [--window 1d|3d|1w]

Phase 1 covers the currency layer. backfill/scrape/report land in later phases.
"""
from __future__ import annotations
import argparse
import logging
import sys

import config
from fetchers import Transport, resolve_league
from fetchers.currency import fetch_currency
from fetchers.items import fetch_uniques
from signals.momentum import currency_momentum
from signals.movers import currency_movers
from signals.items import unique_momentum, unique_movers
from store import db
import report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("poe2")

_WINDOWS = {"1d": 86400, "3d": 259200, "1w": 604800, "24h": 86400}


def cmd_init(_args) -> int:
    con = db.connect()
    db.init_db(con)
    db.set_league_meta(con, config.LEAGUE, config.LEAGUE_START_TS)
    log.info("Initialized DB at %s for league %r (start_ts=%s)",
             config.DB_PATH, config.LEAGUE, config.LEAGUE_START_TS)
    return 0


def cmd_fetch(args) -> int:
    con = db.connect()
    db.init_db(con)
    with Transport(headless=not args.headed) as t:
        canonical, _idx = resolve_league(t, config.LEAGUE)
        if canonical is None:
            log.warning("League %r not found in index-state — it may have rotated. "
                        "Fetching anyway with the configured name.", config.LEAGUE)
            league = config.LEAGUE
        else:
            if canonical != config.LEAGUE:
                log.warning("Configured league %r resolved to canonical %r — using canonical.",
                            config.LEAGUE, canonical)
            league = canonical
        db.set_league_meta(con, league, config.LEAGUE_START_TS)
        rows = fetch_currency(t, league)
        urows = [] if args.no_uniques else fetch_uniques(t, league)
    n = db.upsert_currency(con, rows)
    un = db.upsert_uniques(con, urows) if urows else 0
    log.info("Stored %d currency + %d unique snapshot rows for %r (league_day=%s).",
             n, un, league, config.league_day(config.now_ts()))
    return 0


def cmd_momentum(args) -> int:
    con = db.connect()
    db.init_db(con)
    hits = currency_momentum(con, config.LEAGUE, z_threshold=args.z, min_volume=args.min_volume)
    if not hits:
        print("No currency momentum signals (need a fetch first, or none exceed threshold).")
        return 0
    print(f"Currency momentum (|z| >= {args.z}, league={config.LEAGUE!r}):")
    for h in hits:
        print(f"  {h['name']:<28} z={h['z']:+.2f}  7d%={h['total_change_pct']}  vol={h['volume']}")
    return 0


def cmd_movers(args) -> int:
    con = db.connect()
    db.init_db(con)
    window = _WINDOWS.get(args.window, 86400)
    movers = currency_movers(con, config.LEAGUE, window_sec=window, top=args.top)
    if not movers:
        print(f"No movers over {args.window} yet - need >=2 snapshots spanning the window. "
              "Use `momentum` for run-#1 signal.")
        return 0
    print(f"Currency movers over {args.window} (league={config.LEAGUE!r}):")
    for m in movers:
        print(f"  {m['name']:<28} {m['pct']:+.2f}%  {m['from']:.6g} -> {m['to']:.6g}")
    return 0


def cmd_unique_momentum(args) -> int:
    con = db.connect()
    db.init_db(con)
    hits = unique_momentum(con, config.LEAGUE, z_threshold=args.z,
                           min_listings=args.min_listings)
    if not hits:
        print("No unique momentum signals (need a fetch first, or none exceed threshold).")
        return 0
    print(f"Unique momentum (|z| >= {args.z}, listings >= {args.min_listings}, "
          f"league={config.LEAGUE!r}):")
    for h in hits:
        print(f"  {h['name']:<34} z={h['z']:+.2f}  7d%={h['total_change_pct']}  "
              f"val={h['primary_value']:g}ex  n={h['listing_count']}  [{h['item_type']}]")
    return 0


def cmd_unique_movers(args) -> int:
    con = db.connect()
    db.init_db(con)
    window = _WINDOWS.get(args.window, 86400)
    movers = unique_movers(con, config.LEAGUE, window_sec=window, top=args.top,
                           min_listings=args.min_listings)
    if not movers:
        print(f"No unique movers over {args.window} yet - need >=2 snapshots spanning "
              "the window. Use `unique-momentum` for run-#1 signal.")
        return 0
    print(f"Unique movers over {args.window} (league={config.LEAGUE!r}):")
    for m in movers:
        print(f"  {m['name']:<34} {m['pct']:+.2f}%  {m['from']:g} -> {m['to']:g}ex  "
              f"n={m['listing_count']}  [{m['item_type']}]")
    return 0


def cmd_report(args) -> int:
    con = db.connect()
    db.init_db(con)
    window = _WINDOWS.get(args.window, 86400)
    paths = report.generate(
        con, config.LEAGUE,
        cur_z=args.cur_z, cur_min_volume=args.cur_min_volume,
        uniq_z=args.uniq_z, uniq_min_listings=args.uniq_min_listings,
        window_sec=window, top=args.top,
    )
    data = paths["data"]
    log.info("Wrote brief -> %s", paths["markdown"])
    log.info("Wrote dashboard -> %s", paths["html"])
    print(f"Signal report ({config.LEAGUE}, day {data['league_day']}): "
          f"{len(data['currency_momentum'])} currency + {len(data['unique_momentum'])} "
          f"unique momentum signals from {data['snapshot_count']} snapshot(s).")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="poe2-signal", description="PoE2 market signal system")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create DB + league_meta").set_defaults(func=cmd_init)

    pf = sub.add_parser("fetch", help="poll currency + uniques and store a snapshot")
    pf.add_argument("--headed", action="store_true", help="show the browser (debug)")
    pf.add_argument("--no-uniques", action="store_true",
                    help="skip the unique-item layer (currency only)")
    pf.set_defaults(func=cmd_fetch)

    pm = sub.add_parser("momentum", help="z-score momentum from sparklines (live run #1)")
    pm.add_argument("--z", type=float, default=2.0)
    pm.add_argument("--min-volume", type=float, default=0.0)
    pm.set_defaults(func=cmd_momentum)

    pv = sub.add_parser("movers", help="absolute percent movers from snapshot history")
    pv.add_argument("--window", choices=list(_WINDOWS), default="1d")
    pv.add_argument("--top", type=int, default=15)
    pv.set_defaults(func=cmd_movers)

    pum = sub.add_parser("unique-momentum", help="z-score momentum for unique items")
    pum.add_argument("--z", type=float, default=2.0)
    pum.add_argument("--min-listings", type=int, default=3)
    pum.set_defaults(func=cmd_unique_momentum)

    puv = sub.add_parser("unique-movers", help="absolute percent movers for unique items")
    puv.add_argument("--window", choices=list(_WINDOWS), default="1d")
    puv.add_argument("--top", type=int, default=15)
    puv.add_argument("--min-listings", type=int, default=3)
    puv.set_defaults(func=cmd_unique_movers)

    pr = sub.add_parser("report", help="write the Markdown brief + dark HTML dashboard to output/")
    pr.add_argument("--cur-z", type=float, default=2.0)
    pr.add_argument("--cur-min-volume", type=float, default=1.0)
    pr.add_argument("--uniq-z", type=float, default=2.0)
    pr.add_argument("--uniq-min-listings", type=int, default=5)
    pr.add_argument("--window", choices=list(_WINDOWS), default="1d")
    pr.add_argument("--top", type=int, default=25)
    pr.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
