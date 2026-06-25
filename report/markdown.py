"""Render the signal brief as Obsidian-friendly Markdown (YAML frontmatter +
Dataview-queryable fields + readable tables). Pure: dict in, string out.

Bucket A is per-category: each fungible category gets its own momentum / movers /
near-7d-low / near-7d-high block, generated generically from the `fungible` groups.
Uniques keep momentum + movers only (7d low/high deliberately removed).
"""
from __future__ import annotations


def _arrow(v) -> str:
    if v is None:
        return ""
    return "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkbar(prices) -> str:
    """Tiny unicode sparkline from a list of (possibly None) absolute prices."""
    vals = [p for p in (prices or []) if p is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = hi - lo
    out = []
    for p in prices:
        if p is None:
            out.append(" ")
        elif rng == 0:
            out.append(_SPARK_CHARS[0])
        else:
            out.append(_SPARK_CHARS[round((p - lo) / rng * (len(_SPARK_CHARS) - 1))])
    return "".join(out)


def _momentum_table(rows: list[dict], label: str) -> list[str]:
    if not rows:
        return ["_No signals above threshold._", ""]
    out = [f"| {label} | z | 7d % | value (div) | volume |", "|---|--:|--:|--:|--:|"]
    for h in rows:
        out.append(
            f"| {h['name']} | {h['z']:+.2f} | {_arrow(h['total_change_pct'])} "
            f"{_fmt(h['total_change_pct'])} | {_fmt(h['primary_value'])} | {_fmt(h['volume'])} |")
    out.append("")
    return out


def _unique_momentum_table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["_No signals above threshold._", ""]
    out = ["| Item | Type | z | 7d % | value (div) | listings |",
           "|---|---|--:|--:|--:|--:|"]
    for h in rows:
        typ = h["item_type"].replace("Unique", "")
        out.append(
            f"| {h['name']} | {typ} | {h['z']:+.2f} | {_arrow(h['total_change_pct'])} "
            f"{_fmt(h['total_change_pct'])} | {_fmt(h['primary_value'])} | {h['listing_count']} |")
    out.append("")
    return out


def _movers_table(rows: list[dict], label: str) -> list[str]:
    if not rows:
        return ["_Needs ≥2 snapshots spanning the window, or no risers above the floor._", ""]
    out = [f"| {label} | % | from | to |", "|---|--:|--:|--:|"]
    for m in rows:
        out.append(
            f"| {m['name']} | {_arrow(m['pct'])} {m['pct']:+.2f} | "
            f"{_fmt(m['from'])} | {_fmt(m['to'])} |")
    out.append("")
    return out


def _trace_table(rows: list[dict], label: str) -> list[str]:
    if not rows:
        return ["_None above the spread threshold._", ""]
    out = [f"| {label} | pos | now (div) | low | high | trace |", "|---|--:|--:|--:|--:|---|"]
    for t in rows:
        pos = "-" if t["range_pos"] is None else f"{t['range_pos'] * 100:.0f}%"
        out.append(
            f"| {t['name']} | {pos} | {_fmt(t['current'])} | "
            f"{_fmt(t['low'])} | {_fmt(t['high'])} | `{_sparkbar(t['prices'])}` |")
    out.append("")
    return out


def render_markdown(d: dict) -> str:
    p = d["params"]
    win_h = p["window_sec"] // 3600
    spread = p.get("min_spread_pct", 5.0)
    riser_ex = d.get("riser_floor_exalt")
    cur_sig = sum(len(g["momentum"]) for g in d["fungible"])
    lines: list[str] = []
    rate = d.get("exalt_per_divine")
    rate_note = (f"values in Divine · 1 div = {rate:,.0f} ex (live)"
                 if rate else "values in Divine · Exalt:Divine rate unavailable")

    # YAML frontmatter — Dataview reads these as page fields.
    lines += [
        "---",
        "type: poe2-signal-brief",
        f'league: "{d["league"]}"',
        f"league_day: {d['league_day']}",
        f"generated: {d['generated_iso']}",
        f"snapshots: {d['snapshot_count']}",
        f"currency_signals: {cur_sig}",
        f"unique_signals: {len(d['unique_momentum'])}",
        "tags: [poe2, market-signal]",
        "---",
        "",
        f"# PoE2 Signal Brief — {d['league']}",
        "",
        f"> Day {d['league_day']} · generated {d['generated_iso']} · "
        f"{d['snapshot_count']} snapshot(s) · "
        f"{d['currency_entities']} fungibles / {d['unique_entities']} uniques tracked · "
        f"{rate_note}",
        "",
        "Decision-support only. Momentum is run-#1 sparkline z-score; movers are "
        "absolute %-change from our own snapshot history (risers only).",
        "",
    ]

    # --- Bucket A: one block per fungible category -------------------------------
    for g in d["fungible"]:
        label = g["label"]
        lines += [f"## {label}", ""]
        lines += [f"### Momentum (|z| ≥ {p['currency_z']}, vol ≥ {p['currency_min_volume']})", ""]
        lines += _momentum_table(g["momentum"], label)
        lines += [f"### Movers ({win_h}h · risers ≥ {riser_ex:g} ex)", ""]
        lines += _movers_table(g["movers"], label)
        lines += [f"### Near 7d low · buy candidates (spread ≥ {spread}%)", ""]
        lines += _trace_table(g["near_low"], label)
        lines += ["### Near 7d high · running hot", ""]
        lines += _trace_table(g["near_high"], label)

    # --- Uniques: momentum + movers only (7d low/high removed) -------------------
    lines += [f"## Unique momentum (|z| ≥ {p['unique_z']}, listings ≥ {p['unique_min_listings']})", ""]
    lines += _unique_momentum_table(d["unique_momentum"])
    lines += [f"## Unique movers ({win_h}h · risers ≥ {riser_ex:g} ex)", ""]
    lines += _movers_table(d["unique_movers"], "Item")

    return "\n".join(lines)
