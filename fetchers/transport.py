"""Playwright fetch transport with a shared rate limiter and on-disk cache.

poe.ninja is behind Cloudflare — plain urllib/requests get 404. A real browser
engine passes. We load the JSON endpoint as a page and read the body text.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import config

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class RateLimiter:
    """Sliding-window limiter: at most `max_calls` per `period` seconds."""

    def __init__(self, max_calls: int, period: int):
        self.max_calls = max_calls
        self.period = period
        self.calls: list[float] = []

    def acquire(self) -> None:
        now = time.monotonic()
        self.calls = [t for t in self.calls if now - t < self.period]
        if len(self.calls) >= self.max_calls:
            sleep_for = self.period - (now - self.calls[0]) + 0.5
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < self.period]
        self.calls.append(time.monotonic())


class Transport:
    def __init__(self, cache_dir: Path = config.CACHE_DIR,
                 cache_ttl: int = config.CACHE_TTL_SEC, headless: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_ttl = cache_ttl
        self.headless = headless
        self.limiter = RateLimiter(config.RATE_MAX_CALLS, config.RATE_PERIOD_SEC)
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "Transport":
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page(user_agent=_UA)
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"{h}.json"

    def get_json(self, url: str, use_cache: bool = True) -> Any:
        cp = self._cache_path(url)
        if use_cache and cp.exists() and (time.time() - cp.stat().st_mtime) < self.cache_ttl:
            return json.loads(cp.read_text(encoding="utf-8"))
        if self._page is None:
            raise RuntimeError("Transport must be used as a context manager (with Transport() as t:)")
        self.limiter.acquire()
        self._page.goto(url, wait_until="load", timeout=60000)
        body = self._page.inner_text("body")
        data = json.loads(body)
        cp.write_text(json.dumps(data), encoding="utf-8")
        return data
