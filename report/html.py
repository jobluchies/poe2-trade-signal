"""Render a self-contained dark HTML dashboard (inline CSS, no assets, no JS deps).

One file you can open directly or drop onto GitHub Pages later (Phase 6). Pure:
dict in, string out.
"""
from __future__ import annotations
import html as _html

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#e6edf3;--muted:#8b949e;
--up:#3fb950;--down:#f85149;--accent:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
margin:34px 0 10px;border-bottom:1px solid var(--border);padding-bottom:6px}
.sub{color:var(--muted);font-size:13px;margin-bottom:8px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0 4px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;
padding:12px 16px;min-width:130px}
.card .n{font-size:22px;font-weight:600}
.card .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--border);border-radius:8px;overflow:hidden}
th,td{padding:8px 12px;text-align:right;border-bottom:1px solid var(--border)}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.04em;background:#10151c}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1c2230}
.up{color:var(--up)}.down{color:var(--down)}.tag{color:var(--accent)}
.spark{font-family:ui-monospace,Consolas,monospace;letter-spacing:1px;color:var(--accent)}
.empty{color:var(--muted);font-style:italic;padding:10px 2px}
.foot{color:var(--muted);font-size:12px;margin-top:40px}
"""


def _esc(v) -> str:
    return _html.escape(str(v))


def _num(v) -> str:
    if v is None:
        return "-"
    return f"{v:g}" if isinstance(v, float) else str(v)


def _delta(v) -> str:
    if v is None:
        return "<td>-</td>"
    cls = "up" if v > 0 else ("down" if v < 0 else "")
    sign = "+" if v > 0 else ""
    return f'<td class="{cls}">{sign}{v:g}</td>'


def _table(headers: list[str], rows: list[str]) -> str:
    if not rows:
        return '<div class="empty">No signals above threshold yet.</div>'
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _spark(prices) -> str:
    """Tiny unicode sparkline from a list of (possibly None) absolute prices."""
    vals = [p for p in (prices or []) if p is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = hi - lo
    cells = []
    for p in prices:
        if p is None:
            cells.append(" ")
        elif rng == 0:
            cells.append(_SPARK_CHARS[0])
        else:
            cells.append(_SPARK_CHARS[round((p - lo) / rng * (len(_SPARK_CHARS) - 1))])
    return "".join(cells)


def _trace_rows(rows) -> list[str]:
    out = []
    for t in rows:
        pos = "-" if t["range_pos"] is None else f"{t['range_pos'] * 100:.0f}%"
        out.append(
            f"<tr><td>{_esc(t['name'])}</td><td>{pos}</td>"
            f"<td>{_num(t['current'])}</td><td>{_num(t['low'])}</td>"
            f"<td>{_num(t['high'])}</td>"
            f'<td class="spark">{_esc(_spark(t["prices"]))}</td></tr>'
        )
    return out


def render_html(d: dict) -> str:
    p = d["params"]
    win_h = p["window_sec"] // 3600

    cur_mom = [
        f"<tr><td>{_esc(h['name'])}</td>"
        f'<td class="{"up" if h["z"]>0 else "down"}">{h["z"]:+.2f}</td>'
        f"{_delta(h['total_change_pct'])}<td>{_num(h['primary_value'])}</td>"
        f"<td>{_num(h['volume'])}</td></tr>"
        for h in d["currency_momentum"]
    ]
    uniq_mom = [
        f"<tr><td>{_esc(h['name'])}</td>"
        f'<td class="tag">{_esc(h["item_type"].replace("Unique",""))}</td>'
        f'<td class="{"up" if h["z"]>0 else "down"}">{h["z"]:+.2f}</td>'
        f"{_delta(h['total_change_pct'])}<td>{_num(h['primary_value'])}</td>"
        f"<td>{h['listing_count']}</td></tr>"
        for h in d["unique_momentum"]
    ]

    def movers_rows(rows):
        return [
            f"<tr><td>{_esc(m['name'])}</td>{_delta(m['pct'])}"
            f"<td>{_num(m['from'])}</td><td>{_num(m['to'])}</td></tr>"
            for m in rows
        ]

    body = f"""
    <h1>PoE2 Signal Dashboard</h1>
    <div class="sub">{_esc(d['league'])} · day {d['league_day']} · generated {_esc(d['generated_iso'])}</div>
    <div class="cards">
      <div class="card"><div class="n">{d['snapshot_count']}</div><div class="l">Snapshots</div></div>
      <div class="card"><div class="n">{d['currency_entities']}</div><div class="l">Currencies</div></div>
      <div class="card"><div class="n">{d['unique_entities']}</div><div class="l">Uniques</div></div>
      <div class="card"><div class="n">{len(d['currency_momentum'])+len(d['unique_momentum'])}</div><div class="l">Live signals</div></div>
    </div>

    <h2>Currency momentum · |z| ≥ {p['currency_z']}, vol ≥ {p['currency_min_volume']}</h2>
    {_table(["Currency","z","7d %","Value (ex)","Volume"], cur_mom)}

    <h2>Unique momentum · |z| ≥ {p['unique_z']}, listings ≥ {p['unique_min_listings']}</h2>
    {_table(["Item","Type","z","7d %","Value (ex)","Listings"], uniq_mom)}

    <h2>Currency movers · {win_h}h</h2>
    {_table(["Currency","%","From","To"], movers_rows(d['currency_movers']))}

    <h2>Unique movers · {win_h}h</h2>
    {_table(["Item","%","From","To"], movers_rows(d['unique_movers']))}

    <h2>Currency near 7d low · buy candidates (spread ≥ {p.get('min_spread_pct', 5.0)}%)</h2>
    {_table(["Currency","Pos","Now (ex)","Low","High","Trace"], _trace_rows(d.get('currency_near_low', [])))}

    <h2>Currency near 7d high · running hot</h2>
    {_table(["Currency","Pos","Now (ex)","Low","High","Trace"], _trace_rows(d.get('currency_near_high', [])))}

    <h2>Unique near 7d low · buy candidates</h2>
    {_table(["Item","Pos","Now (ex)","Low","High","Trace"], _trace_rows(d.get('unique_near_low', [])))}

    <h2>Unique near 7d high · running hot</h2>
    {_table(["Item","Pos","Now (ex)","Low","High","Trace"], _trace_rows(d.get('unique_near_high', [])))}

    <div class="foot">Decision-support only — no auto-trading. Momentum = run-#1 sparkline
    z-score; movers = absolute %-change from accumulated snapshot history (cold until ≥2
    snapshots span the window). Base currency: Exalted.</div>
    """

    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>PoE2 Signal — {_esc(d['league'])}</title><style>{_CSS}</style></head>"
        f"<body><div class=\"wrap\">{body}</div></body></html>"
    )
