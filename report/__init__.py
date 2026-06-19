"""Output layer (Phase 5): collect signals -> Markdown brief + dark HTML dashboard.

    from report import generate
    paths = generate(con)   # writes output/signal-brief.md + output/dashboard.html
"""
from __future__ import annotations
from pathlib import Path

import config
from .collect import collect
from .markdown import render_markdown
from .html import render_html

OUTPUT_DIR = config.ROOT / "output"

__all__ = ["collect", "render_markdown", "render_html", "generate", "OUTPUT_DIR"]


def generate(con, league: str = config.LEAGUE, out_dir: Path = OUTPUT_DIR,
             **params) -> dict:
    """Build both artifacts and write them. Returns {'markdown': path, 'html': path, 'data': dict}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = collect(con, league, **params)

    md_path = out_dir / "signal-brief.md"
    html_path = out_dir / "dashboard.html"
    md_path.write_text(render_markdown(data), encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")
    return {"markdown": md_path, "html": html_path, "data": data}
