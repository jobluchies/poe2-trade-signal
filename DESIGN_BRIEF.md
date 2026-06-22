# DESIGN_BRIEF.md — PoE2 Signal Dashboard (presentation layer)

Durable design instructions for the dashboard redesign. The data pipeline and
signal logic are **out of scope** — this governs only how signals are rendered.
The dashboard HTML is **auto-generated** by `report/html.py` on every refresh and
deploys as a static site to GitHub Pages: the deliverable is a better
template/generator + stylesheet, **not** a hand-edited page. Vanilla HTML/CSS/JS,
no build step. Must render correctly with 0 signals, many signals, and very long
item names.

## Product framing
Real-time financial / market-signal dashboard (a trading terminal) for an in-game
economy (Path of Exile 2). Archetypes: Real-Time Monitoring, Financial Dashboard,
Data-Dense Dashboard. Restrained HUD / Sci-Fi FUI feel — precise and kinetic, NOT
a gamer skin.

## Anti-patterns to enforce
No AI purple/pink gradients. No glassmorphism blur over data. No decorative noise.
No neon. Direction colors desaturated and accessible, not bright.

## Hierarchy — three tiers (the core UX problem)
Everything currently has equal weight. Fix it:
- **TIER 1 — Live signals are the headline.** Strongest accent, top of flow. The
  "LIVE SIGNALS" KPI reacts to its value: neutral/dim at 0, lit when > 0.
- **TIER 2 — Populated tables** (momentum, buy candidates, running hot): dense,
  clean, scannable.
- **TIER 3 — Empty states** ("No signals above threshold yet") RECEDE to a thin
  de-emphasized line, not a full section.

## Information design (where it earns the "designed" look)
- Tabular/monospace numerals so every numeric column aligns; consistent decimal
  precision per column. Never scientific notation in the UI.
- **Conviction encoding on z-score:** subtle intensity bar / background fill
  scaled to |z|, so +2.11 reads hotter than +2.00.
- **Position-in-range indicator** on buy/sell-candidate tables: a small track
  showing where NOW sits between 7D LOW and HIGH. "Near the floor" and "running
  hot" instantly visual. Push the existing sparkline trace further.
- Sortable columns + sticky headers. Restrained motion (smooth sort transitions,
  a subtle pulse on live signals only). Readable on a phone.
- Keep threshold annotations (|Z| ≥ 2.0 etc.) visible but as quiet metadata.

## Aesthetic anchor: Path of Exile, translated — NOT skeuomorphic
The visual identity should evoke Path of Exile's world WITHOUT copying its in-game
UI chrome. Borrow the mood and the color language; leave the ornamentation behind.

BORROW:
- Palette: near-black / deep charcoal base, desaturated grungy earth undertones,
  amber/gold as the primary accent, occult/blood red reserved STRICTLY for
  danger/sell/overheated states.
- Mood: heavy, premium-dark, precise. Weighty but not cluttered.
- Color-as-meaning, mapped to PoE's rarity language that players already read
  reflexively:
    · amber/gold  → unique items / highest-conviction signals
    · gold-orange → currency
    · a cool blue → "magic"-tier / secondary signals if you need a second accent
    · red         → ONLY for sell / running-hot / danger
  Use this codified mapping consistently so color is information, not decoration.
- Typography: a heavy carved/serif display face is acceptable for the dashboard
  TITLE and section headers only (evokes the PoE logo). All DATA stays in a clean
  tabular sans / monospace numerals. Never set numbers in a decorative serif.

DO NOT (anti-patterns — these kill a triage tool):
- No parchment, stone, rusted-metal, or grunge TEXTURES on panels or tables.
- No ornate iron frames, rivets, filigree, or beveled "forged" borders.
- No drop-shadow-heavy skeuomorphic panels. Keep surfaces flat/near-flat.
- No background imagery or fantasy art behind the data.
- Don't sacrifice legibility or scan-speed for theme. If a thematic choice slows
  down reading a number, drop the theme, keep the number.

The test: it should feel like it BELONGS to Path of Exile's universe the way a
well-made companion trading site does — recognizable palette and weight, but a
clean instrument first and a themed object second.
