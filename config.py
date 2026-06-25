"""Central config: paths, league, and poe.ninja endpoint builders.

Never hardcode the league elsewhere — read it from here (which reads .env), and
validate against index-state at runtime via fetchers.resolve_league().
"""
from __future__ import annotations
import os
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
DB_PATH = DATA_DIR / "poe2_signal.db"

DATA_DIR.mkdir(exist_ok=True)


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (stdlib only). Does not override existing env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_dotenv()

# Display name used as the `league` query param. MUST be the display name, not the
# url slug (slug returns 0 lines). Confirmed 2026-06-17: "HC Runes of Aldur".
LEAGUE = os.environ.get("POE2_LEAGUE", "HC Runes of Aldur")

_start_raw = os.environ.get("POE2_LEAGUE_START", "2026-05-29T20:00:00Z")
LEAGUE_START_TS = int(
    datetime.fromisoformat(_start_raw.replace("Z", "+00:00")).timestamp()
)

# poe.ninja PoE2 API ---------------------------------------------------------
BASE = "https://poe.ninja/poe2/api"

# poe.ninja rate limit: 12 requests / 5 minutes. Shared across all calls.
RATE_MAX_CALLS = 12
RATE_PERIOD_SEC = 300
CACHE_TTL_SEC = 3600  # currency updates ~hourly

# Layer A — Bucket A fungible-by-name exchange categories. Every line in these
# carries a unique `id` slug, so variants (e.g. Uncut Skill Gem Level 17/19) never
# collide on name — keying on (category, id) keeps them distinct for free.
# (category_key, exchange_type, label). The `type` strings are NOT naive PascalCase
# of the slug — verified live 2026-06-25 against HC Runes of Aldur by capturing the
# requests poe.ninja itself makes (the endpoint returns empty `lines` for any
# unknown type, so a 0-line read does NOT confirm a valid slug). Surprises:
# omens->Ritual, abyssal-bones->Abyss, liquid-emotions->Delirium,
# lineage-support-gems->LineageSupportGems. "catalysts" is NOT a category (only the
# individual `breach-catalyst` currency item exists) and is deliberately omitted.
EXCHANGE_CATEGORIES = (
    ("currency",             "Currency",           "Currency"),
    ("fragments",            "Fragments",          "Fragments"),
    ("runes",                "Runes",              "Runes"),
    ("essences",             "Essences",           "Essences"),
    ("soul-cores",           "SoulCores",          "Soul Cores"),
    ("omens",                "Ritual",             "Omens"),
    ("liquid-emotions",      "Delirium",           "Liquid Emotions"),
    ("abyssal-bones",        "Abyss",              "Abyssal Bones"),
    ("uncut-gems",           "UncutGems",          "Uncut Gems"),
    ("lineage-support-gems", "LineageSupportGems", "Lineage Support Gems"),
    ("verisium",             "Verisium",           "Verisium"),
)

# Bucket B — carry rolled mods / per-item structure (price clouds, fake z-scores).
# Verified present in the poe.ninja nav but deliberately NOT wired: revisit per-item
# later. Drop a (key, type, label) tuple into EXCHANGE_CATEGORIES to enable one.
BUCKET_B_CATEGORIES = (
    # ("idols",            "Idols",            "Idols"),
    # ("expedition",       "Expedition",       "Expedition"),
    # ("precursor-tablets","PrecursorTablets", "Precursor Tablets"),
)

# Layer C — unique item overview types that return data for the target league.
# Verified live 2026-06-17 against HC Runes of Aldur (others return 0 lines:
# UniqueArmour, UniqueAccessory, UniqueJewel, UniqueWaystones). UniqueTablets added
# 2026-06-25 (9 lines, healthy listing counts); UniqueRelics still 404s — omitted.
UNIQUE_TYPES = (
    "UniqueWeapons",
    "UniqueArmours",
    "UniqueAccessories",
    "UniqueFlasks",
    "UniqueJewels",
    "UniqueCharms",
    "UniqueTablets",
)


def url_index_state() -> str:
    return f"{BASE}/data/index-state"


def url_exchange(exchange_type: str = "Currency", league: str = LEAGUE) -> str:
    q = urllib.parse.urlencode({"league": league, "type": exchange_type})
    return f"{BASE}/economy/exchange/current/overview?{q}"


def url_currency(league: str = LEAGUE) -> str:
    """Back-compat alias — the Currency exchange overview."""
    return url_exchange("Currency", league)


def url_item_overview(item_type: str, league: str = LEAGUE) -> str:
    q = urllib.parse.urlencode({"league": league, "type": item_type})
    return f"{BASE}/economy/stash/current/item/overview?{q}"


def url_builds_search(version: str, overview: str) -> str:
    q = urllib.parse.urlencode({"overview": overview})
    return f"{BASE}/builds/{version}/search?{q}"


def now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def league_day(ts: int, start_ts: int = LEAGUE_START_TS) -> int:
    """Integer days since league start (day 0 = launch day)."""
    return max(0, (ts - start_ts) // 86400)
