# BUILD_STATUS — PoE2 Market Signal System

Resume doc. A fresh session should read this + `API_NOTES.md` + `poe2_signal_build_prompt.md` to continue cold.

## Locked decisions
- **Target league:** `HC Runes of Aldur` (Hardcore). Has full data on all 3 layers. Query param is the **display name**, not the url slug. (`indexed:false` does NOT mean no data.)
- **Deployment:** GitHub Actions cron + **commit the SQLite DB back to the repo** (NOT artifact storage — 90-day retention would truncate history). Dashboard via GitHub Pages.
  - **Durable alternative (not implemented):** committing a binary DB to git is the root cause of the push contention — every run rewrites it, so any concurrent edit forces a rebase. The robust fix is to stop versioning the DB in git: hold it in a persistent **Actions cache** (keyed/restored each run), publish it as a build **artifact**, keep it on a **dedicated `data` branch** the workflow force-updates (no rebase needed since it's the only writer), or move history to an **external store** (e.g. a hosted SQLite/Postgres or object storage). Each removes git rebase from the hot path. Deferred — the retry/rebase loop is enough for a single-writer cron; revisit if contention persists.
- **Scope:** Core first = Layers A-C + output. Layer D (community scrape) deferred to a later bolt-on.
- **Base currency is Exalted, not Chaos** (prompt's chaos model is wrong for PoE2 0.5). Store raw `primary_value` + `max_volume_currency`.
- **Transport:** poe.ninja is behind Cloudflare; raw HTTP gets 404. Use **headless Playwright** (works locally AND in GitHub Actions). Hard dependency.

## Phase status
- [x] **Phase 0 — Verify API.** Done. Endpoints remapped (prompt's were stale). See `API_NOTES.md`.
- [x] **Phase 1 — Currency layer.** Done + verified live (45 HC rows, momentum signal from run #1).
- [ ] **Phase 2 — Builds + backfill.** Endpoint: `builds/{version}/search?overview={snapshotName}` + `builds/dictionary/{hash}`. Version is per-league from index-state `snapshotVersions` (HC uses a different version than SC). `resolve.find_build_snapshot()` already locates it. Backfill = iterate `snapshotVersions`. Need: `build_snapshot`, `build_item_link` tables; rising-build delta (rank by acceleration); map the dictionary hash lookups.
- [x] **Phase 3 — Unique items.** Done + verified live (574 HC rows across 6 types, momentum from run #1). Endpoint: `economy/stash/current/item/overview?league=...&type=...`. Live-valid types: `UniqueWeapons`(129), `UniqueArmours`(328), `UniqueAccessories`(85), `UniqueFlasks`(6), `UniqueJewels`(14), `UniqueCharms`(12). Dead types (0 lines): UniqueArmour, UniqueAccessory, UniqueJewel, UniqueWaystones. `sparkLine` (capital L), `primaryValue`, `listingCount`, `corrupted` stored. z-score momentum + confidence gate on `listing_count` (min 3 — suppresses thin price-fixer traps like Temporalis @ n=1).
- [ ] **Phase 4 — Community scrape (Layer D).** Deferred. Reddit/YouTube official APIs first.
- [x] **Phase 5 — Output.** Done + verified. `report/` package: `collect.py` (one dict, single source of thresholds) -> `markdown.py` (YAML-frontmatter brief, Dataview-ready) + `html.py` (self-contained dark dashboard, inline CSS, no JS — Pages-ready for Phase 6). `python cli.py report` writes `output/signal-brief.md` + `output/dashboard.html`. Builds (Phase 2) will slot new sections into the same collect dict.
- [x] **Phase 6 — Scheduling.** GitHub Actions cron (`.github/workflows/fetch.yml`) fetches, regenerates the report, commits `data/` + `output/` back to `main`, and deploys the dashboard to Pages. The commit step is resilient to the remote advancing mid-run: it pulls/rebases onto the live tip before fetching, then pushes in a retry loop (5 attempts) that rebases onto `origin/main` on rejection. A rebase conflict on the binary DB is handled by aborting, resetting to the live tip, and re-running `fetch` so rows append onto the current DB (capped re-fetch budget) — never picking a side, so no snapshots are lost.

## What exists now
```
config.py              league/env, endpoint builders, league_day, UNIQUE_TYPES
fetchers/
  transport.py         Playwright fetch + 12-req/5min limiter + 1h cache
  resolve.py           index-state, resolve_league(), find_build_snapshot()
  currency.py          Layer A normalizer (Exalted-based)
  items.py             Layer C normalizer (uniques, 6 types, fail-soft per type)
store/db.py            sqlite schema, league_meta + currency_snapshot + unique_snapshot, upserts, queries
signals/
  momentum.py          sparkline z-score (live run #1), confidence gate via min_volume
  movers.py            absolute % currency movers from snapshot history
  items.py             unique momentum + movers, confidence gate via min_listings
report/
  collect.py           gather all signals + meta into one dict (single threshold source)
  markdown.py          YAML-frontmatter brief (Dataview-ready)
  html.py              self-contained dark dashboard (inline CSS, no JS, Pages-ready)
cli.py                 init | fetch | momentum | movers | unique-momentum | unique-movers | report
data/poe2_signal.db    the time-series (committed back, per decision)
output/                generated artifacts: signal-brief.md + dashboard.html
```

## Run
```
pip install -r requirements.txt && python -m playwright install chromium
cp .env.example .env          # confirm league + start date
python cli.py init
python cli.py fetch           # poll + store one snapshot
python cli.py momentum --z 2.0 --min-volume 1
python cli.py movers --window 1d
python cli.py unique-momentum --z 2.0 --min-listings 3
python cli.py unique-movers --window 1d --min-listings 3
python cli.py report           # -> output/signal-brief.md + output/dashboard.html
```

## Gotchas
- `league` param = display name (`HC Runes of Aldur`), url slug returns 0 lines.
- Sparklines contain `null` entries - filter before stats (done in momentum).
- Sparkline = RELATIVE %. Never reconstruct absolute history from it. DB snapshots = sole absolute source.
- Python 3.14: argparse treats `%` in help strings as a format char - avoid literal `%`.
- Movers are empty until >=2 snapshots span the window. Correct - momentum covers cold-start.
- Unique item `type` naming is plural and exact: `UniqueArmours` works, `UniqueArmour` returns 0 lines. Same for Accessories/Jewels. Source of truth = `config.UNIQUE_TYPES` (verified live).
- Items use `sparkLine` (capital L); currency uses `sparkline`. `fetch_uniques` checks both.
- Unique confidence gate is `listing_count` (not volume — uniques have no volume field). Default min 3; raise it to cut early-league noise (day-18 sparklines ramp hard so z-scores cluster near +2.4).
- Unique entity key = (item_type, details_id, corrupted) — corrupted variants tracked as separate series.
