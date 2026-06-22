"""Render a self-contained dark HTML dashboard (inline CSS+JS, one base64 font).

Instrument-grade trading-terminal layout for the PoE2 signal system. Pure: dict
in, string out — all formatting lives here, signal logic stays untouched. Design
direction is codified in DESIGN_BRIEF.md (PoE palette, three-tier hierarchy,
conviction fills, range tracks). The page is a generator template, not a
hand-edited file, and must render with 0 / many signals and very long names.

Colour-as-meaning (PoE rarity language):
  amber/gold  -> unique items / highest-conviction signals
  gold-orange -> currency
  cool blue   -> rise / near-floor buy ("magic"-tier, opportunity)
  blood red   -> fall / running-hot / sell (danger)  [reserved, never decorative]
"""
from __future__ import annotations
import base64
import html as _html
import math
from pathlib import Path

# --- self-hosted display serif, base64-inlined (no CDN, no runtime request) ----
# Cinzel 600 (OFL), latin subset. Masthead + section headers only; never data.
_FONT_PATH = Path(__file__).resolve().parent / "assets" / "cinzel-600-latin.woff2"
try:
    _FONT_B64 = base64.b64encode(_FONT_PATH.read_bytes()).decode("ascii")
except OSError:
    _FONT_B64 = ""  # degrade gracefully to the system-serif fallback

_FONT_FACE = (
    "@font-face{font-family:'Cinzel';font-style:normal;font-weight:600;"
    f"font-display:swap;src:url(data:font/woff2;base64,{_FONT_B64}) format('woff2')}}"
    if _FONT_B64 else ""
)

