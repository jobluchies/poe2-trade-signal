# Build Prompt — PoE2 Market Signal System

Paste this into Claude Code in an empty project folder. Read it fully before writing code, then start at Phase 0.

---

## What we're building

A personal market-intelligence system for **Path of Exile 2**. It captures poe.ninja data on a schedule, accumulates its own price + meta history in SQLite, and surfaces *trends* — which builds are rising and which gear/currency those builds depend on — so a human can spot demand shifts **before the broad playerbase** and trade accordingly (buy low, sell high).

This is a decision-support tool, **not** an auto-trader. The system assembles a signal brief; a human reads it and decides. Stay out of any actual buying/selling.

### The thesis (this drives every design choice)

Build popularity is the **leading** indicator; gear/currency price is the **lagging** variable. A build rises in popularity → demand for its key uniques and currency follows → price moves. If we detect the rising build early, we're early on the gear. The highest-signal window is the **first week of a new league**, when the meta crystallizes fastest.

### The core insight about the data

The poe.ninja PoE2 economy API mostly returns **current prices only**, and (confirmed) there is **no PoE2 data-dump page** for bulk historical backfill — dumps exist for PoE1 only. So **the time-series is the product**: we build it ourselves by polling the JSON endpoints on a schedule and accumulating snapshots. poe.ninja is the meter; our database is the chart. The one piece of history that ships for free is the ~7-day `sparkline` embedded in each response, which seeds momentum detection from the first run. Continuous capture from day one matters more than any backfill. See **Historical data strategy** below for how history arrives in layers.

---

## Tech stack & conventions

- **Python 3.11+**, standard library first (`urllib`, `sqlite3`, `json`). Add `requests`, `beautifulsoup4`/`selectolax`, and any official-API SDKs only where they earn their place (mainly the scrape layer). Keep a `requirements.txt`.
- **SQLite** single-file DB. All timestamps stored as UTC unix seconds.
- **Secrets in `.env`** (never hardcoded): any API keys for the scrape layer, OAuth creds if used. Provide `.env.example`.
- **Output is consumable two ways**: (1) a self-contained dark-theme HTML dashboard, (2) a Markdown "signal brief" with YAML frontmatter so it drops into an Obsidian vault and is Dataview-queryable.
- Clear module boundaries: `fetchers/`, `store/`, `signals/`, `report/`, `scrape/`. A thin CLI ties them together (`fetch`, `backfill`, `scrape`, `signals`, `report`).
- Idempotent runs, graceful failure, structured logging. A failed source must not abort the whole run.

A reference skeleton for the currency fetcher + snapshot table + trend query already exists (`poe2_signal.py`, dependency-free stdlib). Use it as the starting pattern for Phase 1 if provided; otherwise rebuild that pattern.

---

## Data sources (verify before trusting)

poe.ninja has an **official Swagger-documented API** at `https://poe.ninja/swagger/index.html`. **Treat this as canonical.** Read it first and prefer documented endpoints. The reverse-engineered endpoints below are a fallback and may have drifted — confirm shapes against the live API and, where needed, by inspecting the site's network calls (DevTools → Network → XHR/fetch).

**Layer A — Currency (verified):**
`GET https://poe.ninja/poe2/api/economy/currencyexchange/overview?leagueName={LEAGUE}&overviewName=Currency`
Returns `lines[]` (`id`, `primaryValue`, `volumePrimaryValue`) and `items[]` (`id`, `name`, `icon`). Gotchas: **no sparkline / no history** on this endpoint (we build the series). `primaryValue` rule is documented as: `>=1` → direct chaos value; `<1` → items-per-chaos, so invert (`1/primaryValue`). **Validate this interpretation against the live site before trusting direction.** Keep the raw `primaryValue` in the DB so it can be re-derived.

**Layer B — Builds / meta (partly reverse-engineered):**
poe.ninja indexes the GGG ladder API for builds, plus opt-in OAuth character data. Historical snapshots exist via a "Time Machine": an **index-state** exposes `snapshotVersions`, and a builds endpoint (pattern `/poe2/api/builds/{version}/...`) serves each snapshot — **daily in week 1, then weekly**. This means build-meta history **is backfillable**. Confirm exact endpoint shapes against Swagger / network capture. Known quirk (per poe.ninja FAQ): the character API sometimes reports the secondary weapon set as primary, making build determination noisy — flag low-confidence rows rather than dropping them.

