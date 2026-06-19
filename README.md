# PoE2 Market Signal System

Personal market-intelligence for Path of Exile 2 (league: **HC Runes of Aldur**). It polls
poe.ninja on a schedule, accumulates its own price + meta history in SQLite, and surfaces
*trends* - which builds are rising and which gear/currency they drive - so demand shifts can be
spotted before the broad playerbase. Decision-support only; no auto-trading.

**The time-series is the product.** poe.ninja serves mostly current prices; there is no PoE2
bulk history. We build history by polling and accumulating snapshots. The ~7-day sparkline in
each response seeds momentum from the first run.

## Setup
```
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env        # confirm league + start date
python cli.py init
```

## Use
```
python cli.py fetch                       # poll currency + uniques, store a snapshot
python cli.py momentum --z 2.0 --min-volume 1
python cli.py movers --window 1d
python cli.py unique-momentum --z 2.0 --min-listings 3
python cli.py unique-movers --window 1d --min-listings 3
python cli.py report                       # -> output/signal-brief.md + output/dashboard.html
```
`fetch --no-uniques` polls currency only. Open `output/dashboard.html` in any browser for the
dark dashboard; `output/signal-brief.md` is a Dataview-ready Obsidian note.

## Status
Phases 1 (currency), 3 (unique items), 5 (output: dashboard + brief), and 6 (scheduling) are
live and verified. See `BUILD_STATUS.md` for the full roadmap and `API_NOTES.md` for the verified
endpoint surface. Builds (Phase 2) and community scrape are upcoming.

## Scheduling
`.github/workflows/fetch.yml` runs on a cron, fetches a snapshot, regenerates the report, commits
`data/` + `output/` back to `main`, and deploys the dashboard to Pages — your machine stays off.
The commit step rebases onto the live tip and retries the push, so a concurrent edit no longer
fails the run; a conflict on the binary DB triggers a re-fetch onto the current DB rather than
discarding snapshots. The DB is versioned in git on purpose (full history); the durable way to
avoid push contention entirely is to stop committing the binary — see the deployment note in
`BUILD_STATUS.md`.
