"""
MoneyPuller - fetch utilities for Moneycontrol Trade Spotlight pages.

Plain urllib (no external dependencies) with browser-like headers, since
moneycontrol.com returns 403 to bare non-browser clients.
"""

import time
import urllib.request

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

RETRIES = 3
TIMEOUT = 30


def get_url(url: str) -> str:
    """Fetch a URL and return the response body as text. Raises on final failure."""
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                # Moneycontrol serves gzip/deflate only if requested; urllib
                # does not request compression, so raw bytes are plain text.
                data = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return data.decode(charset, errors="replace")
        except Exception as err:  # noqa: BLE001 - retry any network hiccup
            last_err = err
            if attempt < RETRIES:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Failed to fetch {url} after {RETRIES} attempts: {last_err}")