**Layer C — Unique items (partly reverse-engineered):**
Item/market-trend overviews carry a short **sparkline array (~7 points)** plus `lowConfidenceSparkline` and `totalChange`, alongside `chaosValue`/`divineValue` and `listingCount`. So ~a week of recent per-item movement can be **seeded at build time** for the current league. Confirm the exact PoE2 unique-item endpoint(s) via Swagger.

**What is NOT cleanly available:** bulk historical PoE2 economy data. There are no PoE2 data dumps, and the API serves no continuous tick-history. Past-league *build* snapshots are the exception — retrievable via snapshot versions.

---

## Historical data strategy (confirmed: no PoE2 data dumps)

poe.ninja hosts downloadable dumps for PoE1 only (`poe.ninja/poe1/data`); there is **no PoE2 equivalent** — verified. So there is no one-shot backfill of past-league PoE2 economy. The system earns its history by polling on a schedule and accumulating snapshots. That is the design, not a workaround. Crucially, history becomes available in **layers at different times** — build for this explicitly instead of assuming everything cold-starts:

- **Momentum / "hot" — live from run #1.** Every item/currency overview ships a ~7-point `sparkline` (relative % movement over ~7 days) plus `lowConfidenceSparkline`. The sparkline *is* the rolling 7-day window, so momentum detection needs none of our own accumulated history to begin. Working signal on the very first fetch.
- **Intra-league trend beyond 7 days — after ~a week of running.** Past the sparkline window, our own snapshots extend the series indefinitely. Sparkline seeds week 1; our polls carry it onward.
- **Rising builds — fast.** Build-meta backfills via snapshot versions (Time Machine), so this layer does not cold-start.
- **Cross-league cyclical ("reliably spikes on day 4") — matures over leagues, NOT a launch feature.** Buildable only from leagues we observe forward. League 1 = no baseline; the overlay becomes meaningful from league 2–3 onward. Set this expectation clearly; don't present it as available at launch.

**Critical modeling rule — keep relative and absolute separate.** The sparkline is *relative* (percent movement); our snapshots are *absolute* (chaos value at poll time). Do **not** reconstruct absolute historical prices by back-applying sparkline percentages — it is lossy and corrupts the series. Sparkline feeds momentum / z-score only; the snapshot DB is the sole source of absolute history beyond 7 days. Two complementary functions, never merged into one fake history.

---

## Data model

