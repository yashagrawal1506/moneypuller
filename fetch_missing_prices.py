"""Fetch prices only for symbols that have leads but no price rows yet.

Usage: python fetch_missing_prices.py [budget_seconds]
"""

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from moneypuller import db
from moneypuller.prices import capture_symbol

BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 600

conn = db.connect()
symbols = [r[0] for r in conn.execute(
    """SELECT DISTINCT s.yahoo_symbol FROM symbols s
       JOIN recommendations r ON r.stock_name = s.stock_name
       WHERE s.yahoo_symbol IS NOT NULL
         AND s.yahoo_symbol NOT IN (SELECT DISTINCT symbol FROM prices)
       ORDER BY s.yahoo_symbol""")]
n_total = len(symbols)
print(f"{n_total} symbols without price rows")

ok = fail = empty = 0
t0 = time.time()
for i, sym in enumerate(symbols, start=1):
    if time.time() - t0 > BUDGET:
        print(f"PAUSED at {i}/{n_total} after {time.time() - t0:.0f}s "
              f"(re-run to continue)")
        break
    n, note, _ = capture_symbol(sym, conn)
    if note == "OK":
        ok += 1
    elif note == "EMPTY":
        empty += 1
    else:
        fail += 1
        print(f"  FAIL {sym}: {note}", flush=True)
    if i % 20 == 0:
        print(f"  ... {i}/{n_total} ok={ok} fail={fail} empty={empty} "
              f"({time.time() - t0:.0f}s)", flush=True)

print(f"DONE: ok={ok} fail={fail} empty={empty} "
      f"({time.time() - t0:.0f}s)")
conn.close()