_CSS = """
:root{
  --void:#0B0A07;--panel:#14120D;--inset:#100E09;--border:#2A251B;--border-bri:#3B3426;
  --fg:#ECE6DA;--muted:#9A9080;--faint:#5E564A;
  --amber:#E8A33D;--amber-lit:#FFC766;   /* unique / conviction / brand        */
  --gold:#C9892F;                         /* currency                           */
  --blue:#6FA2D6;                         /* rise / buy-cold / magic-tier        */
  --red:#C9554F;                          /* fall / running-hot / sell (danger)  */
  --serif:'Cinzel',Georgia,'Times New Roman',serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono',Consolas,'Liberation Mono',monospace;
  --sans:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--void);color:var(--fg);font:14px/1.5 var(--sans);
  font-variant-numeric:tabular-nums}
.wrap{max-width:1200px;margin:0 auto;padding:24px 20px 72px}

/* --- masthead + status bar ------------------------------------------------- */
.top{border-bottom:1px solid var(--border-bri);padding-bottom:14px;margin-bottom:6px}
h1{font-family:var(--serif);font-weight:600;font-size:26px;line-height:1.1;margin:0;
  letter-spacing:.10em;text-transform:uppercase;color:var(--fg)}
h1 .x{color:var(--amber)}
.status{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:8px;
  color:var(--muted);font:12px/1.4 var(--mono)}
.status .sep{color:var(--faint)}
.live{display:inline-flex;align-items:center;gap:6px;margin-left:auto;
  letter-spacing:.14em;font-weight:600}
.live .dot{width:8px;height:8px;border-radius:50%;background:var(--faint)}
.live.on{color:var(--amber)}
.live.on .dot{background:var(--amber);box-shadow:0 0 10px var(--amber);
  animation:pulse 2.6s ease-in-out infinite}
.live.off{color:var(--faint)}

/* --- KPI row --------------------------------------------------------------- */
.kpi{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0 6px}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:6px;
  padding:11px 16px;min-width:128px;flex:1 1 128px}
.stat .sv{font:600 24px/1.1 var(--mono)}
.stat .sl{color:var(--muted);font-size:11px;text-transform:uppercase;
  letter-spacing:.06em;margin-top:3px}
.stat.hero.on{border-color:rgba(232,163,61,.55)}
.stat.hero.on .sv{color:var(--amber-lit);text-shadow:0 0 16px rgba(232,163,61,.45);
  animation:pulse 2.6s ease-in-out infinite}
.stat.hero.on .sl{color:var(--amber)}
.stat.hero.off{opacity:.62}
.stat.hero.off .sv{color:var(--faint)}

/* --- sections -------------------------------------------------------------- */
.sec{margin-top:30px}
.sec-h{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--border);
  padding-bottom:6px;margin-bottom:8px}
h2{font-family:var(--serif);font-weight:600;font-size:15px;margin:0;
  letter-spacing:.07em;text-transform:uppercase}
.sec-m{color:var(--faint);font:11px/1 var(--mono);letter-spacing:.02em}
.badge{font:600 10px/1 var(--mono);letter-spacing:.12em;color:var(--amber);
  border:1px solid rgba(232,163,61,.45);border-radius:3px;padding:3px 5px}
.accent-cur h2{color:var(--gold)}
.accent-cur .sec-h{border-bottom-color:rgba(201,137,47,.40)}
.accent-uniq h2{color:var(--amber)}
.accent-uniq .sec-h{border-bottom-color:rgba(232,163,61,.40)}
.tier1 h2{font-size:17px}
.tier1 .sec-h{border-bottom-width:2px}

/* tier-3 empty states recede to one quiet line */
.sec-empty{display:flex;align-items:baseline;gap:10px;margin-top:14px;padding:5px 2px;
  border-top:1px solid var(--border);color:var(--faint);font-size:12px}
.sec-empty .se-t{font-family:var(--serif);text-transform:uppercase;letter-spacing:.07em;
  font-size:12px;color:var(--muted)}
.sec-empty .se-m{font:10px/1 var(--mono)}
.sec-empty .se-n{margin-left:auto;font-style:italic}

/* --- tables ---------------------------------------------------------------- */
.tscroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--border);border-radius:6px;overflow:hidden;font-family:var(--mono)}
th,td{padding:7px 12px;text-align:right;border-bottom:1px solid var(--border);
  font-size:12.5px;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{position:sticky;top:0;z-index:2;background:var(--inset);color:var(--muted);
  font:600 11px/1 var(--sans);text-transform:uppercase;letter-spacing:.05em;
  cursor:pointer;user-select:none}
th:hover{color:var(--fg)}
th[aria-sort]{color:var(--amber)}
th[aria-sort="ascending"]::after{content:" \\2191"}
th[aria-sort="descending"]::after{content:" \\2193"}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(232,163,61,.05)}
tbody.flash{animation:flash .18s ease-out}
.nm span{display:inline-block;max-width:240px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;vertical-align:bottom}
.up{color:var(--blue)}    /* rise */
.down{color:var(--red)}   /* fall */
.z{font-weight:600}
.ty{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.spark{font-family:var(--mono);letter-spacing:1px;color:var(--faint)}

/* position-in-range micro-track: floor (cold blue) -> ceiling (hot red) */
td.pos{text-align:left}
.trk{position:relative;display:inline-block;width:72px;height:7px;background:var(--inset);
  border:1px solid var(--border);border-radius:3px;vertical-align:middle;margin-right:8px}
.trk .d{position:absolute;top:50%;width:7px;height:7px;border-radius:50%;
  transform:translate(-50%,-50%);box-shadow:0 0 0 1px var(--void)}
.trk-na{color:var(--faint)}
.pos-n{color:var(--muted);font-size:11px}

.foot{color:var(--faint);font-size:11.5px;line-height:1.6;margin-top:42px;
  border-top:1px solid var(--border);padding-top:14px;max-width:760px}

/* live Exalt:Divine rate — pinned to the viewport, rides the scroll */
.rate{position:fixed;right:18px;bottom:18px;z-index:50;display:flex;align-items:center;
  gap:8px;background:var(--panel);border:1px solid var(--border-bri);border-radius:999px;
  padding:8px 14px;font:600 12px/1 var(--mono);letter-spacing:.04em;color:var(--fg);
  box-shadow:0 6px 22px rgba(0,0,0,.55)}
.rate .rk{width:7px;height:7px;border-radius:50%;background:var(--amber);
  box-shadow:0 0 10px var(--amber);animation:pulse 2.6s ease-in-out infinite}
.rate .rl{color:var(--muted);font-weight:600;letter-spacing:.10em;text-transform:uppercase;
  font-size:10px}
.rate .rv{color:var(--amber-lit)}
.rate.warn{border-color:rgba(201,85,79,.6);color:var(--red)}
.rate.warn .rk{background:var(--red);box-shadow:0 0 10px var(--red)}
@media (max-width:640px){.rate{right:10px;bottom:10px;padding:7px 11px;font-size:11px}}

@keyframes pulse{0%,100%{opacity:1}50%{opacity:.58}}
@keyframes flash{from{opacity:.5}to{opacity:1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:640px){
  .wrap{padding:18px 12px 56px}
  h1{font-size:21px}
  .nm span{max-width:150px}
  .status{font-size:11px}
}
"""