One append-only snapshot row per (timestamp, league, entity). Every snapshot is tagged with **league** and **`league_day`** (integer days since that league's start) so leagues can be overlaid on a common axis ("day 3 of every league") — this is how we identify items that reliably appreciate within or across leagues.

Suggested tables (refine as you go):
- `currency_snapshot(ts, api_ts, league, league_day, currency_id, name, primary_value, volume, chaos_equiv)`
- `item_snapshot(ts, api_ts, league, league_day, item_id, name, category, chaos_value, divine_value, listing_count, low_confidence, sparkline_json)`
- `build_snapshot(ts, snapshot_version, league, league_day, class, ascendancy, skill, share_pct, sample_size, low_confidence)`
- `build_item_link(build_snapshot fk, item_id, slot, usage_pct)` — the bridge that connects a rising build to the specific gear it drives. This table is where the thesis lives.
- `community_signal(ts, source, source_url, league, build_name, class, ascendancy, skills_json, items_json, mentions, engagement, raw_excerpt)` — see Layer D.

Store a `league_meta(league, start_ts, status)` table; `league_day` is derived from it. Make league a parameter everywhere — **never hardcode the current league name** (it rotates and is case-sensitive; confirm it from the live site at runtime or via config).

---

## Signals (the actual value)

Compute, don't just store:
- **Hot momentum (z-score, live from run #1)**: flag an item when its current price sits more than ~2 standard deviations above the mean of its 7-day sparkline — an unusual move relative to its *own* recent range, not just a raw % change. The sparkline supplies the rolling window, so this needs no accumulated history.
- **Intra-league movers (absolute)**: % change of `chaos_equiv` / `chaos_value` over a window (24h/3d/1w) vs the snapshot closest to `now - window`, sourced from our own snapshot DB. Reject baselines older than ~2× the window so a stale row isn't reported as a fresh mover.
- **Rising builds**: delta of `share_pct` per (class, ascendancy, skill) across build snapshot versions. Rank by acceleration, not just level.
- **Build→gear linkage**: for builds that are rising, surface their associated uniques/currency from `build_item_link`, and cross-reference whether those items have *yet* moved in price. **The sweet spot is a rising build whose key gear has not yet repriced.**
- **Cross-league appreciation (matures over leagues)**: using `league_day`, overlay observed leagues on a common axis to flag items that reliably climb on the same league-day or end every league higher. Only meaningful once ≥2–3 leagues have been observed (see Historical data strategy) — until then this section should report "insufficient history" rather than fabricate a pattern.
- **Confidence gate (anti price-fixing)**: gate every momentum/mover signal on confidence. If only `lowConfidenceSparkline` is populated, or `listingCount`/volume is below a threshold, suppress the signal. A near-vertical spike on thin volume with no matching meta shift is usually a price-fixer, not a trend — flag it, never silently surface it as a buy.

Honest caveat to encode: in week 1 the build data is sharp but economy data is noisy (thin listings → volatile prices). Weight the build layer as predictor early; trust gear prices more as the market gets liquid.

---

## Layer D — Community build-source scrape (the leading-of-leading layer)

The ladder shows what dedicated early players run *now* — already ahead of the masses, but the *trigger* (a guide or streamer) leads even the ladder. This layer captures that earliest signal.

**Sources:** build-guide sites (e.g. Maxroll, Mobalytics), the PoE2 subreddit, and YouTube/Twitch.

**Rules — read carefully:**
- **Prefer official APIs** with keys in `.env`: Reddit API (OAuth app), YouTube Data API. Use these instead of HTML scraping wherever available. (Note: Reddit blocks naive fetching; the API is the right path.)
- Respect `robots.txt`, each site's ToS, and rate limits. Cache responses; back off on errors.
- **Extract structured signal, not content.** Pull: build name, class/ascendancy, headline skill(s), key uniques mentioned, source URL, publish/poll timestamp, and an engagement proxy (upvotes, views, comment volume). Do **not** copy or store full guide text — short excerpts only for matching. This is both a copyright boundary and what keeps the DB lean.
- Normalize extracted build/skill/item names to the same identifiers used in Layers B and C, so a Reddit-trending build can be joined to its ladder share and its gear prices. Maintain an alias map for fuzzy matches; flag unresolved names rather than guessing.
- Output: `community_signal` rows. The cross-layer signal we want is **"build trending in community + not yet risen on ladder + key gear still cheap."** That's the earliest actionable edge.

Build this as its own module with per-source adapters so sources can be added/disabled independently.

---

## Constraints & guardrails

- **poe.ninja rate limit: 12 requests / 5 minutes.** Cache aggressively (≈1h TTL for currency, aligned to update frequency). A scheduled hourly run touching a handful of endpoints is well inside budget. Implement a shared limiter across all poe.ninja calls.
- Endpoints are undocumented-or-may-change: validate response shapes, log mismatches, fail soft.
- No auto-trading, no order placement, no account actions beyond read-only OAuth if the user opts in.
- Deterministic, re-runnable; never lose history on re-run (`INSERT OR REPLACE` on the snapshot key).

---

## Phased plan (checkpoint at each phase)

0. **Verify the API.** Read `poe.ninja/swagger`. Confirm the current PoE2 league name, and the live shapes of the currency, builds (+ snapshot versions), and unique-item endpoints. Write findings to `API_NOTES.md`. **Do not hardcode anything you haven't confirmed.**
1. **Currency layer.** Fetcher + snapshot table + movers query + CLI. Validate the `primaryValue` interpretation against the live site.
2. **Builds layer + backfill.** Pull current build meta; backfill historical snapshot versions; compute rising-build deltas; populate `build_item_link`.
3. **Unique-items layer.** Fetch item overviews; use the ~7-point sparklines for z-score momentum (relative only — do **not** store as absolute history); begin accumulating absolute snapshots; wire item movers + the confidence gate.
4. **Community scrape (Layer D).** Reddit + YouTube via official APIs first; guide-site adapters; name normalization; cross-layer "early edge" signal.
5. **Output.** Dark-theme HTML dashboard + Markdown signal brief (YAML frontmatter, Obsidian/Dataview-ready). Brief leads with: rising builds, their gear that hasn't repriced yet, top movers, and community-vs-ladder divergences.
6. **Scheduling.** Wire it to run unattended (see decision below).

---

## Before you start, confirm with me

1. **Where does the collector run?** Options: (a) my machine on a local cron/Task Scheduler; (b) a GitHub Actions cron (no machine needs to stay on — best for an unbroken time-series); (c) standalone on my friend's machine. This decides the scheduling + packaging in Phase 6. Recommended default if I don't specify: **GitHub Actions cron**, with the DB committed back to the repo or stored as an artifact, and the dashboard published via GitHub Pages.
2. **Current PoE2 league name** (exact, case-sensitive) — pull it from the live site if I haven't given it.

Ask these two questions, then begin at Phase 0.
