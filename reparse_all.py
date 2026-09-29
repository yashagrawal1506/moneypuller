"""Re-parse all cached article HTML and upsert into the DB.

Use after parser fixes: rebuilds articles + recommendations from
data/raw/articles/*.html without any network access. URLs are recovered
from data/article_urls.txt by the numeric slug, so genuinely new articles
(recovered by parser fixes) get their real Moneycontrol URL.

Usage: python reparse_all.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from moneypuller import db, parser

ART_DIR = Path("data/raw/articles")
URLS_FILE = Path("data/article_urls.txt")


def slug_to_url() -> dict[str, str]:
    out = {}
    for line in URLS_FILE.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if not url:
            continue
        m = re.search(r"-(\d+)\.html$", url)
        if m:
            out[m.group(1)] = url
    return out


def main() -> None:
    urls = slug_to_url()
    files = sorted(ART_DIR.glob("*.html"))
    conn = db.connect()
    articles = recs = empty = 0
    no_url = []
    for i, f in enumerate(files, start=1):
        url = urls.get(f.stem)
        if not url:
            no_url.append(f.name)
            continue
        html = f.read_text(encoding="utf-8", errors="replace")
        art = parser.extract_article(html, url)
        if not art.recommendations:
            empty += 1
            continue
        db.save_article(conn, art)
        articles += 1
        recs += len(art.recommendations)
        if i % 100 == 0:
            print(f"  ... {i}/{len(files)} articles", flush=True)
    conn.close()

    print(f"\nre-parsed {articles} articles ({empty} empty), "
          f"{recs} recommendations total")
    if no_url:
        print(f"skipped (no url in {URLS_FILE}): {len(no_url)} -> "
              + ", ".join(no_url[:8]) + (" ..." if len(no_url) > 8 else ""))


if __name__ == "__main__":
    main()
