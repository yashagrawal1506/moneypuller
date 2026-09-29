"""Discover all Trade Spotlight article URLs from tag pages 1..31.

Output: data/article_urls.txt (one URL per line, newest first)
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from moneypuller.fetch import get_url  # noqa: E402

TAG = "https://www.moneycontrol.com/news/tags/trade-spotlight.html/page-{n}/"
ARTICLE_RE = re.compile(
    r'href="(https?://www\.moneycontrol\.com/news/[^"]*trade-spotlight[^"]*?-\d+\.html)"')
MAX_PAGES = 31


def main() -> None:
    urls: dict[str, None] = {}
    for page in range(1, MAX_PAGES + 1):
        html = get_url(TAG.format(n=page))
        found = ARTICLE_RE.findall(html)
        new = [u for u in found if u not in urls]
        for u in found:
            urls.setdefault(u)
        print(f"page {page:2d}: {len(found):2d} links ({len(new)} new), total {len(urls)}",
              flush=True)
        time.sleep(0.8)

    out = Path("data/article_urls.txt")
    out.write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"\nwrote {len(urls)} URLs to {out}")


if __name__ == "__main__":
    main()
