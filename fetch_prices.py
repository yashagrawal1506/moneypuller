"""Batch-capture prices for all mapped symbols.

- Iterates the `symbols` table (799 mapped)
- 3.2s pause between Yahoo calls (rate-limit friendly: ~50 min for all)
- Checkpointed via data/raw/prices/<symbol>.json cache (TTL 20h), so a
  re-run skips fresh symbols; failures logged, never fatal
- Optional time budget arg (seconds) like backfill.py
"""

import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from moneypuller import prices  # noqa: E402

ERR_LOG = Path("data/price_errors.log")
# MP_PAUSE env var overrides the default 3.2s pause (e.g. MP_PAUSE=1.0 when
# Yahoo is not throttling); retry/backoff in prices.py absorbs any 429s
PAUSE = float(os.environ.get("MP_PAUSE", "3.2"))


def main() -> None:
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 1e9
    conn = sqlite3.connect("data/moneypuller.db")
    symbols = [r[0] for r in conn.execute(
        """SELECT s.yahoo_symbol, COUNT(*) n FROM symbols s
           JOIN recommendations r ON r.stock_name = s.stock_name
           WHERE s.yahoo_symbol IS NOT NULL
           GROUP BY s.yahoo_symbol ORDER BY n DESC""")]
    print(f"{len(symbols)} distinct symbols to capture", flush=True)

    done = fail = empty = skipped = 0
    t0 = time.time()
    for i, sym in enumerate(symbols):
        if prices.is_cached_fresh(sym):
            skipped += 1          # cache hit: free, no pause needed
            n, note, _ = prices.capture_symbol(sym, conn)
            continue
        if time.time() - t0 > budget:
            print(f"\nPAUSED at {i}/{len(symbols)} after {time.time()-t0:.0f}s "
                  f"(cached={skipped} - re-run to continue)")
            break
        n, note, _ = prices.capture_symbol(sym, conn)
        if note == "OK":
            done += 1
        elif note == "EMPTY":
            empty += 1
        else:
            fail += 1
            with open(ERR_LOG, "a", encoding="utf-8") as f:
                f.write(f"{sym}: {note}\n")
        if (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{len(symbols)} done={done} skip={skipped} "
                  f"fail={fail} empty={empty} ({time.time()-t0:.0f}s)", flush=True)
        time.sleep(PAUSE)

    conn.close()
    print(f"\nDONE: ok={done} skip={skipped} fail={fail} empty={empty} "
          f"({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
