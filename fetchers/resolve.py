"""Resolve and validate the league against the live index-state registry.

The `indexed` flag does NOT gate data availability (HC shows indexed:false but
returns data). We use index-state only to map an input to the canonical display
name and to look up build snapshot versions (Phase 2).
"""
from __future__ import annotations
from typing import Any, Optional

import config
from .transport import Transport


def fetch_index_state(transport: Transport) -> dict:
    return transport.get_json(config.url_index_state())


def resolve_league(transport: Transport, requested: str = config.LEAGUE) -> tuple[Optional[str], dict]:
    """Return (canonical_display_name, index_state). name is None if not found."""
    idx = fetch_index_state(transport)
    pool = idx.get("economyLeagues", []) + idx.get("buildLeagues", [])
    req = requested.strip().lower()
    for lg in pool:
        candidates = {
            (lg.get("name") or "").lower(),
            (lg.get("displayName") or "").lower(),
            (lg.get("url") or "").lower(),
        }
        if req in candidates:
            return lg.get("name"), idx
    return None, idx


def find_build_snapshot(idx: dict, league_name: str) -> Optional[dict]:
    """Find the current build snapshot version entry for a league (Phase 2)."""
    target = league_name.strip().lower()
    for sv in idx.get("snapshotVersions", []):
        if (sv.get("name") or "").lower() == target:
            return sv
    return None