_SORT_JS = """
(function(){
  function val(td){
    var s=td.getAttribute('data-sort');
    if(s!==null){var n=parseFloat(s);return isNaN(n)?s.toLowerCase():n;}
    var t=td.textContent.trim().replace(/[,%]/g,'');
    var n=parseFloat(t);return isNaN(n)?td.textContent.trim().toLowerCase():n;
  }
  document.querySelectorAll('table.srt').forEach(function(tbl){
    if(!tbl.tHead||!tbl.tBodies.length)return;
    var ths=tbl.tHead.rows[0].cells;
    Array.prototype.forEach.call(ths,function(th,ci){
      th.tabIndex=0;th.setAttribute('role','button');
      function sort(){
        var asc=th.getAttribute('aria-sort')!=='ascending';
        Array.prototype.forEach.call(ths,function(h){h.removeAttribute('aria-sort');});
        th.setAttribute('aria-sort',asc?'ascending':'descending');
        var tb=tbl.tBodies[0];
        var rows=Array.prototype.slice.call(tb.rows);
        rows.sort(function(a,b){
          var x=val(a.cells[ci]),y=val(b.cells[ci]);
          if(x<y)return asc?-1:1;if(x>y)return asc?1:-1;return 0;
        });
        rows.forEach(function(r){tb.appendChild(r);});
        tb.classList.remove('flash');void tb.offsetWidth;tb.classList.add('flash');
      }
      th.addEventListener('click',sort);
      th.addEventListener('keydown',function(e){
        if(e.key==='Enter'||e.key===' '){e.preventDefault();sort();}
      });
    });
  });
})();
"""


def _esc(v) -> str:
    return _html.escape(str(v))


def _ds(v) -> str:
    """data-sort value; missing sinks to the bottom on ascending sort."""
    return f"{v}" if v is not None else "-1e308"


def _fmt_price(v) -> str:
    """Absolute price, 3 significant figures, never scientific notation."""
    if v is None:
        return "–"
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.1f}"
    if a >= 1:
        return f"{v:.2f}"
    d = min(max(2 - math.floor(math.log10(a)), 2), 8)
    return f"{v:.{d}f}"


def _fmt_count(v) -> str:
    if v is None:
        return "–"
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,.1f}"


def _fmt_pct(v) -> tuple[str, str]:
    if v is None:
        return "–", ""
    cls = "up" if v > 0 else ("down" if v < 0 else "")
    return f"{v:+.1f}%", cls


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


def _nm(name) -> str:
    e = _esc(name)
    return f'<td class="nm"><span title="{e}">{e}</span></td>'


def _conviction_fill(z: float, thr: float) -> str:
    """Inline background bar on the z-cell: width+alpha scale with |z| past threshold.

    Tinted by direction (blue rise / red fall) so +2.11 reads hotter than +2.00.
    """
    i = max(0.0, min(1.0, (abs(z) - thr) / 1.0))
    rgb = "111,162,214" if z > 0 else "201,85,79"
    a = 0.14 + i * 0.20
    w = i * 100
    return f"background:linear-gradient(90deg,rgba({rgb},{a:.2f}) {w:.0f}%,transparent {w:.0f}%)"


def _track(pos) -> str:
    """Position-in-range track: marker at range_pos, cold (floor) -> hot (ceiling)."""
    if pos is None:
        return '<span class="trk-na">–</span>'
    p = max(0.0, min(1.0, pos))
    pc = p * 100
    col = "var(--blue)" if p <= 0.34 else ("var(--red)" if p >= 0.66 else "var(--muted)")
    return (f'<span class="trk" title="{pc:.0f}% of 7d range">'
            f'<span class="d" style="left:{pc:.0f}%;background:{col}"></span></span>')


