"""Render the signal brief as Obsidian-friendly Markdown (YAML frontmatter +
Dataview-queryable fields + readable tables). Pure: dict in, string out.
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


def render_markdown(d: dict) -> str:
    p = d["params"]
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
        f"currency_signals: {len(d['currency_momentum'])}",
        f"unique_signals: {len(d['unique_momentum'])}",
        "tags: [poe2, market-signal]",
        "---",
        "",
        f"# PoE2 Signal Brief — {d['league']}",
        "",
        f"> Day {d['league_day']} · generated {d['generated_iso']} · "
        f"{d['snapshot_count']} snapshot(s) · "
        f"{d['currency_entities']} currencies / {d['unique_entities']} uniques tracked · "
        f"{rate_note}",
        "",
        "Decision-support only. Momentum is run-#1 sparkline z-score; movers are "
        "absolute %-change from our own snapshot history.",
        "",
    ]

    # --- Currency momentum ---
    lines += [f"## Currency momentum (|z| ≥ {p['currency_z']}, vol ≥ {p['currency_min_volume']})", ""]
    cm = d["currency_momentum"]
    if cm:
        lines += ["| Currency | z | 7d % | value (div) | volume |",
                  "|---|--:|--:|--:|--:|"]
        for h in cm:
            lines.append(
                f"| {h['name']} | {h['z']:+.2f} | {_arrow(h['total_change_pct'])} "
                f"{_fmt(h['total_change_pct'])} | {_fmt(h['primary_value'])} | {_fmt(h['volume'])} |")
    else:
        lines.append("_No signals above threshold._")
    lines.append("")

    # --- Unique momentum ---
    lines += [f"## Unique momentum (|z| ≥ {p['unique_z']}, listings ≥ {p['unique_min_listings']})", ""]
    um = d["unique_momentum"]
    if um:
        lines += ["| Item | Type | z | 7d % | value (div) | listings |",
                  "|---|---|--:|--:|--:|--:|"]
        for h in um:
            typ = h["item_type"].replace("Unique", "")
            lines.append(
                f"| {h['name']} | {typ} | {h['z']:+.2f} | {_arrow(h['total_change_pct'])} "
                f"{_fmt(h['total_change_pct'])} | {_fmt(h['primary_value'])} | {h['listing_count']} |")
    else:
        lines.append("_No signals above threshold._")
    lines.append("")

    # --- Movers (history-based; cold until >=2 snapshots span the window) ---
    win_h = p["window_sec"] // 3600
    for title, rows in (
        (f"Currency movers ({win_h}h)", d["currency_movers"]),
        (f"Unique movers ({win_h}h)", d["unique_movers"]),
    ):
        lines += [f"## {title}", ""]
        if rows:
            lines += ["| Item | % | from | to |", "|---|--:|--:|--:|"]
            for m in rows:
                lines.append(
                    f"| {m['name']} | {_arrow(m['pct'])} {m['pct']:+.2f} | "
                    f"{_fmt(m['from'])} | {_fmt(m['to'])} |")
        else:
            lines.append("_Needs ≥2 snapshots spanning the window — momentum covers the cold-start._")
        lines.append("")

    # --- 7-bucket range position (sparkline-decoded, live from run #1) ---
    spread = p.get("min_spread_pct", 5.0)
    lines += [
        f"## 7-bucket range position (spread ≥ {spread}%)", "",
        "Where today's price sits inside its own decoded ~7-day window. "
        "`pos` = 0% at the window low, 100% at the high. "
        "Near low = cheap vs recent range; near high = running hot.", "",
    ]
    for title, rows in (
        ("Currency — near 7d low (buy candidates)", d.get("currency_near_low")),
        ("Currency — near 7d high (running hot)", d.get("currency_near_high")),
        ("Unique — near 7d low (buy candidates)", d.get("unique_near_low")),
        ("Unique — near 7d high (running hot)", d.get("unique_near_high")),
    ):
        lines += [f"### {title}", ""]
        if rows:
            lines += ["| Item | pos | now (div) | low | high | trace |",
                      "|---|--:|--:|--:|--:|---|"]
            for t in rows:
                pos = "-" if t["range_pos"] is None else f"{t['range_pos'] * 100:.0f}%"
                lines.append(
                    f"| {t['name']} | {pos} | {_fmt(t['current'])} | "
                    f"{_fmt(t['low'])} | {_fmt(t['high'])} | `{_sparkbar(t['prices'])}` |")
        else:
            lines.append("_None above the spread threshold._")
        lines.append("")

    return "\n".join(lines)
