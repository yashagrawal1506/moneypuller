"""MoneyPuller master backfill: 2025-04-01 -> today.

- Reads data/article_urls.txt (newest first)
- Includes an article if its record_date (trading day) or publish date >= 2025-04-01
- Checkpoint: scraped URLs go to data/scraped_ids.txt; re-runs skip them
- Raw HTML cached in data/raw/articles/<id>.html (also resume-friendly)
- Errors logged to data/scrape_errors.log; never stops the run
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from moneypuller import db, parser  # noqa: E402
from moneypuller.fetch import get_url  # noqa: E402

CUTOFF = "2025-04-01"
DATE_RE = re.compile(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})')
RAW_DIR = Path("data/raw/articles")
SCRAPE_LOG = Path("data/scraped_ids.txt")
ERR_LOG = Path("data/scrape_errors.log")
SLEEP = 0.7
MAX_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 1e9


def load_checkpoints() -> set[str]:
    if SCRAPE_LOG.exists():
        return set(SCRAPE_LOG.read_text(encoding="utf-8").split())
    return set()


def checkpoint(id_: str) -> None:
    with open(SCRAPE_LOG, "a", encoding="utf-8") as f:
        f.write(id_ + "\n")


def main() -> None:
    urls = Path("data/article_urls.txt").read_text(encoding="utf-8").split()
    done = load_checkpoints()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = db.connect()

    total = included = skipped_date = skipped_done = parsed = errors = 0
    t0 = time.time()

    for i, url in enumerate(urls):
        if time.time() - t0 > MAX_SECONDS:
            print(f"\nPAUSED at index {i} after {time.time() - t0:.0f}s "
                  f"(checkpointed - re-run to continue)")
            break
        total += 1
        art_id = url.rsplit("-", 1)[-1].replace(".html", "")
        if art_id in done:
            skipped_done += 1
            continue

        raw_path = RAW_DIR / f"{art_id}.html"
        try:
            if raw_path.exists() and raw_path.stat().st_size > 10000:
                html = raw_path.read_text(encoding="utf-8", errors="replace")
            else:
                html = get_url(url)
                raw_path.write_text(html, encoding="utf-8")

            m = DATE_RE.search(html)
            pub = m.group(1) if m else None
            art = parser.extract_article(html, url)
            rec_date = art.record_date or pub

            # date gate: keep articles for trading days on/after 2025-04-01
            gate = max(x for x in (rec_date, pub) if x) if (rec_date or pub) else None
            if gate and gate < CUTOFF:
                skipped_date += 1
                checkpoint(art_id)
                continue

            if art.recommendations:
                db.save_article(conn, art)
                parsed += len(art.recommendations)
                included += 1
                if included % 25 == 0:
                    elapsed = time.time() - t0
                    print(f"  ... {included} articles, {parsed} leads "
                          f"({elapsed:.0f}s)", flush=True)
            else:
                # fetched but nothing parsed - worth flagging
                with open(ERR_LOG, "a", encoding="utf-8") as ef:
                    ef.write(f"NOPARSE {pub} {url}\n")
                errors += 1
            checkpoint(art_id)
        except Exception as err:  # noqa: BLE001 - keep the batch alive
            errors += 1
            with open(ERR_LOG, "a", encoding="utf-8") as ef:
                ef.write(f"ERROR {url}: {err}\n")
            time.sleep(2)

        time.sleep(SLEEP)

    conn.close()
    elapsed = time.time() - t0
    print(f"\nDONE in {elapsed:.0f}s: {included} articles kept, {parsed} leads, "
          f"{skipped_date} before cutoff, {skipped_done} already done, "
          f"{errors} errors (see {ERR_LOG})")


if __name__ == "__main__":
    main()