def _table(headers: list[str], rows: list[str]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    return (f'<table class="srt"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table>")


def _section(title: str, meta: str, headers: list[str], rows: list[str], *,
             tier: str, accent: str) -> str:
    """Populated -> full section; empty -> one receded tier-3 line."""
    if not rows:
        return (f'<div class="sec-empty {accent}"><span class="se-t">{_esc(title)}</span>'
                f'<span class="se-m">{_esc(meta)}</span>'
                f'<span class="se-n">no signals above threshold</span></div>')
    badge = '<span class="badge">LIVE</span>' if tier == "tier1" else ""
    return (f'<section class="sec {tier} {accent}">'
            f'<div class="sec-h"><h2>{_esc(title)}</h2>{badge}'
            f'<span class="sec-m">{_esc(meta)}</span></div>'
            f'<div class="tscroll">{_table(headers, rows)}</div></section>')


def _cur_mom_row(h: dict, thr: float) -> str:
    z = h["z"]
    pct, pcls = _fmt_pct(h["total_change_pct"])
    return (
        f"<tr>{_nm(h['name'])}"
        f'<td class="z {"up" if z>0 else "down"}" data-sort="{z:.4f}" '
        f'style="{_conviction_fill(z, thr)}">{z:+.2f}</td>'
        f'<td class="{pcls}" data-sort="{_ds(h["total_change_pct"])}">{pct}</td>'
        f'<td data-sort="{_ds(h["primary_value"])}">{_fmt_price(h["primary_value"])}</td>'
        f'<td data-sort="{_ds(h["volume"])}">{_fmt_count(h["volume"])}</td></tr>'
    )


def _uniq_mom_row(h: dict, thr: float) -> str:
    z = h["z"]
    pct, pcls = _fmt_pct(h["total_change_pct"])
    typ = h["item_type"].replace("Unique", "")
    return (
        f"<tr>{_nm(h['name'])}"
        f'<td class="ty" data-sort="{_esc(typ)}">{_esc(typ)}</td>'
        f'<td class="z {"up" if z>0 else "down"}" data-sort="{z:.4f}" '
        f'style="{_conviction_fill(z, thr)}">{z:+.2f}</td>'
        f'<td class="{pcls}" data-sort="{_ds(h["total_change_pct"])}">{pct}</td>'
        f'<td data-sort="{_ds(h["primary_value"])}">{_fmt_price(h["primary_value"])}</td>'
        f'<td data-sort="{_ds(h["listing_count"])}">{_fmt_count(h["listing_count"])}</td></tr>'
    )


def _mover_row(m: dict) -> str:
    pct, pcls = _fmt_pct(m["pct"])
    return (
        f"<tr>{_nm(m['name'])}"
        f'<td class="{pcls}" data-sort="{_ds(m["pct"])}">{pct}</td>'
        f'<td data-sort="{_ds(m["from"])}">{_fmt_price(m["from"])}</td>'
        f'<td data-sort="{_ds(m["to"])}">{_fmt_price(m["to"])}</td></tr>'
    )


def _trace_row(t: dict) -> str:
    pos = t["range_pos"]
    postxt = "–" if pos is None else f"{pos * 100:.0f}%"
    return (
        f"<tr>{_nm(t['name'])}"
        f'<td class="pos" data-sort="{_ds(pos)}">{_track(pos)}'
        f'<span class="pos-n">{postxt}</span></td>'
        f'<td data-sort="{_ds(t["current"])}">{_fmt_price(t["current"])}</td>'
        f'<td data-sort="{_ds(t["low"])}">{_fmt_price(t["low"])}</td>'
        f'<td data-sort="{_ds(t["high"])}">{_fmt_price(t["high"])}</td>'
        f'<td class="spark">{_esc(_spark(t["prices"]))}</td></tr>'
    )


def render_html(d: dict) -> str:
    p = d["params"]
    win_h = p["window_sec"] // 3600
    live = len(d["currency_momentum"]) + len(d["unique_momentum"])
    live_cls = "on" if live > 0 else "off"

    # Live Exalt:Divine rate — a pinned chip (position:fixed) that rides the scroll.
    rate = d.get("exalt_per_divine")
    warn = d.get("rate_warning")
    floor_ex = d.get("floor_exalt")
    if rate:
        rate_chip = (
            '<div class="rate" title="Live Exalt:Divine — Exalted Orbs per 1 Divine Orb">'
            '<span class="rk"></span><span class="rl">1 div</span>'
            f'<span class="rv">{rate:,.0f} ex</span></div>')
        foot_rate = (f"Base currency: Divine. Values shown in Divine Orbs; live rate "
                     f"1 div = {rate:,.0f} ex. Value floor {floor_ex:g} ex "
                     f"(= {floor_ex / rate:.3g} div at the current rate).")
    else:
        rate_chip = (
            f'<div class="rate warn" title="{_esc(warn or "rate unavailable")}">'
            '<span class="rk"></span><span class="rl">rate</span>'
            '<span class="rv">unavailable</span></div>')
        foot_rate = (f"Base currency: Divine. Values shown in Divine Orbs. {warn or ''} "
                     "Value floor skipped — no live Exalt:Divine rate.").strip()

    cur_mom = [_cur_mom_row(h, p["currency_z"]) for h in d["currency_momentum"]]
    uniq_mom = [_uniq_mom_row(h, p["unique_z"]) for h in d["unique_momentum"]]
    cur_mov = [_mover_row(m) for m in d["currency_movers"]]
    uniq_mov = [_mover_row(m) for m in d["unique_movers"]]
    cur_lo = [_trace_row(t) for t in d.get("currency_near_low", [])]
    cur_hi = [_trace_row(t) for t in d.get("currency_near_high", [])]
    uniq_lo = [_trace_row(t) for t in d.get("unique_near_low", [])]
    uniq_hi = [_trace_row(t) for t in d.get("unique_near_high", [])]

    spread = p.get("min_spread_pct", 5.0)
    trace_cols = ["Pos", "Now (div)", "Low", "High", "Trace"]

    sections = [
        # TIER 1 — live signals, the headline
        _section("Currency momentum",
                 f"|z| ≥ {p['currency_z']:g} · vol ≥ {p['currency_min_volume']:g}",
                 ["Currency", "z", "7d %", "Value (div)", "Volume"], cur_mom,
                 tier="tier1", accent="accent-cur"),
        _section("Unique momentum",
                 f"|z| ≥ {p['unique_z']:g} · listings ≥ {p['unique_min_listings']}",
                 ["Item", "Type", "z", "7d %", "Value (div)", "Listings"], uniq_mom,
                 tier="tier1", accent="accent-uniq"),
        # TIER 2 — populated flow
        _section("Currency movers", f"{win_h}h window",
                 ["Currency", "%", "From", "To"], cur_mov,
                 tier="tier2", accent="accent-cur"),
        _section("Unique movers", f"{win_h}h window",
                 ["Item", "%", "From", "To"], uniq_mov,
                 tier="tier2", accent="accent-uniq"),
        _section("Currency near 7d low · buy candidates",
                 f"spread ≥ {spread:g}%", ["Currency", *trace_cols], cur_lo,
                 tier="tier2", accent="accent-cur"),
        _section("Currency near 7d high · running hot",
                 "overheated", ["Currency", *trace_cols], cur_hi,
                 tier="tier2", accent="accent-cur"),
        _section("Unique near 7d low · buy candidates",
                 f"spread ≥ {spread:g}%", ["Item", *trace_cols], uniq_lo,
                 tier="tier2", accent="accent-uniq"),
        _section("Unique near 7d high · running hot",
                 "overheated", ["Item", *trace_cols], uniq_hi,
                 tier="tier2", accent="accent-uniq"),
    ]

    body = f"""
    <header class="top">
      <h1>PoE2 <span class="x">Signal</span> Terminal</h1>
      <div class="status">
        <span>{_esc(d['league'])}</span><span class="sep">·</span>
        <span>day {d['league_day']}</span><span class="sep">·</span>
        <span>{_esc(d['generated_iso'])}</span>
        <span class="live {live_cls}"><span class="dot"></span>{'LIVE' if live else 'IDLE'}</span>
      </div>
    </header>

    <div class="kpi">
      <div class="stat"><div class="sv">{d['snapshot_count']}</div><div class="sl">Snapshots</div></div>
      <div class="stat"><div class="sv">{d['currency_entities']}</div><div class="sl">Currencies</div></div>
      <div class="stat"><div class="sv">{d['unique_entities']}</div><div class="sl">Uniques</div></div>
      <div class="stat hero {live_cls}"><div class="sv">{live}</div><div class="sl">Live signals</div></div>
    </div>

    {''.join(sections)}

    <div class="foot">Decision-support only — no auto-trading. Momentum = run-#1
    sparkline z-score; movers = absolute %-change from accumulated snapshot history
    (cold until ≥2 snapshots span the window). Range tracks show where the latest
    price sits in its own 7-bucket window: cold blue near the floor, hot red near the
    ceiling. {foot_rate}</div>
    """

    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>PoE2 Signal — {_esc(d['league'])}</title>"
        f"<style>{_FONT_FACE}{_CSS}</style></head>"
        f"<body><div class=\"wrap\">{body}</div>{rate_chip}"
        f"<script>{_SORT_JS}</script></body></html>"
    )
