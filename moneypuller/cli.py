"""MoneyPuller - command line entry point."""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from moneypuller import db, parser            # noqa: E402
from moneypuller.export import DEFAULT_XLSX, export_workbook  # noqa: E402
from moneypuller.fetch import get_url          # noqa: E402

TAG_URL = "https://www.moneycontrol.com/news/tags/trade-spotlight.html"
RAW_DIR = Path("data/raw")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,*/*;q=0.8",
}

ARTICLE_LINK_RE = re.compile(
    r'href="(https?://(?:www\.)?moneycontrol\.com/news/[^"]*?trade-spotlight[^"]*?-?\d+\.html)"'
)


def discover_article_urls(max_articles: int = 2) -> list[str]:
    """Pull recent Trade Spotlight links from the tag listing page."""
    html = get_url(TAG_URL)
    urls, seen = [], set()
    for m in ARTICLE_LINK_RE.finditer(html):
        url = m.group(1)
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    # tag page repeats each link many times; unique + newest first is enough
    return urls[:max_articles]


def _maybe_export(path: str | None, show: bool = False) -> None:
    if not path:
        return
    target = Path(path) if path != "default" else DEFAULT_XLSX
    n = export_workbook(target)
    if show:
        print(f"[xlsx] wrote {n} leads to {target}")


def run(max_articles: int, show: bool, export: str | None = None) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urls = discover_article_urls(max_articles)
    if not urls:
        print("No Trade Spotlight articles found on the tag page.")
        sys.exit(1)

    conn = db.connect()
    total_recs = 0
    for url in urls:
        slug = url.rstrip(".html").rsplit("-", 1)[-1]
        raw_path = RAW_DIR / f"article_{slug}.html"
        html = get_url(url)
        raw_path.write_text(html, encoding="utf-8")

        art = parser.extract_article(html, url)
        if not art.recommendations:
            print(f"!! no recommendations parsed: {url}")
            continue
        article_id = db.save_article(conn, art)
        total_recs += len(art.recommendations)
        print(f"[ok] {art.title[:70]}  ({len(art.recommendations)} recs, "
              f"record date {art.record_date or art.article_date})")

        if show:
            for r in art.recommendations:
                tgt = ", ".join(f"{t:g}" for t in r.targets) or "-"
                print(f"    - {r.stock_name:38s} CMP {r.cmp:>9g}  {r.action or '-':8s} "
                      f"T {tgt:18s} SL {r.stop_loss or '-'}")
    conn.close()
    print(f"\nSaved {total_recs} recommendations into {db.DB_PATH}")
    _maybe_export(export, show=show)


def export_only(path: str | None) -> None:
    target = Path(path) if path not in (None, "default") else DEFAULT_XLSX
    n = export_workbook(target)
    print(f"[xlsx] wrote {n} leads to {target}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="MoneyPuller",
                                 description="Scrape Moneycontrol Trade Spotlight leads")
    ap.add_argument("-n", "--max-articles", type=int, default=2,
                    help="how many latest articles to pull (default 2)")
    ap.add_argument("--show", action="store_true",
                    help="print parsed recommendations to stdout")
    ap.add_argument("--urls", nargs="*", help="explicit article URLs to scrape")
    ap.add_argument("--export", nargs="?", const="default", default=None,
                    metavar="XLSX_PATH",
                    help="after scraping, also write an Excel workbook "
                         "(default: data/moneypuller_leads.xlsx)")
    ap.add_argument("--export-only", nargs="?", const="default", default=None,
                    metavar="XLSX_PATH",
                    help="skip scraping; export the existing database to Excel")
    args = ap.parse_args()

    if args.export_only is not None:
        export_only(args.export_only)
        return

    if args.urls:
        for u in args.urls:
            html = get_url(u)
            art = parser.extract_article(html, u)
            conn = db.connect()
            aid = db.save_article(conn, art)
            conn.close()
            print(f"[ok] {art.title[:70]}  ({len(art.recommendations)} recs)")
            if args.show:
                for r in art.recommendations:
                    tgt = ", ".join(f"{t:g}" for t in r.targets) or "-"
                    print(f"    - {r.stock_name:38s} CMP {r.cmp:>9g}  {r.action or '-':8s} "
                          f"T {tgt:18s} SL {r.stop_loss or '-'}")
    else:
        run(args.max_articles, args.show, args.export)


if __name__ == "__main__":
    main()
