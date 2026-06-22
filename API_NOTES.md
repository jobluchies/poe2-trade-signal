# API_NOTES.md — PoE2 poe.ninja API (Phase 0 verification)

Verified 2026-06-17 by capturing live network calls from a real (headless Chromium) browser session.
poe.ninja sits behind Cloudflare — raw `urllib`/`requests` calls return 404; a browser-like
client is required, OR we replay the exact endpoints below with proper headers (TBD in Phase 1).

The build prompt's reverse-engineered endpoints have **drifted**. Use the endpoints in this file, not the prompt.

---

## Headline: target league = HC Runes of Aldur (data confirmed across all layers)

`GET https://poe.ninja/poe2/api/data/index-state` returns the canonical league + snapshot registry.

`economyLeagues`:

| name | url | hardcore | indexed |
|------|-----|----------|---------|
| Runes of Aldur | `runesofaldur` | false | true |
| HC Runes of Aldur | `runesofaldurhc` | true | false |
| Standard | `standard` | false | false |
| Hardcore | `hardcore` | true | false |

**⚠️ The `indexed` flag does NOT gate data availability.** HC shows `indexed: false` but the endpoints
still return real data when queried directly. Confirmed for HC Runes of Aldur:
currency = 45 lines, unique-weapons = 129 lines, builds = populated. Do NOT use `indexed` to decide
whether a league has data — call the endpoint.

**⚠️ The `league` query param must be the display `name`, NOT the `url` slug.**
`league=HC Runes of Aldur` → 45 currency lines. `league=runesofaldurhc` → 0 lines (empty but 200 OK).
Map the page-URL slug → display name via `index-state` before any economy call.

| layer | page-URL slug | `league` param (economy) | `overview` param (builds) |
|-------|---------------|--------------------------|---------------------------|
| HC (target) | `runesofaldurhc` | `HC Runes of Aldur` | `hc-runes-of-aldur` |
| SC | `runesofaldur` | `Runes of Aldur` | `runes-of-aldur` |

**Never hardcode the league or snapshot version.** Resolve both at runtime from `index-state`.

---

## index-state (canonical registry)

`GET https://poe.ninja/poe2/api/data/index-state`

Top keys: `economyLeagues`, `oldEconomyLeagues`, `snapshotVersions`, `buildLeagues`, `oldBuildLeagues`.

`snapshotVersions[]` (28 entries) — the build "Time Machine" registry. Example entry:
```json
{
  "url": "runesofaldur", "name": "Runes of Aldur",
  "timeMachineLabels": ["hour-3","hour-6","hour-12","hour-18","day-1","day-2","day-3","day-4","day-5","day-6","week-1","week-2"],
  "version": "1624-20260617-57517",
  "snapshotName": "runes-of-aldur",
  "overviewType": 0,
  "passiveTree": "PassiveTree-0.5"
}
```
`version` is the path segment for the builds search endpoint; `snapshotName` is the `overview` query param.
Daily snapshots in week 1, then weekly — confirms build-meta history is backfillable.

---

## Layer A — Currency (verified)

`GET https://poe.ninja/poe2/api/economy/exchange/current/overview?league={DISPLAY_NAME}&type=Currency`
- Params: `league` = display name, space-encoded as `+` (e.g. `Runes+of+Aldur`); `type` = `Currency`.
- NOT the prompt's `currencyexchange/overview?leagueName=…&overviewName=…` (that path 404s).

Top keys: `core`, `lines`, `items`.

`lines[]` (49) — the price series. Example:
```json
{
  "id": "alch",
  "primaryValue": 0.002459,
  "volumePrimaryValue": 288.8,
  "maxVolumeCurrency": "exalted",
  "maxVolumeRate": 2.09,
  "sparkline": { "totalChange": -29.9, "data": [-38.2,-29.57,-33.11,-19.5,-24.81,-18.74,-29.9] }
}
```
- **Currency DOES ship a `sparkline`** (7 points + `totalChange`). The prompt's "no sparkline/no history" is OUTDATED.
- **Canonical unit is Divine.** Nearly every line is quoted against `divine` (`maxVolumeCurrency: "divine"`); the Divine Orb line itself is `primaryValue: 1.0`. The early "base is Exalted, ~90.9 ex/div" read (and the prompt's `chaos_equiv` model) is wrong/stale for PoE2 0.5. Store `primary_value` + `max_volume_currency` + `max_volume_rate` raw and **derive the Exalt:Divine rate live per run** from the Divine Orb line (`exalt_per_divine = 1 / max_volume_rate`, the line still quoted against `exalted`). The rate moves continuously — never hardcode it.

`items[]` (49) — metadata join: `{ id, name, image, category, detailsId }`. Join to `lines[]` on `id`.

---

## Layer C — Unique items (verified, weapons sampled)

`GET https://poe.ninja/poe2/api/economy/stash/current/item/overview?league={DISPLAY_NAME}&type={ITEM_TYPE}`
- `type` sampled: `UniqueWeapons`. Other types (UniqueArmour, UniqueAccessories, etc.) TBD — confirm in Phase 3.

Top keys: `core`, `lines`.

`lines[]` (148 for weapons) — example fields:
```json
{
  "id": 754, "itemId": "The Dancing Dervish Scimitar", "detailsId": "the-dancing-dervish-scimitar",
  "name": "The Dancing Dervish", "baseType": "Scimitar", "icon": "https://web.poecdn.com/...",
  "levelRequired": 16, "category": "[Sword|One Hand Sword]",
  "primaryValue": 6832, "listingCount": 2, "corrupted": false,
  "sparkLine": { "totalChange": 10.02, "data": [0,-12.72,-14.52,-16.2,-14.27,8.76,10.02] },
  "explicitModifiers": [ { "text": "...", "optional": false } ]
}
```
- Note casing inconsistency: currency uses `sparkline`, items use `sparkLine`. Handle both.
- `listingCount` + `primaryValue` feed the confidence gate (thin listings = suppress / flag).

---

## Layer B — Builds (verified, pattern confirmed)

Search: `GET https://poe.ninja/poe2/api/builds/{version}/search?overview={snapshotName}`
- `version` = `snapshotVersions[].version` (e.g. `1624-20260617-57517`); `overview` = `snapshotName` (e.g. `runes-of-aldur`).
- Backfill = iterate `snapshotVersions` (each is a historical snapshot).

Dictionary: `GET https://poe.ninja/poe2/api/builds/dictionary/{hash}`
- Many calls per page load — appears to resolve hashed ids (skills/items/etc.) to names. Map exact shapes in Phase 2.

Known quirk (per poe.ninja FAQ): character API sometimes reports the secondary weapon set as primary — flag low-confidence build rows rather than dropping.

---

## Constraints (unchanged from prompt, still apply)

- Rate limit: 12 requests / 5 min. Shared limiter across all poe.ninja calls. Cache ~1h.
- Cloudflare blocks naive clients → 404. Phase 1 must solve fetch transport (browser-replayed headers, or headless browser as a fallback).
- Validate response shapes every run; log mismatches; fail soft per source.
